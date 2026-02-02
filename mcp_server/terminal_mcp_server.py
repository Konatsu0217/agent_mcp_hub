import json
import asyncio
import inspect
import subprocess
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from typing import AsyncGenerator, Dict, Any, Optional

# 命令安全等级
SAFETY_LEVELS = {
    "SAFE": 0,      # 安全命令
    "WARNING": 1,   # 警告命令
    "DANGEROUS": 2  # 危险命令
}

# 危险命令模式
dangerous_commands = [
    r'rm\s+-rf',
    r'sudo\s+',
    r'format\s+',
    r'dd\s+',
    r'chmod\s+[0-7]{3}',
    r'chown\s+',
    r'kill\s+-9',
    r'shutdown\s+',
    r'reboot\s+',
    r'init\s+',
    r'mkfs\s+',
    r'fsck\s+',
    r'mount\s+',
    r'umount\s+',
    r'iptables\s+',
    r'curl\s+.*>.*',
    r'wget\s+.*>.*',
    r'echo\s+.*>.*',
    r'cat\s+.*>.*',
    r'touch\s+/etc/.*',
    r'rmdir\s+/.*',
    r'mv\s+/.*',
    r'cp\s+/.*',
]

# 警告命令模式
warning_commands = [
    r'rm\s+',
    r'mkdir\s+-p\s+/.*',
    r'cd\s+/.*',
    r'ls\s+-la\s+/.*',
    r'find\s+/.*',
    r'grep\s+.*>/.*',
    r'sort\s+.*>/.*',
    r'uniq\s+.*>/.*',
]

import re
import time
import os

