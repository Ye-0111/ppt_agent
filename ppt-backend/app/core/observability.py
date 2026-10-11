"""LangSmith 可观测性 — 启动时初始化自动 tracing + trace 上下文注入 helper。

LangSmith 的自动 tracing 由 langchain-core 读取 ``os.environ`` 中的 ``LANGSMITH_*`` 变量
驱动（见 langsmith.utils.get_env_var）。本项目用 pydantic-settings（``extra="ignore"``）
读 ``.env``，未在 Settings 中声明的 ``LANGSMITH_*`` 会被静默丢弃、不会进入 ``os.environ``，
故需 :func:`setup_langsmith` 在启动时显式同步。

顺序约束：langsmith 的 ``get_env_var`` 被 ``@lru_cache``，值在进程首次读取时缓存，
故 :func:`setup_langsmith` 必须在任何 LLM/agent 调用前执行（``main.py`` lifespan 第一行）。
"""

import logging
import os
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

# langsmith.utils.get_env_var 按命名空间顺序取首个非空值：LANGSMITH_* 优先于 LANGCHAIN_*。
# 同时写两组以最大兼容（部分 langchain 路径只认 LANGCHAIN_ 前缀）。
_ENV_NAMESPACES = ("LANGSMITH", "LANGCHAIN")


def setup_langsmith() -> bool:
    """启动时把 ``settings.langsmith_*`` 同步到 ``os.environ``，启用 langchain-core 自动 tracing。

    幂等。未启用或未配置 API key 时 no-op + warn，对业务零影响。
    Returns 是否真正启用 tracing。
    """
    if not settings.langsmith_enabled:
        logger.info("[LangSmith] 未启用（LANGSMITH_ENABLED=false），跳过 tracing")
        return False
    if not settings.langsmith_api_key:
        logger.warning(
            "[LangSmith] LANGSMITH_ENABLED=true 但未配置 LANGSMITH_API_KEY，跳过 tracing"
        )
        return False

    # 主变量用 LANGSMITH_*（langsmith 0.8.x 优先），同时回填 LANGCHAIN_TRACING_V2 兜底
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    for ns in _ENV_NAMESPACES:
        os.environ[f"{ns}_API_KEY"] = settings.langsmith_api_key
        os.environ[f"{ns}_PROJECT"] = settings.langsmith_project
        os.environ[f"{ns}_ENDPOINT"] = settings.langsmith_endpoint
    # 注意：单独 LANGCHAIN_TRACING=true 会被 langchain-core 拒绝（RuntimeError），切勿设置。

    logger.info(
        "[LangSmith] tracing 已启用 → project=%s endpoint=%s",
        settings.langsmith_project,
        settings.langsmith_endpoint,
    )
    return True


def is_tracing_enabled() -> bool:
    """运行时判断 tracing 是否生效（读 ``os.environ``，与 langchain 判断口径一致）。"""
    return (
        os.environ.get("LANGSMITH_TRACING") == "true"
        or os.environ.get("LANGCHAIN_TRACING_V2") == "true"
    )


def build_trace_metadata(
    *,
    session_id: Optional[str] = None,
    user_id: Optional[int | str] = None,
    ppt_id: Optional[int | str] = None,
    intent: Optional[str] = None,  # chat | create | enhance | analyze
    style: Optional[str] = None,
) -> dict:
    """构造 LangSmith trace metadata dict。

    丢弃 None 值、值统一转 str（LangSmith metadata 过滤字段需稳定类型）。
    返回的键直接对应 UI 侧可筛选字段：session_id / user_id / ppt_id / intent / style。
    """
    raw = {
        "session_id": session_id,
        "user_id": user_id,
        "ppt_id": ppt_id,
        "intent": intent,
        "style": style,
    }
    return {k: str(v) for k, v in raw.items() if v is not None}


def apply_trace_context(
    config: Optional[dict],
    *,
    metadata: Optional[dict] = None,
    tags: Optional[list[str]] = None,
    run_name: Optional[str] = None,
) -> dict:
    """把 LangSmith trace 字段并入 LangGraph/LangChain 的 ``RunnableConfig``。

    返回【新】dict，绝不修改入参。metadata 浅合并、tags 拼接（去重保序），
    run_name 仅在入参未指定时设置。必须保留入参 config 已有的 ``configurable`` /
    ``recursion_limit`` 等键 —— workflow 路径的 ``config['configurable']['on_stage']``
    承载断点恢复落库回调，整体替换会丢失。
    """
    cfg = dict(config) if config else {}
    if metadata:
        cfg["metadata"] = {**(cfg.get("metadata") or {}), **metadata}
    if tags:
        existing = cfg.get("tags") or []
        merged = list(existing)
        for t in tags:
            if t not in merged:
                merged.append(t)
        cfg["tags"] = merged
    if run_name and "run_name" not in cfg:
        cfg["run_name"] = run_name
    return cfg
