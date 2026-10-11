"""workflow 模式：StateGraph 编排 — Supervisor 路由 + Specialist 循环，直到 FINISH。

specialist ReAct agent 构造见 app.agents（每个 specialist 一个文件）；
本文件负责 workflow 专属的节点编排：为 specialist 注入 filename/style 上下文、
content 成功后回写 filename，以及图的拓扑（supervisor ↔ specialist 循环）。
"""

import json
import logging
import os
from typing import Optional

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from app.agents import build_specialist
from app.core.config import settings
from app.agents.common.llm import build_llm
from app.agents.common.tools import ROLES
from app.agents.workflow.state import AgentState
from app.agents.workflow.supervisor import SUPERVISOR, build_supervisor_node
from app.agents.workflow.router import (
    CHAT_REPLY,
    INTENT_ROUTER,
    build_chat_reply_node,
    build_intent_router_node,
)
from app.services.agent_log_service import agent_log_context

logger = logging.getLogger(__name__)


def route_after_supervisor(state: AgentState) -> str:
    """条件边路由：supervisor 的 next 决定下一个 specialist，或结束。"""
    nxt = state.get("next") or "FINISH"
    if nxt == "FINISH":
        return END
    return nxt


# create 意图并行子图节点名（compiled subgraph 作为主图的一个节点）
CREATE_PIPELINE = "create_pipeline"


def route_after_content(state: AgentState) -> list[str]:
    """create 子图内 content 之后：有 filename → 并行 fan-out [image, chart]；否则直接结束。

    image/chart/beautify 都依赖 content 产出的 PPTX 文件；content 失败（无 filename）时
    整条美化链无意义，直接 END，由 content 节点留下的错误消息兜底。
    返回 list 触发 LangGraph 同一超级步并行执行多个节点。
    """
    if state.get("filename"):
        return ["image", "chart"]
    logger.warning("[create_pipeline] content 未生成 filename，跳过 image/chart/beautify")
    return [END]


def route_create_resume(state: AgentState):
    """create 子图入口条件边（断点恢复）：按已注入的阶段跳过已完成节点。"""
    if state.get("filename"):
        return ["image", "chart"]
    if state.get("research"):
        return "content"
    if state.get("outline"):
        return "research"
    return "outline"


def route_after_intent(state: AgentState) -> str:
    """条件边路由：intent_router 的 intent 决定走 chat 直答、create 并行子图，还是 supervisor。"""
    intent = state.get("intent") or "chat"
    if intent == "chat":
        return CHAT_REPLY
    # create 走确定性并行子图（outline→research→content→[image‖chart]→beautify）
    if intent == "create":
        return CREATE_PIPELINE
    # enhance / analyze 仍进 supervisor 串行循环
    return SUPERVISOR


# ============================================================
# Specialist ReAct 节点包装（workflow 专属编排）
# ============================================================

