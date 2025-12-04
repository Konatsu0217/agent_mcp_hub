import asyncio
import inspect
import json

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from mcp_server import MCPServer, Parameter

# ===================== 创建 MCP 实例 =====================
mcp = MCPServer(name="Example MCP Server")

@mcp.tool(name="echo", description="回显消息")
def echo(message: str) -> str:
    return message

@mcp.tool(name="add", description="加法运算")
def add(a: float, b: float) -> float:
    return a + b

@mcp.tool(name="count_stream", description="计数流")
async def count_stream(n: int):
    for i in range(1, n + 1):
        await asyncio.sleep(1)
        yield {"count": i}


@mcp.tool(
    name="search_files",
    description="在目录中搜索文件",
    parameters=[
        Parameter("directory", "string", "搜索的目录路径"),
        Parameter("pattern", "string", "文件名匹配模式 (支持通配符)"),
        Parameter("recursive", "boolean", "是否递归搜索子目录", required=False),
        Parameter("max_results", "integer", "最大返回结果数", required=False)
    ]
)
def search_files(directory: str, pattern: str, recursive: bool = False, max_results: int = 100):
    return {"success": True, "result": f"Searching {directory} for {pattern}"}

# ===================== FastAPI 应用 =====================
app = FastAPI(title=mcp.name, version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.post("/mcp")
async def streamable_http_mcp(req: Request):
    payload = await req.json()
    method = payload.get("method")
    params = payload.get("params", {})

    try:
        if method == "initialize":
            result = mcp.initialize(client_info=params.get("clientInfo", {}),
                                    capabilities=params.get("capabilities", {}))
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
                        yield json.dumps({"type": "tool_chunk", "chunk": chunk}, ensure_ascii=False) + "\n"
                else:
                    result = func(**arguments)
                    yield json.dumps({"type": "tool_result", "result": result}, ensure_ascii=False) + "\n"

            return StreamingResponse(stream_tool(), media_type="application/json")

        elif method in ("tools/list", "tools/roots"):
            return mcp.tools_list()

        else:
            raise ValueError(f"Method '{method}' not found")

    except Exception as e:
        return {"error": str(e), "error_type": type(e).__name__}

@app.get("/health")
async def health():
    return {"status": "healthy", "tools_registered": len(mcp.tools)}

# ===================== 启动服务器 =====================
if __name__ == "__main__":
    import uvicorn
    print(f"🚀 {mcp.name} 启动中, Streamable HTTP MCP 协议启用...")
    uvicorn.run(app, host="0.0.0.0", port=8000)
