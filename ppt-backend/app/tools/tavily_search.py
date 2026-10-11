"""Tavily 联网搜索工具 - 供 research 专家调用，为 PPT 内容提供事实依据。

最简实现，两个 async @tool：
- web_search(query)：Tavily 搜索，返回 [{title,url,content}, ...]
- fetch_page(url) ：抓取并清洗单个网页正文

约定：
- 未配置 TAVILY_API_KEY 时**降级返回空/提示**，绝不抛异常（仿 pexels_search.py），
  保证多智能体图在无 key 时仍能走通（outline → content）。
- 全程 try/except，工具永不抛异常（否则中断 ReAct 循环）。
- 参数名不用 `config`（与 LangChain RunnableConfig 冲突）。
- 关键调用点用 logger.info 打印，便于观测检索流程。
"""

import json
import logging
import re

import httpx
from langchain_core.tools import tool

from app.core.config import settings

logger = logging.getLogger(__name__)

# Tavily API Key（与 pexels_api_key 同款，从 .env 经 Settings 读入；缺省降级跳过）
TAVILY_API_KEY = settings.tavily_api_key

MAX_RESULTS = 5               # 每次 search 返回条数
SNIPPET_MAX_CHARS = 500       # 单条摘要截断
FETCH_MAX_CHARS = 4000        # 单页正文截断


def _client():
    """构造一个 AsyncTavilyClient（轻量，按调用创建；延迟导入）。"""
    from tavily import AsyncTavilyClient
    return AsyncTavilyClient(api_key=TAVILY_API_KEY)


@tool
async def web_search(query: str) -> str:
    """联网搜索，返回与查询相关的网页结果列表（标题/URL/摘要）。

    用于为 PPT 主题检索最新事实、数据、案例。返回 JSON 字符串：
      {"success": true, "query": "...", "results": [{"title","url","content"}, ...]}
    未配置 API key 或出错时返回 success=false、results=[]，绝不抛异常。

    Args:
        query: 搜索关键词（自然语言或短语，英文对国际主题效果更好）。
    """
    logger.info("[tavily/web_search] 调用: query=%s", query[:80])
    if not TAVILY_API_KEY:
        logger.info("[tavily/web_search] 未配置 TAVILY_API_KEY，跳过: query=%s", query[:80])
        return json.dumps(
            {"success": False, "query": query, "results": [], "message": "未配置 TAVILY_API_KEY，跳过联网搜索"},
            ensure_ascii=False,
        )
    try:
        resp = await _client().search(query, max_results=MAX_RESULTS, include_raw_content=False)
        results = []
        for item in (resp or {}).get("results", []) or []:
            content = (item.get("content") or "").strip()
            if len(content) > SNIPPET_MAX_CHARS:
                content = content[:SNIPPET_MAX_CHARS] + "…"
            results.append(
                {"title": item.get("title", ""), "url": item.get("url", ""), "content": content}
            )
        logger.info(
            "[tavily/web_search] 完成: query=%s → %d 条: %s",
            query[:60], len(results), [r["url"] for r in results],
        )
        return json.dumps({"success": True, "query": query, "results": results}, ensure_ascii=False)
    except Exception as e:
        logger.error("[tavily/web_search] 失败: %s | query=%s", e, query[:60])
        return json.dumps(
            {"success": False, "query": query, "results": [], "message": f"搜索失败: {e}"},
            ensure_ascii=False,
        )


@tool
async def fetch_page(url: str) -> str:
    """抓取单个网页的正文内容（已清洗、去标签、截断）。

    当 web_search 发现某条结果价值很高、需要更多细节时调用。返回 JSON 字符串：
      {"success": true, "url": "...", "content": "...正文..."}
    失败或无 key 时 success=false、content=""，绝不抛异常。

    Args:
        url: 要抓取的网页地址（必须是完整 http(s) URL）。
    """
    logger.info("[tavily/fetch_page] 调用: url=%s", url[:100])
    if not url or not str(url).lower().startswith(("http://", "https://")):
        logger.info("[tavily/fetch_page] 无效 URL，跳过: url=%s", url[:80])
        return json.dumps(
            {"success": False, "url": url, "content": "", "message": "无效的 URL"},
            ensure_ascii=False,
        )

    # 有 key 用 Tavily extract（清洗更好）；否则/失败回退 httpx 粗抓
    if TAVILY_API_KEY:
        try:
            resp = await _client().extract([url])
            contents = (resp or {}).get("results", []) or []
            text = ""
            if contents:
                text = (contents[0].get("raw_content") or contents[0].get("content") or "").strip()
            if text:
                if len(text) > FETCH_MAX_CHARS:
                    text = text[:FETCH_MAX_CHARS] + "…"
                logger.info("[tavily/fetch_page] 完成: url=%s → %d 字 (via tavily extract)", url[:80], len(text))
                return json.dumps({"success": True, "url": url, "content": text}, ensure_ascii=False)
        except Exception as e:
            logger.warning("[tavily/fetch_page] extract 失败，回退 httpx: %s | %s", e, url[:80])

    # httpx 兜底：去 script/style → 剥标签 → 压空白
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            r = await client.get(url, headers={"User-Agent": "Mozilla/5.0 PPTCreatorBot"})
            if r.status_code != 200:
                logger.info("[tavily/fetch_page] 非 200: %d | %s", r.status_code, url[:80])
                return json.dumps(
                    {"success": False, "url": url, "content": "", "message": f"HTTP {r.status_code}"},
                    ensure_ascii=False,
                )
            text = r.text
    except Exception as e:
        logger.warning("[tavily/fetch_page] httpx 抓取失败: %s | %s", e, url[:80])
        return json.dumps(
            {"success": False, "url": url, "content": "", "message": f"抓取失败: {e}"},
            ensure_ascii=False,
        )

    text = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > FETCH_MAX_CHARS:
        text = text[:FETCH_MAX_CHARS] + "…"
    logger.info("[tavily/fetch_page] 完成: url=%s → %d 字 (via httpx)", url[:80], len(text))
    return json.dumps({"success": True, "url": url, "content": text}, ensure_ascii=False)
