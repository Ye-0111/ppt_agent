"""FastAPI 主应用入口"""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.schemas.common import BaseResponse
from app.core.config import settings
from app.core.observability import setup_langsmith
from app.core.database import database
from app.core.exceptions import BusinessException, ErrorCode
from app.core.redis import init_redis, close_redis
from app.controller import (
    user_router,
    chat_router,
    ppt_router,
    template_router,
)

# 配置日志格式
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时执行
    # LangSmith tracing 必须在任何 LLM/agent 调用前初始化（langsmith 的 get_env_var 被 lru_cache）
    setup_langsmith()
    await database.connect()
    await init_redis()
    print(f"数据库连接成功: {settings.database_url}")
    print(f"Redis 连接成功: {settings.redis_url}")

    yield

    # 关闭时执行
    await database.disconnect()
    await close_redis()
    print("应用已关闭")

# 创建 FastAPI 应用
app = FastAPI(
    title="AI PPT创作器",
    description="基于多智能体编排的 AI PPT 创作平台",
    version="0.0.1",
    lifespan=lifespan
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8200"],  # 前端开发服务器地址
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局异常处理
@app.exception_handler(BusinessException)
async def business_exception_handler(request: Request, exc: BusinessException):
    """业务异常处理"""
    return JSONResponse(
        status_code=200,
        content={
            "code": exc.error_code.code,
            "data": None,
            "message": exc.message
        }
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全局异常处理"""
    print(f"未处理的异常: {exc}")
    return JSONResponse(
        status_code=200,
        content={
            "code": ErrorCode.SYSTEM_ERROR.code,
            "data": None,
            "message": f"系统内部异常: {str(exc)}"
        }
    )

# 注册路由
app.include_router(user_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(ppt_router, prefix="/api")
app.include_router(template_router, prefix="/api")

@app.get("/", response_model=BaseResponse)
async def root():
    """根路径"""
    return BaseResponse.success(data={
        "message": "AI PPT创作器 - Python 后端",
        "version": "0.0.1",
        "docs": "/docs"
    })

@app.get("/api/hello", response_model=BaseResponse)
async def say_hello():
    """hello"""
    return BaseResponse.success(data={"message": "Hello!"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.server_host,
        port=settings.server_port,
        reload=True,
    )
