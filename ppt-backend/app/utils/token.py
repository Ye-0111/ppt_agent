"""Token 管理工具"""

import uuid
import json
from typing import Optional
from app.core.config import settings
from app.core import redis as redis_module


def generate_token_id() -> str:
    """生成 Token ID"""
    return str(uuid.uuid4())


def _get_token_key(token_id: str) -> str:
    """获取 Token Key"""
    return f"token:{token_id}"


async def get_token(token_id: str) -> Optional[dict]:
    """获取 Token 数据"""
    if not redis_module.redis_client:
        return None

    key = _get_token_key(token_id)
    data = await redis_module.redis_client.get(key)

    if data:
        return json.loads(data)
    return None


async def set_token(token_id: str, data: dict, expire: Optional[int] = None):
    """设置 Token 数据"""
    if not redis_module.redis_client:
        return

    key = _get_token_key(token_id)
    expire_time = expire or settings.token_max_age

    await redis_module.redis_client.setex(
        key,
        expire_time,
        json.dumps(data)
    )


async def remove_token(token_id: str):
    """删除 Token"""
    if not redis_module.redis_client:
        return

    key = _get_token_key(token_id)
    await redis_module.redis_client.delete(key)
