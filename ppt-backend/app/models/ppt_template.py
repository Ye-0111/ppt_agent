"""PPT 模板 ORM 模型"""

from sqlalchemy import Column, BigInteger, String, DateTime, Text, SmallInteger, Integer
from sqlalchemy.sql import func

from app.core.database import Base


class PptTemplate(Base):
    """PPT 模板表（仅存已含 {{占位符}} 的成品模板）"""

    __tablename__ = "sys_ppt_template"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="id")
    user_id = Column("userId", BigInteger, nullable=False, index=True, comment="上传者ID")
    name = Column(String(128), nullable=False, comment="模板名称")
    filename = Column(String(256), nullable=False, comment="模板文件名(ppt_templates/下)")
    variables = Column(Text, nullable=True, comment="占位符名 JSON 数组，如 [\"title\",\"author\"]")
    slide_count = Column("slideCount", Integer, nullable=True, comment="页数")
    is_public = Column("isPublic", SmallInteger, nullable=False, default=0, comment="0私有 1公开")
    create_time = Column("createTime", DateTime, nullable=False, default=func.now(), comment="创建时间")
    update_time = Column(
        "updateTime", DateTime, nullable=False,
        default=func.now(), onupdate=func.now(), comment="更新时间",
    )
