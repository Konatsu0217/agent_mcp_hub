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