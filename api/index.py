from fastapi import FastAPI, HTTPException, Request, Query, Depends
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.encoders import jsonable_encoder
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
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('api.log')
    ]
)
logger = logging.getLogger(__name__)

class Settings(BaseSettings):
    MASTODON_BASE_URL: str = os.getenv("MASTODON_BASE_URL", "https://jiong.us")
    MASTODON_ACCOUNT_ID: str = os.getenv("MASTODON_ACCOUNT_ID", "110710864910866001")
    MAX_RETRIES: int = 3
    TIMEOUT: int = 10
    DEFAULT_PAGE_SIZE: int = 50
    MAX_PAGE_SIZE: int = 100
    CACHE_TTL: int = 300  # 5分钟缓存

    @property
    def MASTODON_API_PATH(self) -> str:
        return f"/api/v1/accounts/{self.MASTODON_ACCOUNT_ID}/statuses"

    class Config:
        env_file = ".env"
        env_file_encoding = 'utf-8'

settings = Settings()

class MemoResource(BaseModel):
    type: str = Field(..., description="资源类型，如image/video")
    link: str = Field(..., description="资源链接")
    externalLink: str = Field("", description="外部资源链接")

class MemoRelation(BaseModel):
    type: str = Field(..., description="关联类型")
    targetId: int = Field(..., description="目标ID")

class Memo(BaseModel):
    id: str = Field(..., description="Mastodon状态ID（字符串保证精度）")
    creatorId: int = Field(1, description="创建者ID")
    creatorName: str = Field(..., description="创建者显示名称")
    creatorUsername: str = Field(..., description="创建者用户名")
    createdTs: int = Field(..., description="创建时间戳")
    updatedTs: int = Field(..., description="更新时间戳")
    displayTs: int = Field(..., description="显示时间戳")
    content: str = Field(..., description="内容文本")
    resourceList: List[MemoResource] = Field(default_factory=list, description="资源列表")
    relationList: List[MemoRelation] = Field(default_factory=list, description="关联列表")
    visibility: str = Field("PUBLIC", description="可见性：PUBLIC/PRIVATE")
    pinned: bool = Field(False, description="是否置顶")
    rowStatus: str = Field("NORMAL", description="状态：NORMAL/ARCHIVED")

app = FastAPI(
    title="Mastodon to Memos API Bridge",
    description="将Mastodon嘟文转换为Memos格式的API接口",
    version="1.0.0",
    docs_url="/docs",
    redoc_url=None
)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 自定义异常
class MastodonAPIError(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=502, detail=f"Mastodon API Error: {detail}")

class MemoConversionError(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=500, detail=f"Memo Conversion Error: {detail}")

# 启动和关闭事件
@app.on_event("startup")
async def startup_event():
    """初始化HTTP客户端和缓存"""
    logger.info("Starting Optimized Mastodon to Memos API Bridge")
    app.state.http_client = httpx.AsyncClient(
        timeout=settings.TIMEOUT,
        limits=httpx.Limits(
            max_connections=100,
            max_keepalive_connections=20
        ),
        headers={"User-Agent": "Mastodon-Memos-Bridge/1.0"}
    )
    app.state.account_info = None
    app.state.last_fetched = 0

@app.on_event("shutdown")
async def shutdown_event():
    """清理资源"""
    await app.state.http_client.aclose()
    logger.info("Shutting down Mastodon to Memos API Bridge")

# 依赖项
async def get_http_client() -> httpx.AsyncClient:
    """获取HTTP客户端依赖"""
    return app.state.http_client

async def get_cached_account_info() -> Dict[str, Any]:
    """获取缓存的账户信息"""
    now = time.time()
    if not app.state.account_info or (now - app.state.last_fetched) > settings.CACHE_TTL:
        try:
            client = app.state.http_client
            response = await client.get(
                f"{settings.MASTODON_BASE_URL}/api/v1/accounts/{settings.MASTODON_ACCOUNT_ID}",
                timeout=settings.TIMEOUT
            )
            response.raise_for_status()
            app.state.account_info = response.json()
            app.state.last_fetched = now
        except Exception as e:
            logger.error(f"Error fetching account info: {e}")
            app.state.account_info = {
                "username": "unknown",
                "display_name": "Unknown User"
            }
    return app.state.account_info

# 工具函数
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
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    return '\n'.join(lines)

def datetime_to_timestamp(dt_str: str) -> int:
    """将ISO格式的日期时间字符串转换为Unix时间戳"""
    try:
        dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        return int(dt.timestamp())
    except Exception as e:
        logger.error(f"Error converting datetime {dt_str}: {e}")
        return int(datetime.now(timezone.utc).timestamp())

