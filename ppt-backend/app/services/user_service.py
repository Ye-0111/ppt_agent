"""用户服务"""

from typing import Optional
from sqlalchemy import select, func, and_
from databases import Database

from app.models.user import User
from app.schemas.user import (
    UserRegisterRequest,
    UserLoginRequest,
    LoginUserVO,
)
from app.constants.user import UserConstant
from app.core.exceptions import ErrorCode, throw_if, throw_if_not
from app.utils.password import encrypt_password


class UserService:
    """用户服务"""

    def __init__(self, db: Database):
        self.db = db

    async def register(self, request: UserRegisterRequest) -> int:
        """用户注册"""
        # 校验参数
        throw_if(
            len(request.username) < 4,
            ErrorCode.PARAMS_ERROR,
            "用户名长度不能小于 4 位"
        )
        throw_if(
            len(request.password) < 8,
            ErrorCode.PARAMS_ERROR,
            "密码长度不能小于 8 位"
        )
        throw_if(
            request.password != request.check_password,
            ErrorCode.PARAMS_ERROR,
            "两次输入的密码不一致"
        )

        # 检查用户名是否已存在
        query = select(func.count(User.id)).where(
            and_(User.username == request.username, User.status == 1)
        )
        count = await self.db.fetch_val(query)
        throw_if(count > 0, ErrorCode.USER_ALREADY_EXIST, "用户名已存在")

        # 加密密码
        encrypted_password = encrypt_password(request.password)

        # 插入用户（含默认配额）
        query = """
            INSERT INTO sys_user (username, password, nickname, userRole, ppt_quota, status, createTime)
            VALUES (:username, :password, :nickname, :userRole, :ppt_quota, 1, CURRENT_TIMESTAMP)
        """
        user_id = await self.db.execute(
            query=query,
            values={
                "username": request.username,
                "password": encrypted_password,
                "nickname": f"用户{request.username}",
                "userRole": UserConstant.DEFAULT_ROLE,
                "ppt_quota": UserConstant.DEFAULT_PPT_QUOTA,
            }
        )

        return user_id

    async def login(self, request: UserLoginRequest) -> LoginUserVO:
        """用户登录"""
        # 校验参数
        throw_if(
            len(request.username) < 4,
            ErrorCode.PARAMS_ERROR,
            "用户名长度不能小于 4 位"
        )
        throw_if(
            len(request.password) < 8,
            ErrorCode.PARAMS_ERROR,
            "密码长度不能小于 8 位"
        )

        # 查询用户
        query = select(User).where(
            and_(User.username == request.username, User.status == 1)
        )
        user = await self.db.fetch_one(query)
        throw_if_not(user, ErrorCode.USER_NOT_EXIST, "用户不存在")

        # 验证密码
        encrypted_password = encrypt_password(request.password)
        throw_if(
            user["password"] != encrypted_password,
            ErrorCode.PASSWORD_ERROR,
            "密码错误"
        )

        user_dict = dict(user)

        # 返回登录用户信息
        return LoginUserVO(
            id=user_dict["id"],
            username=user_dict["username"],
            nickname=user_dict["nickname"],
            user_role=user_dict["userRole"],
            createTime=user_dict["createTime"].isoformat(),
            ppt_quota=user_dict.get("ppt_quota", UserConstant.DEFAULT_PPT_QUOTA),
        )

    # ================================================================
    # 配额相关
    # ================================================================

    async def get_quota(self, user_id: int) -> int:
        """查询用户剩余配额"""
        row = await self.db.fetch_one(
            query="SELECT ppt_quota FROM sys_user WHERE id = :id AND status = 1",
            values={"id": user_id},
        )
        throw_if_not(row, ErrorCode.USER_NOT_EXIST, "用户不存在")
        return row["ppt_quota"]

    async def set_quota(self, user_id: int, ppt_quota: int) -> None:
        """管理员设置用户配额"""
        rowcount = await self.db.execute(
            query="UPDATE sys_user SET ppt_quota = :ppt_quota WHERE id = :id AND status = 1",
            values={"ppt_quota": ppt_quota, "id": user_id},
        )
        throw_if(not rowcount, ErrorCode.USER_NOT_EXIST, "用户不存在")

    async def list_users_quota(
        self, current: int, page_size: int, username: Optional[str] = None
    ) -> dict:
        """分页查询用户配额（管理员）"""
        where = "status = 1"
        values: dict = {}
        if username:
            where += " AND username LIKE :kw"
            values["kw"] = f"%{username}%"

        total = await self.db.fetch_val(
            query=f"SELECT COUNT(id) FROM sys_user WHERE {where}",
            values=values,
        )

        offset = (current - 1) * page_size
        rows = await self.db.fetch_all(
            query=(
                "SELECT id, username, nickname, userRole, ppt_quota, createTime "
                f"FROM sys_user WHERE {where} "
                "ORDER BY id DESC LIMIT :limit OFFSET :offset"
            ),
            values={**values, "limit": page_size, "offset": offset},
        )

        records = [
            {
                "id": r["id"],
                "username": r["username"],
                "nickname": r["nickname"],
                "userRole": r["userRole"],
                "pptQuota": r["ppt_quota"],
                "createTime": r["createTime"].isoformat() if r["createTime"] else None,
            }
            for r in rows
        ]
        return {
            "records": records,
            "total": total,
            "current": current,
            "pageSize": page_size,
        }
