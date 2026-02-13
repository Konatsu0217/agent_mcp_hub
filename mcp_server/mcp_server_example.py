import asyncio
import inspect
import json
import re
from typing import AsyncGenerator, Optional

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from tavily import TavilyClient

from mcp_server import MCPServer, Parameter


# ===================== 配置管理 =====================
class Settings:
    """简单的配置类，可以改成从文件/数据库加载"""

    def __init__(self):
        self.tavily_api_key = "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"
        self.jina_api_key = ""  # 可选，不填就不带 Authorization
        self.tavily_max_results = 5
        self.jina_max_length = 1500
        self.content_per_page = 1000


settings = Settings()

# ===================== 创建 MCP 实例 =====================
mcp = MCPServer(name="Web Search MCP Server")


# ===================== 辅助函数 =====================

def clean_text(text: str, max_length: int = 2000) -> str:
    """清理和截断文本"""
    if not text:
        return ""
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', text)
    if len(text) > max_length:
        text = text[:max_length] + "..."
    return text.strip()


def extract_main_content(html_text: str, max_length: int = 1500) -> str:
    """从 Jina 返回的文本中提取主要内容"""
    if not html_text:
        return ""

    lines = html_text.split('\n')
    content_lines = []
    skip_keywords = ['navigation', 'menu', 'footer', 'subscribe', 'cookie', 'privacy policy']

    for line in lines:
        line_lower = line.lower()
        if any(keyword in line_lower for keyword in skip_keywords):
            continue
        if line.strip():
            content_lines.append(line.strip())

    content = ' '.join(content_lines)
    return clean_text(content, max_length)


def format_sources(results: list) -> str:
    """格式化来源链接：[网站名称](链接地址)"""
    sources = []
    for r in results:
        title = r.get("title", "未知来源")
        url = r.get("url", "")
        if url:
            # 移除括号内的空格
            sources.append(f"[{title}]({url.strip()})")
    return "\n".join(sources)


# ===================== 核心工具函数 =====================

async def jina_crawler_internal(
        original_url: str,
        max_length: Optional[int] = None
) -> str:
    """
    内部 Jina 爬虫函数，返回网页内容文本
    """
    if max_length is None:
        max_length = settings.jina_max_length

    detail_url = "https://r.jina.ai/"
    url = f"{detail_url}{original_url}"

    try:
        headers = {}
        if settings.jina_api_key:
            headers['Authorization'] = f'Bearer {settings.jina_api_key}'

        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(url, headers=headers)

            if response.status_code == 200:
                content = extract_main_content(response.text, max_length)
                return content
            else:
                return f"获取{original_url}网页信息失败，状态码：{response.status_code}"

    except Exception as e:
        return f"获取{original_url}网页信息失败，错误信息：{str(e)}"


async def tavily_search_internal(
        query: str,
        max_results: Optional[int] = None
) -> dict:
    """
    内部 Tavily 搜索函数，返回结构化数据
    """
    if max_results is None:
        max_results = settings.tavily_max_results

    try:
        def sync_search():
            client = TavilyClient(api_key=settings.tavily_api_key)
            return client.search(
                query=query,
                max_results=max_results,
                include_answer=True,
                include_raw_content=False
            )

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, sync_search)
        return response

    except Exception as e:
        print(f"Tavily search error: {e}")
        return {"results": [], "answer": ""}


# ===================== MCP 工具定义 =====================
'''
1. 创建MCPServer实例
2. 用 @mcp.tool 声明可以被发现的工具
3. 创建FastAPI应用实例，配置URL，记得填到外面那个 [mcp_servers_config.json] 当中
4. 运行你写好的mcpServer服务，[/mcp]接口方法可以直接copy，不用管
'''

@mcp.tool(name="echo", description="回显消息")
def echo(message: str) -> str:
    return message

