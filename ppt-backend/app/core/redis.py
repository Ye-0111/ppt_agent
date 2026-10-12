"""Redis 连接管理"""

import redis.asyncio as redis
from typing import Optional
from app.core.config import settings

# Redis 连接池
redis_client: Optional[redis.Redis] = None


async def init_redis():
    """初始化 Redis 连接"""
    global redis_client
    redis_client = redis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True
    )
    try:
        await redis_client.ping()
    except Exception:
        await close_redis()
        raise


async def close_redis():
    """关闭 Redis 连接"""
    global redis_client
    if redis_client:
        client = redis_client
        redis_client = None
        await client.aclose()
