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