from fastapi import FastAPI, HTTPException, Request, Query, Header
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import httpx
from datetime import datetime, timezone
import time
import logging
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from bs4 import BeautifulSoup
import os
from pydantic_settings import BaseSettings
from enum import Enum
from typing import Literal

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 添加实例类型枚举
class InstanceType(str, Enum):
    MASTODON = "mastodon"
    GOTOSOCIAL = "gotosocial"
    PLEROMA = "pleroma"
    
class Settings(BaseSettings):
    MASTODON_BASE_URL: str = os.getenv("MASTODON_BASE_URL", "https://jiong.us")
    MASTODON_ACCOUNT_ID: str = os.getenv("MASTODON_ACCOUNT_ID", "110710864910866001")
    MASTODON_ACCESS_TOKEN: str = os.getenv("MASTODON_ACCESS_TOKEN", "")  # 新增: API访问令牌
    INSTANCE_TYPE: InstanceType = os.getenv("INSTANCE_TYPE", InstanceType.MASTODON)  # 新增实例类型    
    MAX_RETRIES: int = 3
    TIMEOUT: int = 10
    DEFAULT_PAGE_SIZE: int = 80  # 修改默认值为Mastodon单次请求最大值
    MAX_PAGE_SIZE: int = 80     # Mastodon单次请求最多80条
    MAX_PAGES: int = 5          # 最大分页数

    @property
    def MASTODON_API_PATH(self) -> str:
        return f"/api/v1/accounts/{self.MASTODON_ACCOUNT_ID}/statuses"

    class Config:
        env_file = ".env"
        use_enum_values = True  # 确保枚举值正确序列化

settings = Settings()

class MemoResource(BaseModel):
    type: str = ""
    link: str = ""
    externalLink: str = ""

class MemoRelation(BaseModel):
    type: str = ""
    targetId: int = 0

class Memo(BaseModel):
    id: str = Field(..., description="Mastodon status ID (强制字符串避免精度问题)")
    creatorId: int = Field(..., description="Mastodon account ID")
    creatorName: str = Field(..., description="Mastodon display name")
    creatorUsername: str = Field(..., description="Mastodon username")
    createdTs: int
    updatedTs: int
    displayTs: int
    content: str
    resourceList: List[MemoResource] = Field(default_factory=list)
    relationList: List[MemoRelation] = Field(default_factory=list)
    visibility: str = "PUBLIC"
    pinned: bool = False
    rowStatus: str = "NORMAL"

app = FastAPI(title="Mastodon to Memos API Bridge")

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    logger.info("Starting Mastodon to Memos API Bridge")
    logger.info(f"MASTODON_BASE_URL: {settings.MASTODON_BASE_URL}")
    logger.info(f"MASTODON_ACCOUNT_ID: {settings.MASTODON_ACCOUNT_ID}")
    logger.info(f"INSTANCE_TYPE: {settings.INSTANCE_TYPE}")

