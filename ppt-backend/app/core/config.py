"""配置管理"""

from pathlib import Path
from typing import Literal
from urllib.parse import quote
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

# 后端文件工作区保持在 ppt-backend/；安装清单和 .env 位于仓库根目录。
BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_FILE = BASE_DIR.parent / ".env"


class Settings(BaseSettings):
    """应用配置"""

    # 服务器配置
    server_port: int = 8001
    server_host: str = "0.0.0.0"

    # 数据库配置
    db_host: str
    db_port: int = 3306
    db_name: str
    db_user: str
    db_password: str

    # Redis 配置
    redis_host: str
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str = ""

    # 业务配置
    password_salt: str
    token_max_age: int = 2592000

    # AI 配置（DashScope 通义千问）
    dashscope_api_key: str = ""
    dashscope_model: str = ""

    # Pexels 图片搜索 API
    pexels_api_key: str = ""

    # Tavily 联网检索 API（research 专家用）
    tavily_api_key: str = ""

    # LangSmith 可观测性（默认关：trace 含 LLM 输入输出/用户消息，显式开启）
    langsmith_enabled: bool = False
    langsmith_api_key: str = ""
    langsmith_project: str = "multi-agent-ppt-creator"
    langsmith_endpoint: str = "https://api.smith.langchain.com"  # 自托管在 .env 覆盖

    # 文件存储目录
    workspace_dir: str = "workspace"

    # 智能体配置
    agent_max_react_iterations: int = 10      # ReAct 最大迭代次数
    agent_max_plan_steps: int = 8             # 计划最大步骤数
    agent_enable_plan_review: bool = True     # 是否启用计划审查

    # 多智能体配置（Supervisor 多专家路由）
    use_multi_agent: bool = True              # 是否启用多智能体
    agent_multi_recursion_limit: int = 80     # 多智能体图执行步数上限（防死循环）
    agent_mode: Literal["workflow", "subagents"] = "workflow"  # 完整 PPT 接口使用 workflow

    # 大纲人工审阅（Human-in-the-loop）配置
    outline_review_enabled: bool = False      # 大纲生成后是否暂停等待人工审阅

    # 意图识别 embedding 配置
    dashscope_embedding_model: str = "text-embedding-v3"  # DashScope embedding 模型
    intent_embedding_min_score: float = 0.5   # top1 绝对下限，低于此直接走 LLM 兜底
    intent_embedding_margin: float = 0.15     # top1-top2 间隔阈值，小于此走 LLM 兜底

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    @property
    def database_url(self) -> str:
        """获取数据库连接 URL"""
        return URL.create(
            "mysql+pymysql",
            username=self.db_user,
            password=self.db_password,
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
            query={"charset": "utf8mb4"},
        ).render_as_string(hide_password=False)

    @property
    def redis_url(self) -> str:
        """获取 Redis 连接 URL"""
        if self.redis_password:
            return f"redis://:{quote(self.redis_password, safe='')}@{self.redis_host}:{self.redis_port}/{self.redis_db}"
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def workspace_path(self) -> Path:
        """获取工作区绝对路径"""
        return BASE_DIR / self.workspace_dir


settings = Settings()
