"""鉴权依赖

通过 TOKEN cookie → Redis 会话 → LoginUserVO 解析当前用户。
- get_current_user: 解析当前登录用户（未登录抛 NOT_LOGIN_ERROR）
- require_admin: 在 get_current_user 基础上要求管理员角色（非管理员抛 NO_AUTH_ERROR）

注意：角色用 Redis 会话快照判断（稳定）；配额一律实时查 DB，不读快照。
"""

from typing import Optional

from fastapi import Depends, Request
from databases import Database

from app.core.database import get_db
from app.utils.token import get_token
from app.schemas.user import LoginUserVO
from app.constants.user import UserConstant
from app.core.exceptions import ErrorCode, throw_if, throw_if_not


async def get_current_user(
    request: Request,
    db: Database = Depends(get_db),
) -> LoginUserVO:
    """解析当前登录用户（必须携带有效 TOKEN cookie）"""
    token_id = request.cookies.get("TOKEN")
    throw_if(not token_id, ErrorCode.NOT_LOGIN_ERROR, "未登录")

    session_data = await get_token(token_id)
    throw_if_not(session_data, ErrorCode.NOT_LOGIN_ERROR, "登录已过期，请重新登录")

    user_dict = session_data.get("user") or {}
    throw_if_not(user_dict.get("id") is not None, ErrorCode.NOT_LOGIN_ERROR, "登录信息异常")

    return LoginUserVO(**user_dict)


async def require_admin(
    current_user: LoginUserVO = Depends(get_current_user),
) -> LoginUserVO:
    """要求当前用户是管理员"""
    throw_if(
        current_user.user_role != UserConstant.ADMIN_ROLE,
        ErrorCode.NO_AUTH_ERROR,
        "需要管理员权限",
    )
    return current_user
