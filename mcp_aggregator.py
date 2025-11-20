"""
MCP 聚合管理器 - 完全兼容 Streamable MCP

特性:
1. 多 MCP 服务器聚合
2. 自动发现工具
3. 路由工具调用
4. 支持 Streamable MCP 流式输出
5. 健康检查与客户端管理
"""

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, AsyncGenerator

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

# ===================== 数据模型 =====================
@dataclass
class MCPServerConfig:
    name: str
    endpoint: str
    enabled: bool = True
    timeout: int = 30

@dataclass
class ToolInfo:
    name: str
    server_name: str
    schema: Dict[str, Any]

    @property
    def full_name(self):
        return f"{self.server_name}.{self.name}"

# ===================== MCP 聚合管理器 =====================
class MCPAggregator:
    def __init__(self):
        self.servers: Dict[str, MCPServerConfig] = {}
        self.clients: Dict[str, httpx.AsyncClient] = {}
        self.tools: Dict[str, ToolInfo] = {}
        self.health_status: Dict[str, bool] = {}
        self.request_ids: Dict[str, int] = {}

    def add_server(self, config: MCPServerConfig):
        self.servers[config.name] = config
        self.health_status[config.name] = False
        self.request_ids[config.name] = 0

    def _next_id(self, server_name: str) -> int:
        self.request_ids[server_name] += 1
        return self.request_ids[server_name]

    async def connect_all(self):
        """连接所有启用的服务器并发现工具"""
        for name, config in self.servers.items():
            if config.enabled:
                await self._connect_server(name, config)

    async def _connect_server(self, name: str, config: MCPServerConfig):
        client = httpx.AsyncClient(timeout=config.timeout)
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": self._next_id(name),
                "method": "initialize",
                "params": {
                    "clientInfo": {"name": "MCPAggregator", "version": "1.0.0"},
                    "capabilities": {}
                }
            }
            resp = await client.post(config.endpoint, json=payload)
            resp.raise_for_status()
            self.clients[name] = client
            self.health_status[name] = True
            await self._discover_tools(name, config, client)
            print(f"✅ 服务器 {name} 连接成功")
        except Exception as e:
            self.health_status[name] = False
            await client.aclose()
            print(f"❌ 服务器 {name} 连接失败: {e}")

    async def _discover_tools(self, server_name: str, config: MCPServerConfig, client: httpx.AsyncClient):
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(server_name),
            "method": "tools/list",
            "params": {}
        }
        resp = await client.post(config.endpoint, json=payload)
        resp.raise_for_status()
        data = resp.json()

        # 兼容返回 result 是列表或字典
        result_list = []
        if isinstance(data, dict):
            result = data.get("result", [])
            if isinstance(result, list):
                result_list = result
            elif isinstance(result, dict) and "tools" in result:
                result_list = result["tools"]
        elif isinstance(data, list):
            result_list = data

        for tool in result_list:
            func = tool.get("function", {})
            tool_name = func.get("name")
            if tool_name:
                self.tools[f"{server_name}.{tool_name}"] = ToolInfo(
                    name=tool_name,
                    server_name=server_name,
                    schema=func
                )

    async def call_tool(self, full_tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """调用工具（同步结果）"""
        if full_tool_name not in self.tools:
            return {"success": False, "error": f"工具 {full_tool_name} 不存在"}

        tool = self.tools[full_tool_name]
        server_name = tool.server_name
        if not self.health_status.get(server_name, False):
            return {"success": False, "error": f"服务器 {server_name} 不可用"}

        client = self.clients[server_name]
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(server_name),
            "method": "tools/call",
            "params": {
                "name": tool.name,
                "arguments": arguments
            }
        }

        try:
            resp = await client.post(self.servers[server_name].endpoint, json=payload)
            resp.raise_for_status()
            # Streamable MCP 也可能返回列表或字典
            try:
                data = resp.json()
            except Exception:
                text = await resp.aread()
                data = json.loads(text.decode())
            # 提取结果
            if isinstance(data, dict) and "result" in data:
                return {"success": True, "result": data["result"]}
            else:
                return {"success": True, "result": data}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def call_tool_stream(self, full_tool_name: str, arguments: Dict[str, Any]) -> AsyncGenerator[str, None]:
        """流式调用工具（SSE / Streamable MCP）"""
        if full_tool_name not in self.tools:
            yield json.dumps({"success": False, "error": f"工具 {full_tool_name} 不存在"})
            return

        tool = self.tools[full_tool_name]
        server_name = tool.server_name
        if not self.health_status.get(server_name, False):
            yield json.dumps({"success": False, "error": f"服务器 {server_name} 不可用"})
            return

        client = self.clients[server_name]
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(server_name),
            "method": "tools/call",
            "params": {
                "name": tool.name,
                "arguments": arguments
            }
        }

        async with client.stream("POST", self.servers[server_name].endpoint, json=payload) as resp:
            async for chunk in resp.aiter_bytes():
                if chunk:
                    try:
                        text = chunk.decode("utf-8").strip()
                        if text:
                            yield text
                    except Exception:
                        continue

# ===================== FastAPI 聚合接口 =====================
app = FastAPI(title="Streamable MCP Aggregator")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

aggregator = MCPAggregator()
aggregator.add_server(MCPServerConfig(name="local", endpoint="http://localhost:8000/mcp"))

@app.on_event("startup")
async def startup_event():
    await aggregator.connect_all()

@app.get("/aggregate/servers")
async def list_servers():
    return [
        {"name": name, "endpoint": s.endpoint, "healthy": aggregator.health_status.get(name, False)}
        for name, s in aggregator.servers.items()
    ]

@app.get("/aggregate/tools")
async def list_tools():
    return [t.full_name for t in aggregator.tools.values()]

@app.post("/aggregate/call")
async def aggregate_call(req: Request):
    body = await req.json()
    tool_name = body.get("tool")
    arguments = body.get("arguments", {})
    result = await aggregator.call_tool(tool_name, arguments)
    return JSONResponse(result)

@app.post("/aggregate/call_stream")
async def aggregate_call_stream(req: Request):
    body = await req.json()
    tool_name = body.get("tool")
    arguments = body.get("arguments", {})

    async def event_generator():
        async for chunk in aggregator.call_tool_stream(tool_name, arguments):
            yield f"data: {chunk}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/aggregate/health")
async def aggregate_health():
    return {"servers": aggregator.health_status}

# ===================== 启动 =====================
if __name__ == "__main__":
    import uvicorn
    print(f"""
    🚀 {aggregator} 启动中...

    📡 API 文档: http://localhost:9000/docs
    📋 工具列表: http://localhost:9000/tools
    🔧 调用工具: POST http://localhost:9000/tools/call

    """)
    uvicorn.run(app, host="0.0.0.0", port=9000)
