"""用户接口"""

from typing import Optional
from fastapi import APIRouter, Depends, Request, Response
from databases import Database

from app.core.database import get_db
from app.core.deps import get_current_user, require_admin
from app.schemas.common import BaseResponse
from app.schemas.user import (
    UserRegisterRequest,
    UserLoginRequest,
    LoginUserVO,
    QuotaSetRequest,
    QuotaPageRequest,
)
from app.services.user_service import UserService
from app.utils.token import set_token, remove_token, generate_token_id
from app.core.config import settings

router = APIRouter(prefix="/user", tags=["用户管理"])


@router.post("/register", response_model=BaseResponse[int])
async def register(
    request: UserRegisterRequest,
    db: Database = Depends(get_db)
):
    """用户注册"""
    service = UserService(db)
    user_id = await service.register(request)
    return BaseResponse.success(data=user_id, message="注册成功")


@router.post("/login", response_model=BaseResponse[LoginUserVO])
async def login(
    request: UserLoginRequest,
    response: Response,
    db: Database = Depends(get_db)
):
    """用户登录"""
    service = UserService(db)
    user = await service.login(request)

    # 生成 Token
    token_id = generate_token_id()

    # 保存到 Redis
    await set_token(token_id, {"user": user.model_dump(by_alias=True)})

    # 设置 Cookie
    response.set_cookie(
        key="TOKEN",
        value=token_id,
        max_age=settings.token_max_age,
        httponly=True,
        samesite="lax"
    )

    user.token = token_id


    return BaseResponse.success(data=user, message="登录成功")


@router.get("/get/login", response_model=BaseResponse[LoginUserVO])
async def get_login_user(
    user: LoginUserVO = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """通过现有 Cookie 恢复登录状态，并读取实时配额。"""
    user.ppt_quota = await UserService(db).get_quota(user.id)
    return BaseResponse.success(data=user)


@router.post("/logout", response_model=BaseResponse[bool])
async def logout(request: Request, response: Response):
    """同时撤销服务器会话和浏览器 Cookie。"""
    token_id = request.cookies.get("TOKEN")
    if token_id:
        await remove_token(token_id)
    response.delete_cookie("TOKEN")
    return BaseResponse.success(data=True)


@router.post("/quota", response_model=BaseResponse)
async def set_user_quota(
    req: QuotaSetRequest,
    db: Database = Depends(get_db),
    _admin: LoginUserVO = Depends(require_admin),
):
    """管理员设置用户配额"""
    service = UserService(db)
    await service.set_quota(req.user_id, req.ppt_quota)
    return BaseResponse.success(message="配额已更新")


@router.post("/quota/page", response_model=BaseResponse)
async def list_user_quota(
    req: QuotaPageRequest,
    db: Database = Depends(get_db),
    _admin: LoginUserVO = Depends(require_admin),
):
    """管理员分页查询用户配额"""
    service = UserService(db)
    result = await service.list_users_quota(
        current=req.current,
        page_size=req.page_size,
        username=req.username,
    )
    return BaseResponse.success(data=result)
