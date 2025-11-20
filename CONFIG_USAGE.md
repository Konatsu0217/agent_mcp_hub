# MCPHub - MCP服务器智能枢纽配置指南

## 🚀 功能概述

MCPHub 是你的MCP服务器智能管理中心！通过配置文件，你可以轻松管理所有MCP服务器，无需修改一行代码就能动态增减服务器。

## 📋 配置文件格式

支持两种格式：**YAML** 和 **JSON**

### YAML 格式示例 (`mcp_servers.yaml`)

```yaml
servers:
  - name: local
    endpoint: http://localhost:8000/mcp
    enabled: true
    timeout: 30

  - name: weather
    endpoint: http://localhost:8001/mcp
    enabled: true
    timeout: 30

  - name: database
    endpoint: http://localhost:8002/mcp
    enabled: false  # 禁用状态
    timeout: 60
```

### JSON 格式示例 (`mcp_servers.json`)

```json
{
  "servers": [
    {
      "name": "local",
      "endpoint": "http://localhost:8000/mcp",
      "enabled": true,
      "timeout": 30
    },
    {
      "name": "weather", 
      "endpoint": "http://localhost:8001/mcp",
      "enabled": true,
      "timeout": 30
    }
  ]
}
```

## 配置字段说明

- **name**: 服务器名称，必须唯一
- **endpoint**: MCP服务器地址
- **enabled**: 是否启用该服务器（可选，默认true）
- **timeout**: 请求超时时间，秒（可选，默认30）

## 🎯 使用方法

### 1. 命令行参数指定配置文件

```bash
# 启动MCPHub并指定配置文件
python mcp_center_server.py --config my_servers.yaml
# 或简写
python mcp_center_server.py -c my_servers.json
```

### 2. 环境变量指定配置文件

```bash
export MCP_CONFIG_FILE=my_servers.json
python mcp_center_server.py
```

### 3. 使用默认配置文件

MCPHub会自动查找以下默认配置文件：
- `mcp_servers.yaml`
- `mcp_servers.json` 
- `config/mcp_servers.yaml`
- `config/mcp_servers.json`

### 4. 无配置文件模式

如果没有找到任何配置文件，MCPHub会自动使用默认的本地MCP服务器配置：
- name: "local"
- endpoint: "http://localhost:8000/mcp"

## 动态管理服务器

### 添加新服务器
只需在配置文件中添加新的服务器配置，然后重启聚合器即可。

### 禁用/启用服务器
修改对应服务器的 `enabled` 字段：
- `enabled: true` - 启用连接
- `enabled: false` - 禁用连接

### 修改服务器配置
直接修改配置文件中的对应字段，重启后生效。

## 🔍 验证配置

启动MCPHub后，可以通过以下API查看已配置的服务器：

```bash
# 查看所有服务器状态
curl http://localhost:9000/hub/servers

# 查看所有可用工具
curl http://localhost:9000/hub/tools

# 健康检查
curl http://localhost:9000/hub/health
```

返回示例：
```json
[
  {
    "name": "local",
    "endpoint": "http://localhost:8000/mcp", 
    "healthy": true
  },
  {
    "name": "weather",
    "endpoint": "http://localhost:8001/mcp",
    "healthy": false
  }
]
```

## ⚠️ 注意事项

1. 🔄 配置文件修改后需要重启MCPHub才能生效
2. ✅ 只有 `enabled: true` 的服务器会被连接
3. 🏷️ 服务器名称必须唯一，重复名称会导致配置失败
4. 🚀 支持同时配置多个服务器，MCPHub会并行连接和发现工具
5. 📊 API路径已从 `/aggregate/*` 更新为 `/hub/*`

## 🎉 MCPHub 的优势

- **🎨 更酷的名字** - 从枯燥的 "Aggregator" 升级为时尚的 "Hub"
- **🔧 配置驱动** - 纯配置文件管理，零代码修改
- **⚡ 智能路由** - 自动工具发现和调用路由
- **💪 健壮性** - 完善的健康检查和错误处理
- **📈 可扩展** - 轻松支持更多MCP服务器