@mcp.tool(
    name="get_weather",
    description="查询天气",
    parameters=[
        Parameter("city", "string", "要查询天气的城市"),
        Parameter("date", "string", "要查询的日期"),
    ]
)
def get_weather(city: str, date: str) -> str:
    if city == "北京":
        return f"北京在 {date} 是晴天"
    elif city == "上海":
        return f"上海在 {date} 是多云"
    elif city == "广州":
        return f"广州在 {date} 是阴云"
    else:
        return f"天气信息: {city} 在 {date}"


@mcp.tool(
    name="tavily_search",
    description="通过Tavily专业搜索API获取高质量的网络信息，特别适合获取实时数据和专业分析。返回结果包含搜索答案和来源链接。",
    parameters=[
        Parameter("query", "string", "需要搜索的关键词或自然语言查询语句"),
        Parameter("max_results", "integer", "最大搜索结果数，默认使用配置值", required=False),
    ]
)
async def tavily_search(
        query: str,
        max_results: Optional[int] = None
):
    """
    Tavily 搜索工具：返回结构化的搜索结果
    """
    search_result = await tavily_search_internal(query, max_results)
    results = search_result.get("results", [])
    answer = search_result.get("answer", "")

    res = clean_text(answer, 500)
    res += "\n 信息来源："
    for r in results:
        res += f" [{r.get('snippet', '')}]({r.get('url', '')})"

    return res


@mcp.tool(
    name="jina_crawler",
    description="通过Jina AI的网页爬取API获取指定URL的网页内容。可以爬取搜索引擎返回的链接，或用户提供的网站链接。注意：不要传入本机地址(localhost/127.0.0.1)或内网地址，Jina无法访问这些URL。",
    parameters=[
        Parameter("original_url", "string", "需要爬取的原始URL地址（完整的http/https链接）"),
        Parameter("max_length", "integer", "返回内容的最大字符数，默认使用配置值", required=False),
    ]
)
async def jina_crawler(
        original_url: str,
        max_length: Optional[int] = None
):
    """
    Jina 爬虫工具：抓取单个网页内容
    """
    # 检查是否是本地/内网地址
    if any(pattern in original_url.lower() for pattern in ['localhost', '127.0.0.1', '192.168.', '10.', '172.16.']):
        return {
            "url": original_url,
            "success": False,
            "error": "不支持爬取本机或内网地址",
            "content": None
        }

    content = await jina_crawler_internal(original_url, max_length)

    # 判断是否成功
    if content.startswith("获取") and "失败" in content:
        return {
            "url": original_url,
            "success": False,
            "error": content,
            "content": None
        }
    else:
        return {
            "url": original_url,
            "success": True,
            "content": content,
            "length": len(content)
        }


# @mcp.tool(
#     name="deep_search",
#     description="深度搜索工具：先通过Tavily搜索，再自动使用Jina爬取前N个结果的完整网页内容。适合需要详细信息的查询。返回时会在底部提供信息来源链接。",
#     parameters=[
#         Parameter("query", "string", "需要搜索的关键词或自然语言查询语句"),
#         Parameter("max_results", "integer", "搜索并爬取的结果数量，默认2个", required=False),
#         Parameter("content_per_page", "integer", "每个网页返回的最大字符数，默认使用配置值", required=False),
#     ]
# )
async def deep_search(
        query: str,
        max_results: int = 2,
        content_per_page: Optional[int] = None
):
    """
    组合工具：Tavily 搜索 + Jina 批量爬取
    """
    if content_per_page is None:
        content_per_page = settings.content_per_page

    # 第一步：Tavily 搜索
    search_result = await tavily_search_internal(query, max_results)

    results = search_result.get("results", [])
    answer = search_result.get("answer", "")

    # 第二步：Jina 爬取网页内容
    enriched_results = []
    for result in results[:max_results]:
        url = result.get("url")
        if not url:
            continue

        # 跳过本地/内网地址
        if any(pattern in url.lower() for pattern in ['localhost', '127.0.0.1', '192.168.', '10.', '172.16.']):
            continue

        content = await jina_crawler_internal(url, content_per_page)

        item = {
            "title": clean_text(result.get("title", ""), 100),
            "url": url,
            "snippet": clean_text(result.get("content", ""), 200),
            "score": round(result.get("score", 0), 2)
        }

        # 判断是否成功爬取
        if content.startswith("获取") and "失败" in content:
            item["full_content"] = None
            item["fetch_error"] = content
        else:
            item["full_content"] = content
            item["content_length"] = len(content)

        enriched_results.append(item)

    # 格式化来源链接
    sources_text = format_sources(results)

    return {
        "query": query,
        "answer": clean_text(answer, 500),
        "results": enriched_results,
        "sources_markdown": sources_text,
        "result_count": len(enriched_results)
    }


