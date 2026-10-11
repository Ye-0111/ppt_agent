"""智能体模块 - 手动实现 + LangChain Agent 可切换"""

from app.core.config import settings
from app.agent.ppt_agent import PPTAgent
from app.agent.langchain_agent import LangChainAgent
from app.agent.plain_chat_agent import PlainChatAgent


ppt_agent = PPTAgent()
langchain_agent = LangChainAgent()
plain_chat_agent = PlainChatAgent()  # /chat、/chat/stream 专用：纯聊天，不走多智能体路由

if settings.use_multi_agent:
    if settings.agent_mode == "workflow":
        # Custom workflow 模式（StateGraph + supervisor 条件边路由）
        from app.agents.workflow import MultiAgent as _AgentImpl
    else:
        # Subagents 模式（主 agent 运行时调用子 agent 工具，默认）
        from app.agents.subagents import SubAgents as _AgentImpl

    multi_agent_impl = _AgentImpl()
    default_stream_agent = multi_agent_impl   # /ppt/create
    default_ppt_agent = multi_agent_impl      # 非流式 PPT
else:
    multi_agent_impl = None
    default_stream_agent = langchain_agent
    default_ppt_agent = ppt_agent

# /chat、/chat/stream 始终走纯聊天 agent（不经 intent_router，避免闲聊误判触发 create/generate_ppt）
default_chat_agent = plain_chat_agent

__all__ = [
    "ppt_agent",
    "langchain_agent",
    "plain_chat_agent",
    "multi_agent_impl",
    "default_stream_agent",
    "default_ppt_agent",
    "default_chat_agent",
]