def record_command_history(command: str, success: bool, returncode: int, stdout: str, stderr: str, safety_assessment: Dict[str, Any], working_directory: str):
    """记录命令执行历史到文件
    
    Args:
        command: 执行的命令
        success: 命令是否执行成功
        returncode: 命令返回码
        stdout: 标准输出
        stderr: 标准错误
        safety_assessment: 命令安全评估结果
        working_directory: 命令执行的工作目录
    """
    history_file = "command_history.json"
    
    # 读取现有历史记录
    history = []
    if os.path.exists(history_file):
        try:
            with open(history_file, 'r', encoding='utf-8') as f:
                history = json.load(f)
        except Exception:
            # 如果文件损坏，创建新的历史记录
            history = []
    
    # 创建新的命令记录
    command_record = {
        "timestamp": time.time(),
        "command": command,
        "success": success,
        "returncode": returncode,
        "stdout": stdout,
        "stderr": stderr,
        "safety_level": safety_assessment.get("level_name", "UNKNOWN"),
        "working_directory": working_directory,
        "executed_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    }
    
    # 追加新记录
    history.append(command_record)
    
    # 写入历史记录文件
    try:
        with open(history_file, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception:
        # 忽略文件写入错误，不影响命令执行
        pass

def assess_command_safety(command: str) -> Dict[str, Any]:
    """评估命令安全等级
    
    Args:
        command: 要评估的命令
        
    Returns:
        包含安全等级和评估信息的字典
    """
    # 检查危险命令
    for pattern in dangerous_commands:
        if re.search(pattern, command):
            return {
                "level": SAFETY_LEVELS["DANGEROUS"],
                "level_name": "DANGEROUS",
                "reason": f"Command matches dangerous pattern: {pattern}",
                "requires_approval": True
            }
    
    # 检查警告命令
    for pattern in warning_commands:
        if re.search(pattern, command):
            return {
                "level": SAFETY_LEVELS["WARNING"],
                "level_name": "WARNING",
                "reason": f"Command matches warning pattern: {pattern}",
                "requires_approval": True
            }
    
    # 默认安全命令
    return {
        "level": SAFETY_LEVELS["SAFE"],
        "level_name": "SAFE",
        "reason": "Command appears to be safe",
        "requires_approval": False
    }

# ===================== Terminal MCP服务器 =====================
class TerminalMCPServer:
    def __init__(self, name="Terminal MCP Server"):
        self.name = name
        self.tools = {}
        self.schemas = {}
        self.working_directory = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))  # 默认项目根目录
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
        
        # 注册命令批准工具
        self.tools["approve_command"] = self.approve_command
        self.schemas["approve_command"] = {
            "type": "function",
            "function": {
                "name": "approve_command",
                "description": "批准并执行需要审批的命令",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "要执行的终端命令"
                        },
                        "approval_id": {
                            "type": "string",
                            "description": "审批ID"
                        },
                        "timeout": {
                            "type": "integer",
                            "description": "命令执行超时时间（秒），默认30秒",
                            "default": 30
                        }
                    },
                    "required": ["command", "approval_id"]
                }
            }
        }
    
    def initialize(self, client_info=None, capabilities=None):
        """初始化MCP服务器"""
        # 从client_info中获取工作目录
        if client_info and isinstance(client_info, dict):
            custom_working_dir = client_info.get("working_directory")
            if custom_working_dir and os.path.exists(custom_working_dir):
                self.working_directory = os.path.abspath(custom_working_dir)
        
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
        # 评估命令安全等级
        safety_assessment = assess_command_safety(command)
        
        # 对于危险命令，返回pending状态
        if safety_assessment["requires_approval"]:
            return {
                "success": False,
                "status": "pending",
                "safety_assessment": safety_assessment,
                "message": "Command requires approval before execution",
                "command": command
            }
        
        try:
            # 执行命令
            result = subprocess.run(
                command, 
                shell=True, 
                capture_output=True, 
                text=True, 
                timeout=timeout,
                cwd=self.working_directory
            )
            
            # 记录命令历史
            record_command_history(
                command=command,
                success=True,
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                safety_assessment=safety_assessment,
                working_directory=self.working_directory
            )
            
            return {
                "success": True,
                "status": "completed",
                "safety_assessment": safety_assessment,
                "result": {
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "returncode": result.returncode,
                    "command": command
                }
            }
        except subprocess.TimeoutExpired:
            # 记录命令历史
            record_command_history(
                command=command,
                success=False,
                returncode=-1,
                stdout="",
                stderr=f"Command timed out after {timeout} seconds",
                safety_assessment=safety_assessment,
                working_directory=self.working_directory
            )
            
            return {
                "success": False,
                "status": "error",
                "safety_assessment": safety_assessment,
                "error": f"Command timed out after {timeout} seconds",
                "error_type": "TimeoutError"
            }
        except Exception as e:
            # 记录命令历史
            record_command_history(
                command=command,
                success=False,
                returncode=-1,
                stdout="",
                stderr=str(e),
                safety_assessment=safety_assessment,
                working_directory=self.working_directory
            )
            
            return {
                "success": False,
                "status": "error",
                "safety_assessment": safety_assessment,
                "error": str(e),
                "error_type": type(e).__name__
            }
    
    async def execute_command_stream(self, command: str, timeout: int = 60) -> AsyncGenerator[Dict[str, Any], None]:
        """流式执行终端命令并实时返回结果"""
        # 评估命令安全等级
        safety_assessment = assess_command_safety(command)
        
        # 对于危险命令，返回pending状态
        if safety_assessment["requires_approval"]:
            yield {
                "type": "pending",
                "data": {
                    "success": False,
                    "status": "pending",
                    "safety_assessment": safety_assessment,
                    "message": "Command requires approval before execution",
                    "command": command
                }
            }
            return
        
        stdout_output = []
        stderr_output = []
        returncode = -1
        
        try:
            # 启动子进程
            process = subprocess.Popen(
                command, 
                shell=True, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.STDOUT,  # 合并 stderr 到 stdout
                text=True,
                bufsize=1,  # 行缓冲
                cwd=self.working_directory
            )
            
            # 实时读取输出
            for line in iter(process.stdout.readline, ''):
                if line:
                    stdout_output.append(line.strip())
                    yield {
                        "type": "stdout",
                        "data": line.strip(),
                        "command": command,
                        "safety_assessment": safety_assessment
                    }
                    await asyncio.sleep(0.01)  # 让出控制权
            
            # 等待进程结束
            returncode = process.wait(timeout=timeout)
            
            # 记录命令历史
            record_command_history(
                command=command,
                success=True,
                returncode=returncode,
                stdout="\n".join(stdout_output),
                stderr="",
                safety_assessment=safety_assessment,
                working_directory=self.working_directory
            )
            
            # 输出最终状态
            yield {
                "type": "result",
                "data": {
                    "returncode": returncode,
                    "command": command,
                    "status": "completed",
                    "safety_assessment": safety_assessment
                }
            }
            
        except subprocess.TimeoutExpired:
            # 记录命令历史
            record_command_history(
                command=command,
                success=False,
                returncode=-1,
                stdout="\n".join(stdout_output),
                stderr=f"Command timed out after {timeout} seconds",
                safety_assessment=safety_assessment,
                working_directory=self.working_directory
            )
            
            yield {
                "type": "error",
                "data": {
                    "error": f"Command timed out after {timeout} seconds",
                    "error_type": "TimeoutError",
                    "command": command,
                    "safety_assessment": safety_assessment
                }
            }
        except Exception as e:
            # 记录命令历史
            record_command_history(
                command=command,
                success=False,
                returncode=-1,
                stdout="\n".join(stdout_output),
                stderr=str(e),
                safety_assessment=safety_assessment,
                working_directory=self.working_directory
            )
            
            yield {
                "type": "error",
                "data": {
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "command": command,
                    "safety_assessment": safety_assessment
                }
            }
    
    def approve_command(self, command: str, approval_id: str, timeout: int = 30) -> Dict[str, Any]:
        """批准并执行命令"""
        # 评估命令安全等级
        safety_assessment = assess_command_safety(command)
        
        try:
            # 执行命令
            result = subprocess.run(
                command, 
                shell=True, 
                capture_output=True, 
                text=True, 
                timeout=timeout,
                cwd=self.working_directory
            )

            # 记录命令历史
            record_command_history(
                command=command,
                success=True,
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                safety_assessment=safety_assessment,
                working_directory=self.working_directory
            )
            
            return {
                "success": True,
                "status": "completed",
                "approval_id": approval_id,
                "result": {
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "returncode": result.returncode,
                    "command": command
                }
            }
        except subprocess.TimeoutExpired:
            # 记录命令历史
            record_command_history(
                command=command,
                success=False,
                returncode=-1,
                stdout="",
                stderr=f"Command timed out after {timeout} seconds",
                safety_assessment=safety_assessment,
                working_directory=self.working_directory
            )
            
            return {
                "success": False,
                "status": "error",
                "approval_id": approval_id,
                "error": f"Command timed out after {timeout} seconds",
                "error_type": "TimeoutError"
            }
        except Exception as e:
            # 记录命令历史
            record_command_history(
                command=command,
                success=False,
                returncode=-1,
                stdout="",
                stderr=str(e),
                safety_assessment=safety_assessment,
                working_directory=self.working_directory
            )
            
            return {
                "success": False,
                "status": "error",
                "approval_id": approval_id,
                "error": str(e),
                "error_type": type(e).__name__
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
        
        elif method == "tools/approve":
            tool_name = params.get("name", "approve_command")
            arguments = params.get("arguments", {})
            approval_id = params.get("approval_id", str(hash(str(arguments))))
            
            # 构建批准命令的参数
            approve_args = {
                "command": arguments.get("command"),
                "approval_id": approval_id,
                "timeout": arguments.get("timeout", 30)
            }
            
            if not approve_args["command"]:
                return {
                    "jsonrpc": "2.0",
                    "id": payload.get("id"),
                    "error": {
                        "code": -32602,
                        "message": "Command is required for approval"
                    }
                }
            
            # 调用批准命令工具
            result = mcp.tools["approve_command"](**approve_args)
            
            return {
                "jsonrpc": "2.0",
                "id": payload.get("id"),
                "result": result
            }
        
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
