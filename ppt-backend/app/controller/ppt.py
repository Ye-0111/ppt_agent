"""PPT 创作接口"""

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, StreamingResponse
from databases import Database

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.exceptions import BusinessException, ErrorCode
from app.core.observability import build_trace_metadata
from app.core.sse import sse_event, SSE_HEADERS
from app.schemas.common import BaseResponse
from app.schemas.user import LoginUserVO
from app.schemas.ppt import (
    PptCreateRequest,
    PptOutlineResumeRequest,
    PptListRequest,
    PptResumeRequest,
)
from app.services.agent_log_service import AgentLogService
from app.services.ppt_service import PptService, ROLE_TO_FIELD, ROLE_TO_STAGE
from app.agent import default_stream_agent
from app.agents.workflow.outline_normalize import normalize_outline

router = APIRouter(prefix="/ppt", tags=["PPT创作"])
logger = logging.getLogger(__name__)

PPTX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.presentationml.presentation"
)


def _make_on_stage(service: PptService, ppt_id: int, tag: str):
    """构造 on_stage 回调：specialist 节点产出实时落库（outline/research/filename + stage）。

    落库失败仅记日志，不中断流水线（终态以 mark_success/mark_failed 为准）。
    """

    async def on_stage(role: str, value: str):
        field = ROLE_TO_FIELD.get(role)
        stage = ROLE_TO_STAGE.get(role)
        if not (field and stage):
            return
        try:
            await service.update_progress(ppt_id, **{field: value, "stage": stage})
        except Exception as e:
            logger.warning("[%s] on_stage 落库失败 role=%s: %s", tag, role, e)

    return on_stage


def _make_on_ppt_created(service: PptService, ppt_id: int, user_id: int, state: dict):
    """构造 on_ppt_created 回调：content 成功后扣配额（deduct_for_task 带 stage 乐观锁防并发双扣）。"""

    async def on_ppt_created(filename: str):
        if state["deducted"]:
            return
        _ok, remaining = await service.deduct_for_task(ppt_id, user_id, filename)
        state["deducted"] = True
        state["remaining_quota"] = remaining
        state["filename"] = filename

    return on_ppt_created


async def _mark_terminal(service: PptService, ppt_id: int, state: dict, tag: str):
    """流结束后按是否生成文件标记终态。失败仅记日志。"""
    try:
        if state["filename"]:
            await service.mark_success(ppt_id)
        else:
            await service.mark_failed(ppt_id, "未生成文件")
    except Exception as e:
        logger.error("[%s] 标记终态失败: %s", tag, e)


async def _mark_failed_safe(service: PptService, ppt_id: int, err: str):
    try:
        await service.mark_failed(ppt_id, err)
    except Exception:
        pass


