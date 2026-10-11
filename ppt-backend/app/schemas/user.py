"""用户相关请求/响应模型"""

from typing import Optional
from pydantic import BaseModel, Field

from app.schemas.common import PageRequest

class UserRegisterRequest(BaseModel):
    """用户注册请求"""

    username: str = Field(..., min_length=4, max_length=32, description="用户名")
    password: str = Field(..., min_length=8, max_length=64, description="密码")
    check_password: str = Field(..., min_length=8, max_length=64, alias="checkPassword", description="确认密码")

class UserLoginRequest(BaseModel):
    """用户登录请求"""

    username: str = Field(..., min_length=4, max_length=32, description="用户名")
    password: str = Field(..., min_length=8, max_length=64, description="密码")

class UserVO(BaseModel):
    """用户视图对象"""

    id: int
    username: str
    nickname: Optional[str] = None
    user_role: str = Field(..., alias="userRole")
    create_time: str = Field(..., alias="createTime")
    ppt_quota: int = Field(default=10, alias="pptQuota", description="PPT创作配额")

    class Config:
        populate_by_name = True

class LoginUserVO(BaseModel):
    """登录用户视图对象"""

    id: int
    username: str
    nickname: Optional[str] = None
    user_role: str = Field(..., alias="userRole")
    create_time: str = Field(..., alias="createTime")
    ppt_quota: int = Field(default=10, alias="pptQuota", description="PPT创作配额")
    token:Optional[str] = None

    class Config:
        populate_by_name = True


class QuotaSetRequest(BaseModel):
    """管理员设置用户配额请求"""

    user_id: int = Field(..., alias="userId", description="目标用户ID")
    ppt_quota: int = Field(..., ge=0, alias="pptQuota", description="配额值")

    class Config:
        populate_by_name = True


class QuotaPageRequest(PageRequest):
    """管理员分页查询用户配额请求"""

    username: Optional[str] = Field(default=None, description="用户名模糊搜索")
