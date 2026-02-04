# MCPHub

MCP服务器智能管理中心，支持多MCP服务器聚合、工具发现和统一调用。

## 功能

- 多MCP服务器统一接入
- 自动工具发现
- 工具调用路由
- 流式输出支持
- 健康检查与状态监控
- 配置文件驱动

## 安装

```bash
pip install fastapi uvicorn httpx pyyaml
```

## 项目结构

```
mcp_server_stub/
├── mcp_hub.py              # MCPHub核心类，聚合管理多个MCP服务器
├── mcp_center_server.py    # FastAPI服务，提供统一API接口
├── mcp_server/             # MCP服务器实现目录
│   ├── mcp_server.py       # 基础MCP服务器，支持装饰器注册工具
│   ├── mcp_server_example.py # 装饰器使用示例
│   └── MCP_SERVER_GUIDE.md # MCP服务器开发指南
├── model.py                # 数据模型定义
├── mcp_servers.yaml        # MCPHub配置文件（YAML格式）
├── mcp_servers.json        # MCPHub配置文件（JSON格式）
└──  CONFIG_USAGE.md         # MCPHub配置使用说明
```


## 快速开始

### 1. 配置MCP服务器

创建配置文件 `mcp_servers.yaml`：

```yaml
servers:
  - name: local
    endpoint: http://localhost:8000/mcp
    enabled: true
    timeout: 30
```

### 2. 启动MCPHub

```bash
python mcp_center_server.py --config mcp_servers.yaml
```

服务将在 http://localhost:9000 启动。

## API 接口

### 服务器列表
- GET /mcp_hub/servers
- 响应示例
```json
[{"name":"local","endpoint":"http://localhost:8000/mcp","healthy":true}]
```

### 工具列表
- GET /mcp_hub/tools
- 响应示例（每个工具为 OpenAI function schema，function.name 带服务器前缀）
```json
{"tools":[{"type":"function","function":{"name":"local.search","parameters":{"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}}}]}
```

### 健康检查
- GET /mcp_hub/health
- 响应示例
```json
{"servers":{"local":true}}
```

### 主动刷新
- POST /mcp_hub/refresh
- 用途：立即触发一次服务发现与连接
- 响应示例
```json
{"refreshed":true}
```

### 调用工具（同步结果）
- POST /mcp_hub/call
- 请求体（MCPToolCallRequest）
```json
{
  "id": "call_123",
  "type": "function",
  "function": {
    "name": "local.search",
    "arguments": {"query": "abc"}
  }
}
```
- 响应示例（成功）
```json
{"success":true,"result":{"items":[{"title":"..."}]}}
```
- 响应示例（错误）
```json
{"success":false,"error":"message"}
```
- 响应示例（pending）
```json
{"success":false,"status":"pending","data":{"status":"pending","approval_id":"appr_123"}}
```

### 批准工具执行
- POST /mcp_hub/approve
- 请求体
```json
{"tool":"local.search","arguments":{"query":"abc"},"approval_id":"appr_123"}
```
- 响应示例
```json
{"success":true,"result":{"approved":true}}
```

### 流式调用工具（SSE）
- POST /mcp_hub/call_stream
- 请求体同 /mcp_hub/call
- 响应为 text/event-stream，示例 curl：
```bash
curl -N -H "Content-Type: application/json" -H "Accept: text/event-stream" \
  -d '{"id":"call_123","type":"function","function":{"name":"local.search","arguments":{"query":"abc"}}}' \
  http://localhost:9000/mcp_hub/call_stream
```
- 事件行以 `data: ...` 形式返回，内容可能是：
  - 标准 JSON-RPC 块：`{"success":true,"result":...}` 或 `{"success":false,"error":"..."}`；
  - 非 JSON 文本块：原样返回。

## 配置文件

支持YAML和JSON格式。

### YAML格式
```yaml
servers:
  - name: server1
    endpoint: http://host1:port/mcp
    enabled: true
    timeout: 30
  
  - name: server2
    endpoint: http://host2:port/mcp
    enabled: false
    timeout: 60
```

### JSON格式
```json
{
  "servers": [
    {
      "name": "server1",
      "endpoint": "http://host1:port/mcp",
      "enabled": true,
      "timeout": 30
    }
  ]
}
```

配置字段：
- `name`: 服务器名称，必须唯一
- `endpoint`: MCP服务器地址
- `enabled`: 是否启用，默认true
- `timeout`: 超时时间（秒），默认30

## 使用方式

### 命令行参数
```bash
python mcp_center_server.py --config config.yaml
python mcp_center_server.py -c config.json
```

### 环境变量
```bash
export MCP_CONFIG_FILE=config.yaml
python mcp_center_server.py
```

### 默认配置文件
程序自动查找：
- `mcp_servers.yaml`
- `mcp_servers.json`
- `config/mcp_servers.yaml`
- `config/mcp_servers.json`

### 无配置文件
使用默认本地服务器：
- name: "local"
- endpoint: "http://localhost:8000/mcp"

## 刷新策略
- 后台自动刷新：默认每 5 分钟检测配置变更、连接新增服务、断开禁用/移除服务，并进行健康心跳与退避重连。
- 主动刷新：调用 `POST /mcp_hub/refresh` 立即执行一次发现与连接。

## 项目结构

```
mcp_server_stub/
├── mcp_hub.py              # MCPHub核心类，聚合管理多个MCP服务器
├── mcp_center_server.py    # FastAPI服务，提供统一API接口
├── mcp_server/             # MCP服务器实现目录
│   └── mcp_server.py       # 基础MCP服务器，支持装饰器注册工具
├── model.py                # 数据模型定义
├── mcp_servers.yaml        # MCPHub配置文件（YAML格式）
├── mcp_servers.json        # MCPHub配置文件（JSON格式）
└──  CONFIG_USAGE.md         # MCPHub配置使用说明
```