def build_specialist_node(role: str, llm):
    """构建一个 specialist 节点：底层用 app/agents 的 ReAct agent，外层注入上下文 + 回写 filename。"""
    react = build_specialist(role, llm)

    async def node(state: AgentState, config: Optional[RunnableConfig] = None) -> dict:
        # task_id 复用 trace metadata 的 ppt_id（LangSmith 集成注入，独立于 tracing 开关）
        meta = (config.get("metadata") or {}) if config else {}
        task_id = meta.get("ppt_id")
        context_note = _build_context_note(state, role)
        # 注入 filename/style/outline 上下文，让 specialist 知道当前状态
        messages = list(state["messages"])
        messages.append(HumanMessage(content=context_note))
        on_stage = config.get("configurable", {}).get("on_stage") if config else None

        # 本地执行日志：包裹 specialist 执行，落 sys_agent_log（inline await 写库，
        # 非 create_task——ASGI streaming generator 里 detached task 会被拆除丢写）
        async with agent_log_context(
            task_id, role, context_note,
            {
                "style": state.get("style"),
                "has_outline": bool(state.get("outline")),
                "has_research": bool(state.get("research")),
                "filename": state.get("filename"),
                "user_message": (state.get("user_message") or "")[:200],
            },
        ) as log_data:
            # 透传 config 让 specialist 内部 LLM/工具调用继承 trace metadata（防御性；
            # LangGraph 已通过 contextvar 自动传播，此处加固并确保 on_stage 等配置可达）
            result = await react.ainvoke({"messages": messages}, config=config)
            new_msgs = result.get("messages", [])
            patch: dict = {"messages": new_msgs}

            # outline 完成规划 → 回写 outline 结构 JSON，供 research/content 消费
            if role == "outline" and not state.get("outline"):
                outline_json = _extract_outline(new_msgs)
                if outline_json:
                    patch["outline"] = outline_json
                    log_data["outputData"] = json.dumps(
                        {"outline_chars": len(outline_json)}, ensure_ascii=False
                    )
                    logger.info("[outline] 检测到大纲已生成（%d 字符）", len(outline_json))
                    if on_stage:
                        try:
                            await on_stage(role, outline_json)
                        except Exception as e:
                            logger.warning("[on_stage] outline 持久化失败: %s", e)

            # research 完成调研 → 回写 research 笔记 JSON，供 content 消费
            if role == "research" and not state.get("research"):
                research_json = _extract_research(new_msgs)
                if research_json:
                    patch["research"] = research_json
                    log_data["outputData"] = json.dumps(
                        {"research_chars": len(research_json)}, ensure_ascii=False
                    )
                    logger.info("[research] 检测到研究笔记已生成（%d 字符）", len(research_json))
                    if on_stage:
                        try:
                            await on_stage(role, research_json)
                        except Exception as e:
                            logger.warning("[on_stage] research 持久化失败: %s", e)

            # content 成功生成 PPT → 回写 filename 贯穿后续专家
            if role == "content" and not state.get("filename"):
                fn = _extract_filename(new_msgs)
                if fn:
                    patch["filename"] = fn
                    log_data["outputData"] = json.dumps(
                        {"filename": fn}, ensure_ascii=False
                    )
                    logger.info("[content] 检测到 PPT 已生成: %s", fn)
                    if on_stage:
                        try:
                            await on_stage(role, fn)
                        except Exception as e:
                            logger.warning("[on_stage] content 持久化失败: %s", e)

            # image/chart/beautify 及未命中上面的兜底摘要
            if not log_data.get("outputData"):
                log_data["outputData"] = json.dumps(
                    {
                        "role": role,
                        "executed": True,
                        "ai_tail": (_last_ai_text(new_msgs) or "")[:200],
                    },
                    ensure_ascii=False,
                )

            return patch

    return node

def _build_context_note(state: AgentState, role: str) -> str:
    """为 specialist 构造上下文提示（大纲 / 研究笔记 / 文件名 / 风格）。"""
    filename = state.get("filename")
    style = state.get("style") or "business"
    outline = state.get("outline")
    research = state.get("research")
    user_message = state.get("user_message", "")

    if role == "outline":
        return (
            f"[上下文] 主题风格：{style}。请规划幻灯片结构，"
            "直接输出大纲 JSON 数组（每项含 title/layout_hint/purpose），不要生成文件。"
        )
    if role == "research":
        if outline:
            return (
                f"[上下文] 主题风格：{style}。以下是大纲专家产出的结构 JSON，"
                f"请据此为各页主题检索最新事实/数据/案例，并输出研究笔记 JSON：\n{outline}"
            )
        return (
            f"[上下文] 主题风格：{style}。尚无大纲，请基于用户主题检索资料并输出研究笔记 JSON。"
            f"用户主题：{user_message}"
        )
    if role == "content":
        parts = [f"[上下文] 主题风格：{style}。"]
        if outline:
            parts.append(
                "以下是大纲专家产出的结构 JSON，请据此为每页填充要点与备注并生成 PPTX：\n"
                f"{outline}"
            )
        else:
            parts.append("未提供大纲，请自行规划结构并生成 PPT。")
        if research:
            parts.append(
                "以下是调研专家收集的研究笔记 JSON，填充要点时请参考其中的事实/数据/结论"
                "（不要在正文里展示 URL）：\n" + research
            )
        parts.append("filename 请自行取一个语义化名字。")
        return "\n".join(parts)
    if filename:
        return (
            f"[上下文] 当前要操作的 PPT 文件名是：{filename}"
            f"（所有工具调用都必须传这个 filename）。主题风格：{style}。"
        )
    return (
        f"[上下文] 注意：尚未获取到 PPT 文件名，请向协调员反馈需要先生成 PPT。"
        f"主题风格：{style}。"
    )


