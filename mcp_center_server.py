import argparse
import os
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse

from mcp_hub import MCPHub
from model import MCPServerConfig

# ===================== MCPHub FastAPI 接口 =====================
app = FastAPI(title="MCPHub - MCP智能枢纽", description="🚀 统一管理和调用多个MCP服务器的智能枢纽")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# 支持通过命令行参数或环境变量指定配置文件
def get_config_file():
    parser = argparse.ArgumentParser(description="MCPHub - MCP智能枢纽服务器")
    parser.add_argument("--config", "-c", help="MCP服务器配置文件路径", default=None)
    args = parser.parse_args()
    
    # 优先级: 命令行参数 > 环境变量 > 默认文件
    config_file = args.config or os.getenv("MCP_CONFIG_FILE")
    
    if config_file and os.path.exists(config_file):
        return config_file
    
    # 尝试默认配置文件
    default_configs = ["mcp_servers.yaml", "mcp_servers.json", "config/mcp_servers.yaml", "config/mcp_servers.json"]
    for default_config in default_configs:
        if os.path.exists(default_config):
            return default_config
    
    return None

config_file = get_config_file()
hub = MCPHub(config_file=config_file)

# 如果没有配置文件，添加默认的本地服务器
if not config_file:
    print("⚠️  未找到配置文件，使用默认的本地MCP服务器配置")
    hub.add_server(MCPServerConfig(name="local", endpoint="http://localhost:8000/mcp"))

@app.on_event("startup")
async def startup_event():
    await hub.connect_all()

@app.get("/mcp_hub/servers")
async def list_servers():
    return [
        {"name": name, "endpoint": s.endpoint, "healthy": hub.health_status.get(name, False)}
        for name, s in hub.servers.items()
    ]

@app.get("/mcp_hub/tools")
async def list_tools():
    return {"tools": [t.schema for t in hub.tools.values()]}

@app.post("/mcp_hub/call")
async def hub_call(req: Request):
    body = await req.json()
    tool_name = body.get("tool")
    arguments = body.get("arguments", {})
    result = await hub.call_tool(tool_name, arguments)
    return JSONResponse(result)

@app.post("/mcp_hub/call_stream")
async def hub_call_stream(req: Request):
    body = await req.json()
    tool_name = body.get("tool")
    arguments = body.get("arguments", {})

    async def event_generator():
        async for chunk in hub.call_tool_stream(tool_name, arguments):
            yield f"data: {chunk}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/mcp_hub/health")
async def hub_health():
    return {"servers": hub.health_status}

# ===================== 启动 =====================
if __name__ == "__main__":
    import uvicorn
    print(f"""
    🚀 MCPHub 启动中...

    📡 API 文档: http://localhost:9000/docs
    📋 服务器列表: http://localhost:9000/mcp_hub/servers
    🔧 工具列表: http://localhost:9000/mcp_hub/tools
    💓 健康检查: http://localhost:9000/mcp_hub/health
    
    🔗 调用工具: POST http://localhost:9000/mcp_hub/call
    ⚡ 流式调用: POST http://localhost:9000/mcp_hub/call_stream

    """)
    uvicorn.run(app, host="0.0.0.0", port=9000)
