"""
MCPHub - Streamable MCP 智能枢纽

🚀 你的MCP服务器智能管理中心

核心能力:
1. 🔗 多MCP服务器统一接入
2. 🎯 智能工具发现与路由
3. ⚡ 流式输出支持
4. 💓 实时健康监控
5. 🔧 动态配置管理

就像MCP世界的交通枢纽，让所有服务器无缝协作！
"""

import json
try:
    import yaml  # 可选
except Exception:
    yaml = None
from typing import Any, Dict, AsyncGenerator

import httpx

from model import MCPServerConfig, ToolInfo, MCPServersConfig


# ===================== MCPHub - 智能枢纽 =====================
class MCPHub:
    def __init__(self, config_file: str = None):
        self.servers: Dict[str, MCPServerConfig] = {}
        self.clients: Dict[str, httpx.AsyncClient] = {}
        self.tools: Dict[str, ToolInfo] = {}
        self.health_status: Dict[str, bool] = {}
        self.request_ids: Dict[str, int] = {}
        
        if config_file:
            self.load_config(config_file)

    def load_config(self, config_file: str):
        """从配置文件加载MCP服务器配置"""
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                if (config_file.endswith('.yaml') or config_file.endswith('.yml')):
                    if yaml is None:
                        raise ImportError("需要PyYAML来解析YAML配置文件，请安装 'pyyaml' 或改用JSON配置")
                    config_data = yaml.safe_load(f)
                else:
                    config_data = json.load(f)
            
            # 支持两种格式：直接列表格式和包含servers字段的对象格式
            if isinstance(config_data, list):
                servers_config = MCPServersConfig(servers=[MCPServerConfig(**server) for server in config_data])
            elif isinstance(config_data, dict) and 'servers' in config_data:
                servers_config = MCPServersConfig(servers=[MCPServerConfig(**server) for server in config_data['servers']])
            else:
                # 尝试直接作为单个服务器配置
                servers_config = MCPServersConfig(servers=[MCPServerConfig(**config_data)])
            
            # 添加所有服务器配置
            for server_config in servers_config.servers:
                self.add_server(server_config)
                
            print(f"✅ 成功加载配置文件: {config_file}, 共 {len(servers_config.servers)} 个MCP服务器")
        except Exception as e:
            print(f"❌ 加载配置文件失败: {e}")
            raise

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
                    "clientInfo": {"name": "MCPHub", "version": "1.0.0"},
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
                # 构建符合 OpenAPI 标准的 schema 格式
                openapi_schema = {
                    "type": "function",
                    "function": func.copy()  # 复制原始 function 对象
                }
                # 修改 function 内部的 name 为完整名称
                openapi_schema["function"]["name"] = f"{server_name}.{tool_name}"
                
                self.tools[f"{server_name}.{tool_name}"] = ToolInfo(
                    name=tool_name,
                    server_name=server_name,
                    schema=openapi_schema
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