def _last_ai_text(messages) -> Optional[str]:
    """取最后一条非空 AIMessage 文本（outline/research 均以末条 AIMessage 输出 JSON）。"""
    for m in reversed(messages):
        if isinstance(m, AIMessage) and isinstance(m.content, str) and m.content.strip():
            return m.content.strip()
    return None


def _extract_outline(messages) -> Optional[str]:
    """取 outline 专家最后一条 AIMessage 文本作为大纲结构 JSON。"""
    return _last_ai_text(messages)


def _extract_research(messages) -> Optional[str]:
    """取 research 专家最后一条 AIMessage 文本作为研究笔记 JSON。"""
    return _last_ai_text(messages)


def _extract_filename(messages) -> Optional[str]:
    """从消息流中找到 generate_ppt 的成功返回，提取 file_path 的 basename。"""
    for m in reversed(messages):
        if not isinstance(m, ToolMessage):
            continue
        if getattr(m, "name", "") != "generate_ppt":
            continue
        content = m.content if isinstance(m.content, str) else str(m.content)
        try:
            data = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict) and data.get("success") and data.get("file_path"):
            return os.path.basename(data["file_path"])
    return None


# ============================================================
# 图构建
# ============================================================

def build_create_pipeline(llm):
    """构建 create 意图的确定性并行流水线子图。

    拓扑：START ─(无 outline)→ outline → research → content ─(有 filename)→ [image ‖ chart]
                                  └─(有 outline)→ research ↗                  └─(无 filename)→ END
          image → beautify，chart → beautify（fan-in barrier，beautify 等两路完成）→ END

    入口条件边 route_create_resume 按已注入阶段断点续跑：filename 在 → 并行 [image‖chart]；
    research 在 → content；outline 在 → research；都没有 → outline。同时兼容大纲人工审阅
    （HITL 第二段把编辑后大纲注入 state.outline，经此入口跳过 outline 节点）。节点全部复用
    build_specialist_node(role, llm)，经 config['configurable']['on_stage'] 实时回写进度；
    filename 在 content 写入后，经 route_after_content 在 fan-out 前已 reduce 进 state，
    image/chart 通过 _build_context_note 读取。
    """
    g = StateGraph(AgentState)
    for role in ("outline", "research", "content", "image", "chart", "beautify"):
        g.add_node(role, build_specialist_node(role, llm))

    g.add_conditional_edges(
        START, route_create_resume,
        {"outline": "outline", "research": "research", "content": "content",
         "image": "image", "chart": "chart"},
    )
    g.add_edge("outline", "research")
    g.add_edge("research", "content")
    g.add_conditional_edges(
        "content",
        route_after_content,
        {"image": "image", "chart": "chart", END: END},
    )
    # fan-in：image 与 chart 都指向 beautify，LangGraph 默认 join，beautify 等两者都完成
    g.add_edge("image", "beautify")
    g.add_edge("chart", "beautify")
    g.add_edge("beautify", END)
    compiled = g.compile()
    logger.info(
        "[create_pipeline] 并行子图构建完成: (outline)→research→content→[image‖chart]→beautify→END"
    )
    return compiled


# ============================================================
# create 并行流水线 —— Send API 版（与上方静态条件边版对照，未接入主图）
# ============================================================

def route_after_content_send(state: AgentState):
    """content 之后用 Send 动态 fan-out 到 image ‖ chart。

    与 route_after_content 的差异：返回 ``[Send(node, state), ...]`` 而非节点名 list。
    每个 Send 可携带**定制的输入 state**，且实例数/目标可在运行时动态决定（map-reduce）。
    本实现用最简形式（固定两路、传同一份 state），与静态版行为等价。
    """
    if not state.get("filename"):
        logger.warning("[create_pipeline_send] content 未生成 filename，跳过美化链")
        return END
    return [
        Send("image", dict(state)),
        Send("chart", dict(state)),
    ]


