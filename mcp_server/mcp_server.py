import asyncio
import inspect
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional


# ===================== 工具参数模型 =====================
@dataclass
class Parameter:
    name: str
    type: str
    description: str
    required: bool = True
    enum: Optional[List[Any]] = None

# ===================== MCP 核心 =====================
class MCPServer:
    def __init__(self, name="MCP Server", protocol_version="2024-11-05"):
        self.name = name
        self.protocol_version = protocol_version
        self.tools: Dict[str, Callable] = {}
        self.schemas: Dict[str, Dict] = {}

    # 工具装饰器
    def tool(self, name: Optional[str] = None, description: Optional[str] = None,
             parameters: Optional[List[Parameter]] = None):
        def decorator(func: Callable) -> Callable:
            tool_name = name or func.__name__
            tool_desc = description or func.__doc__ or "No description"
            param_schema = self._build_schema(parameters) if parameters else self._extract_schema(func)
            self.tools[tool_name] = func
            self.schemas[tool_name] = {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": tool_desc.strip(),
                    "parameters": param_schema
                }
            }
            return func
        return decorator

    def _build_schema(self, params: List[Parameter]) -> Dict:
        properties, required = {}, []
        for p in params:
            properties[p.name] = {"type": p.type, "description": p.description}
            if p.enum:
                properties[p.name]["enum"] = p.enum
            if p.required:
                required.append(p.name)
        schema = {"type": "object", "properties": properties}
        if required:
            schema["required"] = required
        return schema

    def _extract_schema(self, func: Callable) -> Dict:
        sig = inspect.signature(func)
        properties, required = {}, []
        for name, param in sig.parameters.items():
            if name in ("self", "cls"):
                continue
            ptype = "string"
            if param.annotation != inspect.Parameter.empty:
                ptype = {int: "integer", float: "number", bool: "boolean", list: "array", dict: "object"}.get(
                    param.annotation, "string")
            properties[name] = {"type": ptype, "description": f"Parameter {name}"}
            if param.default == inspect.Parameter.empty:
                required.append(name)
        schema = {"type": "object", "properties": properties}
        if required:
            schema["required"] = required
        return schema

    def list_tools(self) -> List[Dict]:
        return list(self.schemas.values())

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict:
        func = self.tools.get(tool_name)
        if func is None:
            return {"success": False, "error": f"Tool '{tool_name}' not found"}

        try:
            if inspect.iscoroutinefunction(func):
                # 异步函数直接 await
                return {"success": True, "result": asyncio.run(func(**arguments))}
            else:
                return {"success": True, "result": func(**arguments)}
        except Exception as e:
            return {"success": False, "error": str(e), "error_type": type(e).__name__}

    def initialize(self, client_info: Dict[str, Any], capabilities: Dict[str, Any]):
        return {
            "protocolVersion": self.protocol_version,
            "serverName": self.name,
            "tools": self.list_tools()
        }

    def tools_call(self, name: str, arguments: Dict[str, Any]):
        return self.call_tool(name, arguments)

    def tools_list(self):
        return self.list_tools()

    # @mcp.tool(name="echo", description="回显消息")
    # def echo(message: str) -> str:
    #     return message
    #
    # @mcp.tool(
    #     name="get_weather",
    #     description="查询天气",
    #     parameters=[
    #         Parameter("city", "string", "要查询天气的城市"),
    #         Parameter("date", "string", "要查询的日期"),
    #     ]
    # )
    # def get_weather(city: str, date: str) -> str:
    #     if city == "北京":
    #         return f"北京在 {date} 是晴天"
    #     elif city == "上海":
    #         return f"上海在 {date} 是多云"
    #     elif city == "广州":
    #         return f"广州在 {date} 是阴云"
    #     else:
    #         return f"天气信息: {city} 在 {date}"
    #
    # @mcp.tool(name="add", description="加法运算")
    # def add(a: float, b: float) -> float:
    #     return a + b
    #
    # @mcp.tool(name="count_stream", description="计数流")
    # async def count_stream(n: int):
    #     for i in range(1, n + 1):
    #         await asyncio.sleep(1)
    #         yield {"count": i}
    #
    #
    # @mcp.tool(
    #     name="search_files",
    #     description="在目录中搜索文件",
    #     parameters=[
    #         Parameter("directory", "string", "搜索的目录路径"),
    #         Parameter("pattern", "string", "文件名匹配模式 (支持通配符)"),
    #         Parameter("recursive", "boolean", "是否递归搜索子目录", required=False),
    #         Parameter("max_results", "integer", "最大返回结果数", required=False)
    #     ]
    # )
    # def search_files(directory: str, pattern: str, recursive: bool = False, max_results: int = 100):
    #     return {"success": True, "result": f"Searching {directory} for {pattern}"}
