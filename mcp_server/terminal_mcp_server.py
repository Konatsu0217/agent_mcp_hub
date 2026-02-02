import json
import asyncio
import inspect
import subprocess
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from typing import AsyncGenerator, Dict, Any, Optional

# ===================== Terminal MCP服务器 =====================
class TerminalMCPServer:
    def __init__(self, name="Terminal MCP Server"):
        self.name = name
        self.tools = {}
        self.schemas = {}
        self._register_tools()
    
    def _register_tools(self):
        """注册终端相关工具"""
        # 注册同步命令执行工具
        self.tools["execute_command"] = self.execute_command
        self.schemas["execute_command"] = {
            "type": "function",
            "function": {
                "name": "execute_command",
                "description": "执行终端命令并返回结果",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "要执行的终端命令"
                        },
                        "timeout": {
                            "type": "integer",
                            "description": "命令执行超时时间（秒），默认30秒",
                            "default": 30
                        }
                    },
                    "required": ["command"]
                }
            }
        }
        
        # 注册流式命令执行工具
        self.tools["execute_command_stream"] = self.execute_command_stream
        self.schemas["execute_command_stream"] = {
            "type": "function",
            "function": {
                "name": "execute_command_stream",
                "description": "流式执行终端命令并实时返回结果",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "要执行的终端命令"
                        },
                        "timeout": {
                            "type": "integer",
                            "description": "命令执行超时时间（秒），默认60秒",
                            "default": 60
                        }
                    },
                    "required": ["command"]
                }
            }
        }
    
    def initialize(self, client_info=None, capabilities=None):
        """初始化MCP服务器"""
        return {
            "protocolVersion": "2024-11-05",
            "serverName": self.name,
            "tools": self.list_tools()
        }
    
    def list_tools(self):
        """列出所有工具"""
        return list(self.schemas.values())
    
    def execute_command(self, command: str, timeout: int = 30) -> Dict[str, Any]:
        """执行终端命令并返回结果"""
        try:
            # 执行命令
            result = subprocess.run(
                command, 
                shell=True, 
                capture_output=True, 
                text=True, 
                timeout=timeout
            )
            
            return {
                "success": True,
                "result": {
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "returncode": result.returncode,
                    "command": command
                }
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": f"Command timed out after {timeout} seconds",
                "error_type": "TimeoutError"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            }
    
    async def execute_command_stream(self, command: str, timeout: int = 60) -> AsyncGenerator[Dict[str, Any], None]:
        """流式执行终端命令并实时返回结果"""
        try:
            # 启动子进程
            process = subprocess.Popen(
                command, 
                shell=True, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.STDOUT,  # 合并 stderr 到 stdout
                text=True,
                bufsize=1  # 行缓冲
            )
            
            # 实时读取输出
            for line in iter(process.stdout.readline, ''):
                if line:
                    yield {
                        "type": "stdout",
                        "data": line.strip(),
                        "command": command
                    }
                    await asyncio.sleep(0.01)  # 让出控制权
            
            # 等待进程结束
            process.wait(timeout=timeout)
            
            # 输出最终状态
            yield {
                "type": "result",
                "data": {
                    "returncode": process.returncode,
                    "command": command,
                    "status": "completed"
                }
            }
            
        except subprocess.TimeoutExpired:
            yield {
                "type": "error",
                "data": {
                    "error": f"Command timed out after {timeout} seconds",
                    "error_type": "TimeoutError",
                    "command": command
                }
            }
        except Exception as e:
            yield {
                "type": "error",
                "data": {
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "command": command
                }
            }

# ===================== 创建MCP实例 =====================
mcp = TerminalMCPServer()

# ===================== FastAPI应用 =====================
app = FastAPI(title=mcp.name, version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

@app.post("/mcp")
async def mcp_endpoint(req: Request):
    """MCP服务器端点"""
    try:
        payload = await req.json()
        method = payload.get("method")
        params = payload.get("params", {})
        
        if method == "initialize":
            result = mcp.initialize(
                client_info=params.get("clientInfo", {}),
                capabilities=params.get("capabilities", {})
            )
            return {
                "jsonrpc": "2.0",
                "id": payload.get("id"),
                "result": result
            }
        
        elif method == "tools/list":
            result = mcp.list_tools()
            return {
                "jsonrpc": "2.0",
                "id": payload.get("id"),
                "result": result
            }
        
        elif method == "tools/call":
            tool_name = params["name"]
            arguments = params.get("arguments", {})
            
            if tool_name not in mcp.tools:
                return {
                    "jsonrpc": "2.0",
                    "id": payload.get("id"),
                    "error": {
                        "code": -32601,
                        "message": f"Tool '{tool_name}' not found"
                    }
                }
            
            func = mcp.tools[tool_name]
            
            async def stream_response():
                if inspect.isasyncgenfunction(func):
                    # 处理异步生成器
                    async for item in func(**arguments):
                        yield json.dumps({
                            "jsonrpc": "2.0",
                            "id": payload.get("id"),
                            "result": item
                        }, ensure_ascii=False) + "\n"
                elif asyncio.iscoroutinefunction(func):
                    # 处理普通异步函数
                    result = await func(**arguments)
                    yield json.dumps({
                        "jsonrpc": "2.0",
                        "id": payload.get("id"),
                        "result": result
                    }, ensure_ascii=False) + "\n"
                else:
                    # 处理同步函数
                    result = func(**arguments)
                    yield json.dumps({
                        "jsonrpc": "2.0",
                        "id": payload.get("id"),
                        "result": result
                    }, ensure_ascii=False) + "\n"
            
            return StreamingResponse(stream_response(), media_type="application/json")
        
        else:
            return {
                "jsonrpc": "2.0",
                "id": payload.get("id"),
                "error": {
                    "code": -32601,
                    "message": f"Method '{method}' not found"
                }
            }
    
    except Exception as e:
        return {
            "jsonrpc": "2.0",
            "id": payload.get("id") if 'payload' in locals() else None,
            "error": {
                "code": -32603,
                "message": str(e)
            }
        }

@app.get("/health")
async def health():
    """健康检查"""
    return {
        "status": "healthy",
        "tools": list(mcp.tools.keys()),
        "server": mcp.name
    }

# ===================== 启动服务器 =====================
if __name__ == "__main__":
    import uvicorn
    print(f"🚀 {mcp.name} 启动中...")
    print(f"📋 已注册 {len(mcp.tools)} 个工具:")
    for tool_name in mcp.tools.keys():
        print(f"   - {tool_name}")
    print(f"🌐 服务地址: http://localhost:8001/mcp")
    uvicorn.run(app, host="0.0.0.0", port=8001)