@router.post("/create")
async def create_ppt(
    req: PptCreateRequest,
    user: LoginUserVO = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """创建 PPT（流式 SSE，需登录，扣配额，全生命周期落库支持断点恢复）。

    配额门控在 SSE 流开启前同步执行：不足直接抛 BusinessException。
    流程开始即创建任务（status=IN_PROGRESS），每个 specialist 阶段产出实时落库；
    generate_ppt 成功后扣配额；流结束标记 SUCCESS/FAILED。中途断流后任务保留中间态，
    可经 /ppt/resume 续跑。
    """
    service = PptService(db)

    # 1. 配额门控（必须在 StreamingResponse 之前）
    await service.check_quota(user.id)

    style = req.style or "business"
    session_id = req.session_id or f"u{user.id}"

    # HITL 第一段：大纲人工审阅开启时，单独跑 outline specialist 生成大纲，不扣配额。
    # 前端拿到 OUTLINE_REVIEW{outline, thread_id, pptId} 后编辑，再 POST /ppt/create/resume 续跑。
    if settings.outline_review_enabled:
        ppt_id = await service.create_task(user.id, req.message[:500], style, session_id)
        on_stage = _make_on_stage(service, ppt_id, "PPT创建/大纲审阅")

        async def review_generator():
            try:
                async for event in default_stream_agent.run_outline_stream(
                    user_message=req.message, session_id=session_id, style=style,
                    on_stage=on_stage,
                    trace_meta=build_trace_metadata(user_id=user.id, ppt_id=ppt_id),
                ):
                    if event["event"] == "DONE":
                        event["data"]["pptId"] = ppt_id
                    yield sse_event(event["event"], event["data"])
            except Exception as e:
                logger.error("[PPT创建/大纲审阅] 未捕获异常: %s", e)
                await _mark_failed_safe(service, ppt_id, str(e))
                yield sse_event("ERROR", {"message": f"服务器异常: {e}"})

        return StreamingResponse(
            review_generator(),
            media_type="text/event-stream",
            headers=SSE_HEADERS,
        )

    # 2. 建任务（断点恢复：全生命周期落库）
    topic = req.message[:500]
    ppt_id = await service.create_task(user.id, topic, style, session_id)
    state = {"remaining_quota": None, "deducted": False, "filename": None}
    on_stage = _make_on_stage(service, ppt_id, "PPT创建")
    on_ppt_created = _make_on_ppt_created(service, ppt_id, user.id, state)

    # 3. 流式生成
    async def event_generator():
        try:
            async for event in default_stream_agent.run_ppt_stream(
                user_message=req.message,
                session_id=session_id,
                on_ppt_created=on_ppt_created,
                style=style,
                on_stage=on_stage,
                trace_meta=build_trace_metadata(user_id=user.id, ppt_id=ppt_id),
            ):
                if event["event"] == "DONE":
                    event["data"]["pptId"] = ppt_id
                    if state["remaining_quota"] is not None:
                        event["data"]["remaining_quota"] = state["remaining_quota"]
                    if state["filename"]:
                        event["data"]["filename"] = state["filename"]
                yield sse_event(event["event"], event["data"])
            await _mark_terminal(service, ppt_id, state, "PPT创建")
        except Exception as e:
            logger.error("[PPT创建] 未捕获异常: %s", e)
            await _mark_failed_safe(service, ppt_id, str(e))
            yield sse_event("ERROR", {"message": f"服务器异常: {e}"})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.post("/list", response_model=BaseResponse)
async def list_my_ppt(
    req: PptListRequest,
    user: LoginUserVO = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """我的 PPT 任务列表（分页，按用户隔离，支持 status 过滤）。

    含进行中（IN_PROGRESS，可续跑）、成功（SUCCESS，可下载）、失败（FAILED）三类。
    """
    service = PptService(db)
    result = await service.list_by_user(user.id, req.current, req.page_size, req.status)
    return BaseResponse.success(data=result)


@router.get("/detail/{ppt_id}", response_model=BaseResponse)
async def ppt_detail(
    ppt_id: int,
    user: LoginUserVO = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """任务详情（含 outline/research，供前端展示/编辑后调 /ppt/resume 续跑）。"""
    service = PptService(db)
    task = await service.get_task(ppt_id, user.id)
    if not task:
        raise BusinessException(ErrorCode.NOT_FOUND_ERROR, "任务不存在或无权访问")
    return BaseResponse.success(data=task)


@router.get("/agent-log/{ppt_id}", response_model=BaseResponse)
async def get_agent_log(
    ppt_id: int,
    user: LoginUserVO = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """PPT 任务执行日志（各 specialist 耗时/状态/输入输出摘要）。

    登录 + 归属校验（参照 /ppt/detail）。返回 AgentExecutionStatsVO：
    总耗时、各 specialist 耗时、整体状态、日志列表。与 LangSmith 互补——
    结构化落库、SQL 可查、不占云端配额、可面向用户展示。
    """
    service = PptService(db)
    task = await service.get_task(ppt_id, user.id)
    if not task:
        raise BusinessException(ErrorCode.NOT_FOUND_ERROR, "任务不存在或无权访问")
    stats = await AgentLogService(db).get_execution_stats(str(ppt_id))
    return BaseResponse.success(data=stats)


@router.post("/resume")
async def resume_ppt_task(
    req: PptResumeRequest,
    user: LoginUserVO = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """断点续跑：按 pptId 加载已落库的 outline/research/filename，注入 create_pipeline 续跑剩余阶段。

    仅 IN_PROGRESS 任务可续跑；归属越权由 get_task 的 userId 校验拦截。
    配额仅在续跑需要重新生成文件（content 阶段）时扣减；filename 已在则 route_create_resume
    跳过 content，generate_ppt 不再执行，不会重复扣。
    """
    service = PptService(db)
    task = await service.get_task(req.ppt_id, user.id)
    if not task:
        raise BusinessException(ErrorCode.NOT_FOUND_ERROR, "任务不存在或无权访问")
    if task["status"] != "IN_PROGRESS":
        raise BusinessException(
            ErrorCode.OPERATION_ERROR, f"任务状态为 {task['status']}，不可续跑"
        )

    resume_patch = {k: task[k] for k in ("outline", "research", "filename") if task.get(k)}
    if not resume_patch:
        raise BusinessException(ErrorCode.OPERATION_ERROR, "无可续跑的进度，请重新创建")

    # 仅在续跑需重生文件时才真扣（deduct_for_task）；filename 已在则不会扣
    await service.check_quota(user.id)

    ppt_id = task["id"]
    topic = (req.message or task["topic"] or "")[:500]
    style = task["style"] or "business"
    session_id = task["sessionId"] or f"u{user.id}"
    state = {"remaining_quota": None, "deducted": False, "filename": task.get("filename")}
    on_stage = _make_on_stage(service, ppt_id, "PPT续跑")
    on_ppt_created = _make_on_ppt_created(service, ppt_id, user.id, state)

    async def resume_generator():
        try:
            async for event in default_stream_agent.run_resume_stream(
                user_message=topic,
                session_id=session_id,
                resume_patch=resume_patch,
                on_ppt_created=on_ppt_created,
                on_stage=on_stage,
                style=style,
                trace_meta=build_trace_metadata(user_id=user.id, ppt_id=ppt_id),
            ):
                if event["event"] == "DONE":
                    event["data"]["pptId"] = ppt_id
                    if state["filename"]:
                        event["data"]["filename"] = state["filename"]
                    if state["remaining_quota"] is not None:
                        event["data"]["remaining_quota"] = state["remaining_quota"]
                yield sse_event(event["event"], event["data"])
            await _mark_terminal(service, ppt_id, state, "PPT续跑")
        except Exception as e:
            logger.error("[PPT续跑] 未捕获异常: %s", e)
            await _mark_failed_safe(service, ppt_id, str(e))
            yield sse_event("ERROR", {"message": f"服务器异常: {e}"})

    return StreamingResponse(
        resume_generator(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.post("/create/resume")
async def resume_ppt(
    req: PptOutlineResumeRequest,
    user: LoginUserVO = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """大纲审阅后续跑（第二段 SSE，扣配额）。

    应用层方案：接收前端编辑后的大纲，经 normalize_outline 规范化后注入 state.outline，
    跑 create_pipeline（入口条件边 route_create_resume 跳过 outline 节点）
    → research→content→[image‖chart]→beautify。传 pptId 则复用第一段任务，否则新建。
    """
    service = PptService(db)
    await service.check_quota(user.id)

    # 规范化编辑后的大纲；非法/空则拒绝（不进第二段）
    edited = normalize_outline(req.outline)
    if not edited:
        raise BusinessException(ErrorCode.PARAMS_ERROR, "大纲内容非法或为空")

    topic = req.message[:500]
    style = req.style or "business"
    session_id = f"u{user.id}"

    # 复用第一段创建的任务（pptId），否则新建（向后兼容）
    ppt_id = req.ppt_id if req.ppt_id else await service.create_task(user.id, topic, style, session_id)
    # 把规范化后的大纲落库（覆盖第一段草稿大纲），推进到 OUTLINE_DONE
    try:
        await service.update_progress(ppt_id, outline=edited, stage=ROLE_TO_STAGE["outline"])
    except Exception as e:
        logger.warning("[PPT大纲续跑] outline 落库失败: %s", e)

    state = {"remaining_quota": None, "deducted": False, "filename": None}
    on_stage = _make_on_stage(service, ppt_id, "PPT大纲续跑")
    on_ppt_created = _make_on_ppt_created(service, ppt_id, user.id, state)

    async def resume_generator():
        try:
            async for event in default_stream_agent.run_create_stream(
                user_message=req.message,
                session_id=session_id,
                outline=edited,
                on_ppt_created=on_ppt_created,
                style=style,
                on_stage=on_stage,
                trace_meta=build_trace_metadata(user_id=user.id, ppt_id=ppt_id),
            ):
                if event["event"] == "DONE":
                    event["data"]["pptId"] = ppt_id
                    if state["remaining_quota"] is not None:
                        event["data"]["remaining_quota"] = state["remaining_quota"]
                    if state["filename"]:
                        event["data"]["filename"] = state["filename"]
                yield sse_event(event["event"], event["data"])
            await _mark_terminal(service, ppt_id, state, "PPT大纲续跑")
        except Exception as e:
            logger.error("[PPT大纲续跑] 未捕获异常: %s", e)
            await _mark_failed_safe(service, ppt_id, str(e))
            yield sse_event("ERROR", {"message": f"服务器异常: {e}"})

    return StreamingResponse(
        resume_generator(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.get("/download/{filename}")
async def download_ppt(
    filename: str,
    user: LoginUserVO = Depends(get_current_user),
):
    """下载已生成的 PPTX（从 workspace/ppt_output/ 取，登录鉴权）。"""
    out_dir = (settings.workspace_path / "ppt_output").resolve()
    safe = (out_dir / filename).resolve()
    try:
        safe.relative_to(out_dir)
    except ValueError:
        raise BusinessException(ErrorCode.PARAMS_ERROR, "非法文件名")
    if not safe.is_file():
        raise BusinessException(ErrorCode.NOT_FOUND_ERROR, "文件不存在或已被清理")

    return FileResponse(
        path=str(safe),
        media_type=PPTX_MEDIA_TYPE,
        filename=filename,  # 触发 Content-Disposition: attachment
    )