# ===================== 流式工具定义 =====================

# @mcp.tool(
#     name="tavily_search_stream",
#     description="流式Tavily搜索，实时返回搜索进度和结果。",
#     parameters=[
#         Parameter("query", "string", "需要搜索的关键词或自然语言查询语句"),
#         Parameter("max_results", "integer", "最大搜索结果数", required=False),
#     ]
# )
async def tavily_search_stream(
        query: str,
        max_results: Optional[int] = None
) -> AsyncGenerator[dict, None]:
    """流式搜索：逐步返回搜索状态和结果"""

    yield {
        "type": "status",
        "message": f"正在搜索: {query}",
        "progress": 0
    }

    await asyncio.sleep(0.1)

    try:
        search_result = await tavily_search_internal(query, max_results)
        results = search_result.get("results", [])
        answer = search_result.get("answer", "")

        yield {
            "type": "status",
            "message": f"找到 {len(results)} 个结果",
            "progress": 50
        }

        await asyncio.sleep(0.1)

        sources_text = format_sources(results)

        yield {
            "type": "result",
            "data": {
                "query": query,
                "answer": clean_text(answer, 500),
                "sources": [
                    {
                        "title": clean_text(r.get("title", ""), 100),
                        "url": r.get("url", ""),
                        "snippet": clean_text(r.get("content", ""), 200),
                        "score": round(r.get("score", 0), 2)
                    }
                    for r in results
                ],
                "sources_markdown": sources_text,
                "result_count": len(results)
            },
            "progress": 100
        }

    except Exception as e:
        yield {
            "type": "error",
            "message": f"搜索失败: {str(e)}",
            "progress": 100
        }


