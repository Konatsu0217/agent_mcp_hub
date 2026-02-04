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
import yaml
from typing import Any, Dict, AsyncGenerator
import asyncio
import time
import hashlib

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
        self._lock = asyncio.Lock()
        self._config_file = config_file
        self._bg_task = None
        self._retry_info: Dict[str, Dict[str, Any]] = {}
        self._last_config_hash = None
        
        if config_file:
            self.load_config(config_file)

    def load_config(self, config_file: str):
        """从配置文件加载MCP服务器配置"""
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                if config_file.endswith('.yaml') or config_file.endswith('.yml'):
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

    async def start_background_tasks(self, config_file: str = None, interval: int = 300):
        if config_file:
            self._config_file = config_file
        if self._bg_task is None:
            self._bg_task = asyncio.create_task(self._reconcile_loop(interval))

    async def _reconcile_loop(self, interval: int):
        while True:
            try:
                await self._reconcile_once()
            except Exception:
                pass
            await asyncio.sleep(interval)

    def _load_config_snapshot(self) -> Dict[str, MCPServerConfig]:
        snapshot: Dict[str, MCPServerConfig] = {}
        if not self._config_file:
            return snapshot
        with open(self._config_file, 'r', encoding='utf-8') as f:
            if self._config_file.endswith('.yaml') or self._config_file.endswith('.yml'):
                data = yaml.safe_load(f)
            else:
                data = json.load(f)
        if isinstance(data, list):
            for s in data:
                cfg = MCPServerConfig(**s)
                snapshot[cfg.name] = cfg
        elif isinstance(data, dict) and 'servers' in data:
            for s in data['servers']:
                cfg = MCPServerConfig(**s)
                snapshot[cfg.name] = cfg
        else:
            cfg = MCPServerConfig(**data)
            snapshot[cfg.name] = cfg
        return snapshot

    def _snapshot_hash(self, snap: Dict[str, MCPServerConfig]) -> str:
        items = sorted([(n, c.endpoint, c.enabled, c.timeout) for n, c in snap.items()])
        raw = json.dumps(items, ensure_ascii=False)
        return hashlib.sha1(raw.encode('utf-8')).hexdigest()

    async def _reconcile_once(self):
        snap = self._load_config_snapshot()
        snap_hash = self._snapshot_hash(snap)
        current_names = set(self.servers.keys())
        snap_names = set(snap.keys())
        added = snap_names - current_names
        removed = current_names - snap_names if self._config_file else set()
        common = current_names & snap_names
        changed = set()
        for n in common:
            c1 = self.servers[n]
            c2 = snap[n]
            if c1.endpoint != c2.endpoint or c1.enabled != c2.enabled or c1.timeout != c2.timeout:
                changed.add(n)
        if self._last_config_hash != snap_hash:
            for n in added:
                cfg = snap[n]
                async with self._lock:
                    self.add_server(cfg)
                if cfg.enabled:
                    await self._connect_server(n, cfg)
            for n in removed:
                await self._disconnect_server(n)
            for n in changed:
                cfg = snap[n]
                if not cfg.enabled:
                    await self._disconnect_server(n)
                else:
                    await self._disconnect_server(n)
                    async with self._lock:
                        self.servers[n] = cfg
                    await self._connect_server(n, cfg)
            self._last_config_hash = snap_hash
        for n in list(self.servers.keys()):
            if not self.servers[n].enabled:
                continue
            healthy = self.health_status.get(n, False)
            if not healthy:
                await self._reconnect_server(n)
            else:
                await self._ping_health(n)

    async def _disconnect_server(self, name: str):
        client = self.clients.get(name)
        if client:
            try:
                await client.aclose()
            except Exception:
                pass
        async with self._lock:
            self.clients.pop(name, None)
            self.health_status[name] = False
            to_remove = [k for k, v in self.tools.items() if v.server_name == name]
            for k in to_remove:
                self.tools.pop(k, None)
            self.servers.pop(name, None)
            self.request_ids.pop(name, None)
            self._retry_info.pop(name, None)

    async def _reconnect_server(self, name: str):
        cfg = self.servers.get(name)
        if not cfg or not cfg.enabled:
            return
        info = self._retry_info.get(name, {"attempt": 0, "next": 0})
        now = time.monotonic()
        if now < info["next"]:
            return
        attempt = info["attempt"] + 1
        delay = min(60, 2 ** min(attempt, 6))
        try:
            await self._connect_server(name, cfg)
            self._retry_info[name] = {"attempt": 0, "next": 0}
        except Exception:
            self._retry_info[name] = {"attempt": attempt, "next": now + delay}

    async def _ping_health(self, name: str):
        client = self.clients.get(name)
        cfg = self.servers.get(name)
        if not client or not cfg:
            return
        url = None
        if "/mcp" in cfg.endpoint:
            base = cfg.endpoint.rsplit("/mcp", 1)[0]
            url = base + "/health"
        if not url:
            return
        try:
            resp = await client.get(url)
            if resp.status_code != 200:
                self.health_status[name] = False
        except Exception:
            self.health_status[name] = False

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
            
            # 处理响应
            try:
                init_data = resp.json()
                # 检查是否为错误响应
                if isinstance(init_data, dict) and "error" in init_data:
                    error_info = init_data["error"]
                    error_message = error_info.get("message", str(error_info)) if isinstance(error_info, dict) else str(error_info)
                    raise Exception(f"初始化失败: {error_message}")
            except json.JSONDecodeError as e:
                raise Exception(f"响应解析失败: {str(e)}")
            
            self.clients[name] = client
            self.health_status[name] = True
            # 尝试从initialize响应中提取工具信息
            tools_from_init = []
            if isinstance(init_data, dict) and "result" in init_data:
                result = init_data["result"]
                if isinstance(result, dict) and "tools" in result:
                    tools_from_init = result["tools"]
            # 调用工具发现方法
            await self._discover_tools(name, config, client, tools_from_init)
            print(f"✅ 服务器 {name} 连接成功")
        except Exception as e:
            self.health_status[name] = False
            await client.aclose()
            print(f"❌ 服务器 {name} 连接失败: {e}")

    async def _discover_tools(self, server_name: str, config: MCPServerConfig, client: httpx.AsyncClient, tools_from_init: list = None):
        # 首先使用从initialize响应中获取的工具信息
        if tools_from_init and len(tools_from_init) > 0:
            self._process_tool_list(server_name, tools_from_init)
            print(f"✅ 从initialize响应中发现 {len(tools_from_init)} 个工具")
            return
        
        # 如果没有从initialize获取到工具，则调用tools/list方法
        try:
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

            self._process_tool_list(server_name, result_list)
            print(f"✅ 从tools/list发现 {len(result_list)} 个工具")
        except Exception as e:
            print(f"⚠️  工具发现失败: {e}")

    def _process_tool_list(self, server_name: str, tools: list):
        """处理工具列表，构建工具信息"""
        for tool in tools:
            # 处理标准MCP格式的工具定义
            if isinstance(tool, dict):
                # 情况1: 直接包含function字段
                if "function" in tool:
                    func = tool["function"]
                    tool_name = func.get("name")
                # 情况2: 直接是function对象
                elif "name" in tool and "parameters" in tool:
                    func = tool
                    tool_name = func.get("name")
                else:
                    continue
                
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
            
            # 标准JSON-RPC响应处理
            if isinstance(data, dict):
                # 处理错误响应
                if "error" in data:
                    error_info = data["error"]
                    error_message = error_info.get("message", str(error_info)) if isinstance(error_info, dict) else str(error_info)
                    return {"success": False, "error": error_message}
                # 处理成功响应
                elif "result" in data:
                    result = data["result"]
                    # 处理pending状态
                    if isinstance(result, dict) and result.get("status") == "pending":
                        return {
                            "success": False,
                            "status": "pending",
                            "data": result
                        }
                    return {"success": True, "result": result}
            # 兼容非标准响应
            return {"success": True, "result": data}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def approve_tool(self, full_tool_name: str, arguments: Dict[str, Any], approval_id: str) -> Dict[str, Any]:
        """批准工具执行"""
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
            "method": "tools/approve",
            "params": {
                "name": tool.name,
                "arguments": arguments,
                "approval_id": approval_id
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
            
            # 标准JSON-RPC响应处理
            if isinstance(data, dict):
                # 处理错误响应
                if "error" in data:
                    error_info = data["error"]
                    error_message = error_info.get("message", str(error_info)) if isinstance(error_info, dict) else str(error_info)
                    return {"success": False, "error": error_message}
                # 处理成功响应
                elif "result" in data:
                    return {"success": True, "result": data["result"]}
            # 兼容非标准响应
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

        try:
            async with client.stream("POST", self.servers[server_name].endpoint, json=payload) as resp:
                if resp.status_code != 200:
                    error_msg = f"HTTP错误: {resp.status_code}"
                    yield json.dumps({"success": False, "error": error_msg})
                    return
                
                buffer = ""
                async for chunk in resp.aiter_bytes():
                    if chunk:
                        try:
                            text = chunk.decode("utf-8")
                            buffer += text
                            
                            # 按行处理响应
                            lines = buffer.split('\n')
                            buffer = lines[-1]  # 保留最后不完整的行
                            
                            for line in lines[:-1]:
                                line = line.strip()
                                if line:
                                    # 处理标准MCP流式响应格式
                                    try:
                                        chunk_data = json.loads(line)
                                        # 检查是否为错误响应
                                        if isinstance(chunk_data, dict):
                                            if "error" in chunk_data:
                                                error_info = chunk_data["error"]
                                                error_message = error_info.get("message", str(error_info)) if isinstance(error_info, dict) else str(error_info)
                                                yield json.dumps({"success": False, "error": error_message})
                                                return
                                            elif "result" in chunk_data:
                                                # 标准JSON-RPC成功响应
                                                yield json.dumps({"success": True, "result": chunk_data["result"]})
                                            else:
                                                # 其他格式的响应
                                                yield line
                                    except json.JSONDecodeError:
                                        # 非JSON格式，直接返回
                                        yield line
                        except Exception as e:
                            yield json.dumps({"success": False, "error": f"流式处理错误: {str(e)}"})
                            return
                
                # 处理最后剩余的缓冲区内容
                if buffer.strip():
                    try:
                        chunk_data = json.loads(buffer)
                        if isinstance(chunk_data, dict):
                            if "error" in chunk_data:
                                error_info = chunk_data["error"]
                                error_message = error_info.get("message", str(error_info)) if isinstance(error_info, dict) else str(error_info)
                                yield json.dumps({"success": False, "error": error_message})
                            elif "result" in chunk_data:
                                yield json.dumps({"success": True, "result": chunk_data["result"]})
                            else:
                                yield buffer
                    except json.JSONDecodeError:
                        yield buffer
        except Exception as e:
            yield json.dumps({"success": False, "error": str(e)})
            return
