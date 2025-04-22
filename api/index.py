from fastapi import FastAPI, HTTPException, Request
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

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class Settings(BaseSettings):
    MASTODON_BASE_URL: str = os.getenv("MASTODON_BASE_URL", "https://jiong.us")
    MASTODON_ACCOUNT_ID: str = os.getenv("MASTODON_ACCOUNT_ID", "110710864910866001")
    MAX_RETRIES: int = 3
    TIMEOUT: int = 10
    DEFAULT_PAGE_SIZE: int = 50
    MAX_PAGE_SIZE: int = 100

    @property
    def MASTODON_API_PATH(self) -> str:
        return f"/api/v1/accounts/{self.MASTODON_ACCOUNT_ID}/statuses"

    class Config:
        env_file = ".env"

settings = Settings()

class MemoResource(BaseModel):
    type: str = ""
    link: str = ""
    externalLink: str = ""

class MemoRelation(BaseModel):
    type: str = ""
    targetId: int = 0

class Memo(BaseModel):
    id: int = Field(..., description="Mastodon status ID")
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

async def get_mastodon_account_info() -> Dict[str, Any]:
    """获取 Mastodon 账户信息"""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{settings.MASTODON_BASE_URL}/api/v1/accounts/{settings.MASTODON_ACCOUNT_ID}",
                timeout=settings.TIMEOUT
            )
            response.raise_for_status()
            return response.json()
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
            id=str(mastodon_post['id']),  # 修改：强制转为字符串，避免 JSON 大整数精度问题
            creatorId=1,  # 强制设置为1
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
    limit: Optional[int] = None
):
    """获取 Memos 列表"""
    async with httpx.AsyncClient() as client:
        try:
            actual_limit = min(limit or settings.DEFAULT_PAGE_SIZE, settings.MAX_PAGE_SIZE)
            
            response = await client.get(
                f"{settings.MASTODON_BASE_URL}{settings.MASTODON_API_PATH}",
                params={'limit': actual_limit},
                timeout=settings.TIMEOUT
            )
            response.raise_for_status()
            mastodon_posts = response.json()
            
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
    if not post_id.isdigit():
        raise HTTPException(status_code=400, detail="Invalid post ID")
    
    account_info = await get_mastodon_account_info()
    redirect_url = f"{settings.MASTODON_BASE_URL}/@{account_info.get('username', 'unknown')}/{post_id}"
    return RedirectResponse(url=redirect_url)

@app.get("/api/v1/memo/{memo_id}", response_model=Memo)
async def get_memo(memo_id: str):
    """获取单个 Memo"""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{settings.MASTODON_BASE_URL}/api/v1/statuses/{memo_id}",
                timeout=settings.TIMEOUT
            )
            response.raise_for_status()
            mastodon_post = response.json()
            return convert_mastodon_to_memo(mastodon_post)
        except httpx.HTTPError:
            raise HTTPException(status_code=404, detail="Memo not found")
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