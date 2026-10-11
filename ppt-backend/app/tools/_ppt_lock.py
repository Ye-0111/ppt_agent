"""按 filename 维度的 asyncio.Lock —— 串行化 PPTX 覆盖写，避免并行 image/chart 后写丢页。

背景：add_image_slide / add_chart_slide 都是 ``Presentation(path) -> 改 -> prs.save(path)``
覆盖写。若两者并行直写同一 PPTX，后保存者会覆盖掉先保存者新增的页（last-write-wins）。

本模块提供按 filename 的互斥锁，**只串行化毫秒级的 pptx load->save 段**；调用方应把
耗时的网络下载 / matplotlib 渲染 / LLM 推理留在锁外，使其真正并行。

用法::

    async with ppt_file_lock(filename):
        prs = Presentation(str(file_path))
        _add_xxx_slide(prs, ...)
        prs.save(str(file_path))
"""

import asyncio
import logging

logger = logging.getLogger(__name__)

# filename -> Lock。PPTX 文件数有界，常驻进程字典无显著泄漏。
_LOCKS: dict[str, asyncio.Lock] = {}
# 保护 _LOCKS 字典本身的创建，避免并发首次创建同 filename 时产生两把锁。
_REG_LOCK = asyncio.Lock()


async def _get_lock(filename: str) -> asyncio.Lock:
    async with _REG_LOCK:
        lock = _LOCKS.get(filename)
        if lock is None:
            lock = asyncio.Lock()
            _LOCKS[filename] = lock
        return lock


class _PptFileLock:
    """async context manager：进入时取锁并 acquire，退出时 release。"""

    def __init__(self, filename: str) -> None:
        self._filename = filename
        self._lock: asyncio.Lock | None = None

    async def __aenter__(self) -> "_PptFileLock":
        self._lock = await _get_lock(self._filename)
        await self._lock.acquire()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._lock is not None:
            self._lock.release()


def ppt_file_lock(filename: str) -> _PptFileLock:
    """返回一个按 filename 互斥的 async context manager。"""
    return _PptFileLock(filename)