# @mcp.tool(
#     name="deep_search_stream",
#     description="流式深度搜索，实时返回搜索和爬取进度。先搜索，再逐个爬取网页内容。",
#     parameters=[
#         Parameter("query", "string", "需要搜索的关键词或自然语言查询语句"),
#         Parameter("max_results", "integer", "搜索并爬取的结果数量，默认2个", required=False),
#         Parameter("content_per_page", "integer", "每个网页返回的最大字符数", required=False),
#     ]
# )
async def deep_search_stream(
        query: str,
        max_results: int = 2,
        content_per_page: Optional[int] = None
) -> AsyncGenerator[dict, None]:
    """流式深度搜索：Tavily + Jina 流式返回"""

    if content_per_page is None:
        content_per_page = settings.content_per_page

    yield {
        "type": "status",
        "message": f"正在搜索: {query}",
        "stage": "searching",
        "progress": 0
    }

    await asyncio.sleep(0.1)

    try:
        # 搜索
        search_result = await tavily_search_internal(query, max_results)
        results = search_result.get("results", [])
        answer = search_result.get("answer", "")

        yield {
            "type": "status",
            "message": f"找到 {len(results)} 个结果，开始爬取网页内容...",
            "stage": "search_complete",
            "progress": 30
        }

        await asyncio.sleep(0.1)

        # 逐个爬取
        enriched_results = []
        valid_results = [r for r in results[:max_results] if r.get("url")]

        for i, result in enumerate(valid_results):
            url = result.get("url")

            # 跳过本地地址
            if any(pattern in url.lower() for pattern in ['localhost', '127.0.0.1', '192.168.']):
                continue

            yield {
                "type": "status",
                "message": f"正在爬取第 {i + 1}/{len(valid_results)} 个网页: {result.get('title', '')[:30]}...",
                "stage": "fetching",
                "progress": 30 + (i + 1) * (60 // len(valid_results))
            }

            content = await jina_crawler_internal(url, content_per_page)

            item = {
                "title": clean_text(result.get("title", ""), 100),
                "url": url,
                "snippet": clean_text(result.get("content", ""), 200),
                "score": round(result.get("score", 0), 2)
            }

            if content.startswith("获取") and "失败" in content:
                item["full_content"] = None
                item["fetch_error"] = content
            else:
                item["full_content"] = content
                item["content_length"] = len(content)

            enriched_results.append(item)

            yield {
                "type": "partial_result",
                "message": f"已完成第 {i + 1} 个网页",
                "data": item,
                "progress": 30 + (i + 1) * (60 // len(valid_results))
            }

            await asyncio.sleep(0.1)

        # 最终结果
        sources_text = format_sources(results)

        yield {
            "type": "result",
            "data": {
                "query": query,
                "answer": clean_text(answer, 500),
                "results": enriched_results,
                "sources_markdown": sources_text,
                "result_count": len(enriched_results)
            },
            "progress": 100
        }

    except Exception as e:
        yield {
            "type": "error",
            "message": f"深度搜索失败: {str(e)}",
            "progress": 100
        }


# ===================== FastAPI 应用 =====================
app = FastAPI(title=mcp.name, version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)


@app.post("/mcp")
async def streamable_http_mcp(req: Request):
    payload = await req.json()
    method = payload.get("method")
    params = payload.get("params", {})

    try:
        if method == "initialize":
            result = mcp.initialize(
                client_info=params.get("clientInfo", {}),
                capabilities=params.get("capabilities", {})
            )
            return result

        elif method == "tools/call":
            tool_name = params["name"]
            arguments = params.get("arguments", {})
            func = mcp.tools.get(tool_name)
            if func is None:
                raise ValueError(f"Tool '{tool_name}' not found")

            async def stream_tool():
                if inspect.isasyncgenfunction(func):
                    async for chunk in func(**arguments):
                        yield json.dumps(chunk, ensure_ascii=False) + "\n"
                elif inspect.iscoroutinefunction(func):
                    result = await func(**arguments)
                    yield json.dumps({"type": "result", "data": result}, ensure_ascii=False) + "\n"
                else:
                    result = func(**arguments)
                    yield json.dumps({"type": "result", "data": result}, ensure_ascii=False) + "\n"

            return StreamingResponse(stream_tool(), media_type="application/json")

        elif method in ("tools/list", "tools/roots"):
            return mcp.tools_list()

        else:
            raise ValueError(f"Method '{method}' not found")

    except Exception as e:
        return {"error": str(e), "error_type": type(e).__name__}


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "tools_registered": len(mcp.tools),
        "tools": list(mcp.tools.keys())
    }


@app.get("/settings")
async def get_settings():
    """获取当前配置"""
    return {
        "tavily_max_results": settings.tavily_max_results,
        "jina_max_length": settings.jina_max_length,
        "content_per_page": settings.content_per_page,
        "jina_api_key_configured": bool(settings.jina_api_key)
    }


# ===================== 启动服务器 =====================
if __name__ == "__main__":
    import uvicorn

    print(f"🚀 {mcp.name} 启动中...")
    print(f"📋 已注册 {len(mcp.tools)} 个工具:")
    for tool_name in mcp.tools.keys():
        print(f"   - {tool_name}")
    print(f"⚙️  配置: Tavily最大结果={settings.tavily_max_results}, Jina最大长度={settings.jina_max_length}")
    uvicorn.run(app, host="0.0.0.0", port=8000)
