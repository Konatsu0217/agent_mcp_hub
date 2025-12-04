# ===================== 数据模型 =====================
from dataclasses import dataclass, field
from typing import Dict, Any, List


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


@dataclass
class MCPServersConfig:
    """MCP服务器配置列表"""
    servers: List[MCPServerConfig] = field(default_factory=list)



  # {
  #   "id": "call_123",                     // 调用 ID，用于工具返回时对齐
  #   "type": "function",                  // 目前基本固定是 function
  #   "function": {
  #     "name": "search_user",            // 工具名（必须匹配 tools[...] 里定义的 name）
  #     "arguments": "{\"query\":\"abc\"}" // JSON 字符串！不是 dict！
  #   }
  # }
@dataclass
class MCPToolCallRequest:
    id: str
    type: str = "function"
    function: Dict[str, Any] = field(default_factory=dict)
