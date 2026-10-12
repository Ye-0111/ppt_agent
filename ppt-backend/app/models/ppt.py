"""PPT 创作记录 ORM 模型"""

from sqlalchemy import Column, BigInteger, String, DateTime, Text
from sqlalchemy.sql import func

from app.core.database import Base


class PPT(Base):
    """PPT 创作记录表"""

    __tablename__ = "sys_ppt"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="id")
    user_id = Column("userId", BigInteger, nullable=False, index=True, comment="用户ID")
    filename = Column(String(256), nullable=True, comment="生成的 pptx 文件名")
    topic = Column(String(500), nullable=True, comment="创作主题")
    style = Column(String(20), nullable=True, comment="风格")
    status = Column(String(20), nullable=False, default="SUCCESS", server_default="SUCCESS", comment="状态：SUCCESS/IN_PROGRESS/FAILED")
    create_time = Column("createTime", DateTime, nullable=False, default=func.now(), server_default=func.now(), comment="创建时间")
    stage = Column(
        String(20), nullable=False, default="CREATED", server_default="CREATED",
        comment="阶段：CREATED/OUTLINE_DONE/RESEARCH_DONE/CONTENT_DONE/BEAUTIFY_DONE",
    )
    outline = Column(Text, nullable=True, comment="大纲 JSON（outline 节点产出）")
    research = Column(Text, nullable=True, comment="研究笔记 JSON（research 节点产出）")
    session_id = Column("sessionId", String(64), nullable=True, comment="会话ID")
    update_time = Column(
        "updateTime", DateTime, nullable=False,
        default=func.now(), server_default=func.now(), onupdate=func.now(), comment="更新时间",
    )
    error_message = Column("errorMessage", String(500), nullable=True, comment="失败原因")