async def fetch_mastodon_posts(
    client: httpx.AsyncClient,
    max_id: Optional[str] = None,
    limit: int = 40,
    exclude_replies: bool = True,
    exclude_reblogs: bool = True
) -> List[Dict[str, Any]]:
    """获取Mastodon嘟文"""
    params = {
        "limit": min(limit, 80),
        "exclude_replies": exclude_replies,
        "exclude_reblogs": exclude_reblogs,
    }
    if max_id:
        params["max_id"] = max_id
    
    try:
        response = await client.get(
            f"{settings.MASTODON_BASE_URL}{settings.MASTODON_API_PATH}",
            params=params
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        raise MastodonAPIError(f"HTTP error: {e.response.status_code}")
    except httpx.RequestError as e:
        raise MastodonAPIError(f"Request failed: {str(e)}")

def convert_mastodon_to_memo(mastodon_post: Dict[str, Any]) -> Memo:
    """转换Mastodon嘟文为Memo格式"""
    try:
        # 强制ID转为字符串避免精度问题
        post_id = str(mastodon_post['id'])
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
            id=post_id,
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
    except KeyError as e:
        raise MemoConversionError(f"Missing field {str(e)}")
    except Exception as e:
        raise MemoConversionError(str(e))

# API端点
@app.get("/api/v1/status", summary="获取服务状态")
async def get_status():
    """检查服务状态和账户信息"""
    try:
        account_info = await get_cached_account_info()
        current_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        return {
            "status": "running",
            "current_time": current_time,
            "account": account_info['username'],
            "mastodon_url": settings.MASTODON_BASE_URL
        }
    except Exception as e:
        logger.error(f"Error in get_status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/memo", 
         response_model=List[Memo],
         summary="获取Memos列表",
         description="获取Mastodon嘟文并转换为Memos格式",
         responses={
             200: {"description": "成功返回Memo列表"},
             502: {"description": "Mastodon API访问失败"},
             500: {"description": "服务器内部错误"}
         })
async def get_memos(
    client: httpx.AsyncClient = Depends(get_http_client),
    max_id: Optional[str] = Query(None, description="分页参数，获取比该ID更早的嘟文"),
    limit: int = Query(40, ge=1, le=80, description="返回的嘟文数量"),
    exclude_replies: bool = Query(True, description="是否排除回复"),
    exclude_reblogs: bool = Query(True, description="是否排除转发")
):
    """获取并转换嘟文"""
    try:
        posts = await fetch_mastodon_posts(
            client=client,
            max_id=max_id,
            limit=limit,
            exclude_replies=exclude_replies,
            exclude_reblogs=exclude_reblogs
        )
        return [convert_mastodon_to_memo(post) for post in posts]
    except MastodonAPIError as e:
        raise
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/m/{post_id}", 
         summary="重定向到Mastodon",
         responses={307: {"description": "重定向到Mastodon原始嘟文"}})
async def redirect_to_mastodon(
    post_id: str,
    account_info: Dict[str, Any] = Depends(get_cached_account_info)
):
    """重定向到原始Mastodon嘟文"""
    if not post_id.isdigit():
        raise HTTPException(status_code=400, detail="Invalid post ID")
    redirect_url = f"{settings.MASTODON_BASE_URL}/@{account_info['username']}/{post_id}"
    return RedirectResponse(url=redirect_url, status_code=307)

@app.get("/api/v1/memo/{memo_id}", 
         response_model=Memo,
         summary="获取单个Memo",
         responses={
             200: {"description": "成功返回Memo"},
             404: {"description": "未找到指定Memo"},
             502: {"description": "Mastodon API访问失败"}
         })
async def get_memo(
    memo_id: str,
    client: httpx.AsyncClient = Depends(get_http_client)
):
    """获取单个嘟文详情"""
    try:
        response = await client.get(
            f"{settings.MASTODON_BASE_URL}/api/v1/statuses/{memo_id}",
            timeout=settings.TIMEOUT
        )
        response.raise_for_status()
        mastodon_post = response.json()
        return convert_mastodon_to_memo(mastodon_post)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise HTTPException(status_code=404, detail="Memo not found")
        raise MastodonAPIError(str(e))
    except httpx.RequestError as e:
        raise MastodonAPIError(str(e))
    except Exception as e:
        logger.error(f"Error fetching memo: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

# 全局异常处理
@app.exception_handler(MastodonAPIError)
async def mastodon_api_error_handler(request: Request, exc: MastodonAPIError):
    """Mastodon API错误处理"""
    logger.error(f"Mastodon API error: {exc.detail}")
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail}
    )

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全局异常处理"""
    logger.error(f"Unhandled exception: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    )