async def get_mastodon_account_info() -> Dict[str, Any]:
    """获取 Mastodon 账户信息"""
    async with httpx.AsyncClient() as client:
        try:
            headers = {"Authorization": f"Bearer {settings.MASTODON_ACCESS_TOKEN}"}
            response = await client.get(
                f"{settings.MASTODON_BASE_URL}/api/v1/accounts/{settings.MASTODON_ACCOUNT_ID}",
                headers=headers,
                timeout=settings.TIMEOUT
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                logger.error("Authentication failed: Invalid token")
                raise HTTPException(status_code=401, detail="Authentication failed")
            logger.error(f"Error fetching account info: {e}")
            raise HTTPException(status_code=e.response.status_code, detail="Failed to fetch account info")
        except Exception as e:
            logger.error(f"Error fetching account info: {e}")
            return {"username": "unknown", "display_name": "Unknown User"}

def clean_html_content(html_content: str) -> str:
    """清理HTML内容，保留格式化文本"""
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # 处理链接
    for a in soup.find_all('a'):
        href = a.get('href', '')
        text = a.get_text()
        if href and text and href != text:
            a.replace_with(f"{text} ({href})")
        else:
            a.replace_with(text)
    
    # 清理其他HTML标签但保留换行
    text = soup.get_text(separator='\n')
    
    # 清理多余的空行但保留格式
    lines = []
    for line in text.split('\n'):
        cleaned_line = line.strip()
        if cleaned_line:
            lines.append(cleaned_line)
    
    return '\n'.join(lines)

def datetime_to_timestamp(dt_str: str) -> int:
    """将ISO格式的日期时间字符串转换为Unix时间戳"""
    try:
        dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        return int(dt.timestamp())
    except Exception as e:
        logger.error(f"Error converting datetime {dt_str}: {e}")
        return int(datetime.now(timezone.utc).timestamp())

def convert_mastodon_to_memo(mastodon_post: Dict[Any, Any]) -> Memo:
    """将Mastodon帖子转换为Memo格式"""
    try:
        # 确保 mastodon_post['id'] 是字符串（如果不是，强制转换）
        post_id = str(mastodon_post['id'])  # 关键修改：无论如何都转成 str
        content = clean_html_content(mastodon_post['content'])
        created_ts = datetime_to_timestamp(mastodon_post['created_at'])
        account = mastodon_post['account']
        
        # 处理媒体附件
        resource_list = []
        for media in mastodon_post.get('media_attachments', []):
            resource_list.append(MemoResource(
                type=media['type'],
                link=media['url'],
                externalLink=media.get('remote_url', '') or media['url']
            ))
        
        return Memo(
            id=post_id,  # 使用强制转换后的字符串
            creatorId=1,
            creatorName=account['display_name'],
            creatorUsername=account['username'],
            createdTs=created_ts,
            updatedTs=created_ts,
            displayTs=created_ts,
            content=content,
            resourceList=resource_list,
            relationList=[],
            visibility="PUBLIC" if mastodon_post['visibility'] == 'public' else "PRIVATE",
            pinned=mastodon_post.get('pinned', False),
            rowStatus="NORMAL"
        )
    except Exception as e:
        logger.error(f"Error converting post: {e}")
        raise HTTPException(status_code=500, detail="Conversion error")

async def fetch_all_mastodon_posts(
    max_pages: int = settings.MAX_PAGES,
    exclude_replies: bool = True,
    exclude_reblogs: bool = True
) -> List[Dict[str, Any]]:
    """获取所有Mastodon帖子（支持分页）"""
    all_posts = []
    max_id = None
    
    async with httpx.AsyncClient() as client:
        for _ in range(max_pages):
            params = {
                'limit': settings.MAX_PAGE_SIZE,
                'exclude_replies': exclude_replies,
                'exclude_reblogs': exclude_reblogs
            }
            if max_id:
                params['max_id'] = max_id
                
            try:
                headers = {"Authorization": f"Bearer {settings.MASTODON_ACCESS_TOKEN}"}
                response = await client.get(
                    f"{settings.MASTODON_BASE_URL}{settings.MASTODON_API_PATH}",
                    params=params,
                    headers=headers,
                    timeout=settings.TIMEOUT
                )
                response.raise_for_status()
                posts = response.json()
                if not posts:
                    break
                    
                all_posts.extend(posts)
                max_id = posts[-1]['id']  # 设置下一页的max_id
                
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 401:
                    logger.error("Authentication failed: Invalid token")
                    raise HTTPException(status_code=401, detail="Authentication failed")
                logger.error(f"Error fetching posts: {e}")
                break
            except Exception as e:
                logger.error(f"Error fetching posts: {e}")
                break
                
    return all_posts

@app.get("/api/v1/status")
async def get_status():
    """获取系统状态"""
    try:
        account_info = await get_mastodon_account_info()
        current_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        return (
            f"Current Date and Time (UTC - YYYY-MM-DD HH:MM:SS formatted): {current_time}\n"
            f"Current User's Login: {account_info.get('username', 'unknown')}\n"
        )
    except Exception as e:
        logger.error(f"Error in get_status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/memo", response_model=List[Memo])
async def get_memos(
    creatorId: Optional[int] = None,
    rowStatus: Optional[str] = "NORMAL",
    limit: Optional[int] = None,
    exclude_replies: bool = Query(True, description="是否排除回复嘟文"),
    exclude_reblogs: bool = Query(True, description="是否排除转发嘟文")
):
    """获取 Memos 列表（支持分页和过滤）"""
    try:
        # 获取所有符合条件的嘟文
        mastodon_posts = await fetch_all_mastodon_posts(
            exclude_replies=exclude_replies,
            exclude_reblogs=exclude_reblogs
        )
        
        # 转换为Memo格式并过滤
        memos = []
        for post in mastodon_posts:
            try:
                memo = convert_mastodon_to_memo(post)
                if (not creatorId or memo.creatorId == creatorId) and \
                   (not rowStatus or memo.rowStatus == rowStatus):
                    memos.append(memo)
            except Exception as e:
                logger.error(f"Error processing post {post.get('id')}: {e}")
                continue
        
        # 应用limit限制
        actual_limit = min(limit or len(memos), settings.MAX_PAGE_SIZE * settings.MAX_PAGES)
        return memos[:actual_limit]

    except httpx.HTTPError as e:
        logger.error(f"HTTP error occurred: {e}")
        raise HTTPException(status_code=502, detail="Error fetching Mastodon posts")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/m/{post_id}")
async def redirect_to_mastodon(post_id: str):
    """重定向到 Mastodon 帖子"""
    # 移除 isdigit 检查，因为 GoToSocial 使用 Snowflake ID
    # if not post_id.isdigit():
    #     raise HTTPException(status_code=400, detail="Invalid post ID")
    
    try:
        account_info = await get_mastodon_account_info()
        username = account_info.get('username', 'unknown')
        
        # 根据实例类型构建不同的URL格式
        if settings.INSTANCE_TYPE == InstanceType.GOTOSOCIAL:
            redirect_url = f"{settings.MASTODON_BASE_URL}/@{username}/statuses/{post_id}"
        elif settings.INSTANCE_TYPE == InstanceType.PLEROMA:
            redirect_url = f"{settings.MASTODON_BASE_URL}/@{username}/posts/{post_id}"
        else:  # MASTODON (默认)
            redirect_url = f"{settings.MASTODON_BASE_URL}/@{username}/{post_id}"
        
        logger.info(f"Redirecting to: {redirect_url}")
        return RedirectResponse(url=redirect_url)
    except Exception as e:
        logger.error(f"Error in redirect_to_mastodon: {e}")
        raise HTTPException(status_code=500, detail="Error processing redirect")

@app.get("/api/v1/memo/{memo_id}", response_model=Memo)
async def get_memo(memo_id: str):
    """获取单个 Memo"""
    async with httpx.AsyncClient() as client:
        try:
            headers = {"Authorization": f"Bearer {settings.MASTODON_ACCESS_TOKEN}"}
            response = await client.get(
                f"{settings.MASTODON_BASE_URL}/api/v1/statuses/{memo_id}",
                headers=headers,
                timeout=settings.TIMEOUT
            )
            response.raise_for_status()
            mastodon_post = response.json()
            return convert_mastodon_to_memo(mastodon_post)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise HTTPException(status_code=401, detail="Authentication failed")
            elif e.response.status_code == 404:
                raise HTTPException(status_code=404, detail="Memo not found")
            raise HTTPException(status_code=e.response.status_code, detail="Failed to fetch memo")
        except Exception as e:
            logger.error(f"Error fetching memo: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全局异常处理"""
    logger.error(f"Global exception handler caught: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    )