def build_create_pipeline_send(llm):
    """构建 create 并行流水线子图（Send 版）。

    拓扑与 build_create_pipeline 完全一致，仅 content 的 fan-out 用 Send 实现。
    **未接入主图**（build_graph 仍用静态版）；如需切换，把 build_graph 内的
    build_create_pipeline(llm) 换成 build_create_pipeline_send(llm) 即可。

    Send 真正不可替代的场景（静态 list 做不到）：
    - 定制精简输入：Send("image", {"filename":..., "messages":[仅系统提示]})，避免复制长历史。
    - map-reduce：按 outline 页数动态 fan-out [Send("render_slide", {...}) for p in pages]。
    fan-in 合并一致：并行分支写回 messages 靠 add_messages reducer。
    """
    g = StateGraph(AgentState)
    for role in ("outline", "research", "content", "image", "chart", "beautify"):
        g.add_node(role, build_specialist_node(role, llm))

    g.add_edge(START, "outline")
    g.add_edge("outline", "research")
    g.add_edge("research", "content")
    # Send 动态路由：不传 path_map（目标由 Send 在运行时决定）
    g.add_conditional_edges("content", route_after_content_send)
    g.add_edge("image", "beautify")
    g.add_edge("chart", "beautify")
    g.add_edge("beautify", END)
    compiled = g.compile()
    logger.info(
        "[create_pipeline_send] Send 版并行子图构建完成: content→[Send image ‖ Send chart]→beautify"
    )
    return compiled


def build_graph(llm=None, checkpointer=None):
    """构建并编译 workflow 多智能体图。

    Args:
        llm: 共享的 ChatOpenAI 实例（不传则新建）。router/supervisor/specialist 复用同一 LLM。
        checkpointer: LangGraph checkpointer（MemorySaver / AsyncRedisSaver）。
            开启大纲人工审阅时由 MultiAgent 注入，使子图 create_pipeline 内的 interrupt()
            能跨请求恢复；为 None（默认 / 开关关闭）时行为与单段流完全一致。
    """
    if llm is None:
        llm = build_llm()

    graph = StateGraph(AgentState)
    # 入口意图路由 + chat 直答
    graph.add_node(INTENT_ROUTER, build_intent_router_node(llm))
    graph.add_node(CHAT_REPLY, build_chat_reply_node(llm))
    # 原有 supervisor + specialists（enhance/analyze 路径）
    graph.add_node(SUPERVISOR, build_supervisor_node(llm))
    for role in ROLES:
        graph.add_node(role, build_specialist_node(role, llm))
    # create 意图并行子图 静态模式
    graph.add_node(CREATE_PIPELINE, build_create_pipeline(llm))
    # create 意图并行子图 动态模式
    # graph.add_node(CREATE_PIPELINE, build_create_pipeline_send(llm))

    # 入口 → intent_router
    graph.add_edge(START, INTENT_ROUTER)
    # intent_router → chat 直答短路 / create 并行子图 / supervisor 串行循环
    graph.add_conditional_edges(
        INTENT_ROUTER,
        route_after_intent,
        {CHAT_REPLY: CHAT_REPLY, CREATE_PIPELINE: CREATE_PIPELINE, SUPERVISOR: SUPERVISOR},
    )
    # chat_reply → END（不再回 supervisor）
    graph.add_edge(CHAT_REPLY, END)
    # create 子图执行完直接 END
    graph.add_edge(CREATE_PIPELINE, END)

    # supervisor → 条件路由 → specialist 或 END（保持不变）
    graph.add_conditional_edges(
        SUPERVISOR,
        route_after_supervisor,
        {**{role: role for role in ROLES}, END: END},
    )
    # 每个 specialist 执行完回到 supervisor（循环直至 FINISH）
    for role in ROLES:
        graph.add_edge(role, SUPERVISOR)

    compiled = graph.compile(checkpointer=checkpointer)
    logger.info(
        "workflow 图构建完成: intent_router → {chat→END | create→并行子图 | supervisor → %s} "
        "(checkpointer=%s)",
        ROLES, type(checkpointer).__name__ if checkpointer else "None",
    )
    return compiled


def build_outline_only_graph(llm, checkpointer=None):
    """构建仅 outline 的子图（HITL 第一段用）：START → outline → END。"""
    g = StateGraph(AgentState)
    g.add_node("outline", build_specialist_node("outline", llm))
    g.add_edge(START, "outline")
    g.add_edge("outline", END)
    compiled = g.compile(checkpointer=checkpointer)
    logger.info("[outline_only] 子图构建完成: START→outline→END")
    return compiled
