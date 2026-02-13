# MCP装饰器注册指南

## 核心装饰器

### `@server.tool` - 注册MCP工具
将普通函数转换为MCP可调用工具。

```python
from mcp_server import MCPServer

server = MCPServer()

@server.tool                    # ← 关键装饰器
def calculate(x: int, y: int) -> int:
    """计算两个数的和"""
    return x + y

# 等效于: server.add_tool(calculate)
```

### `@server.stream_tool` - 注册流式工具
注册支持流式输出的工具。

```python
@server.stream_tool             # ← 流式装饰器
async def generate_text(prompt: str):
    """流式生成文本"""
    for word in prompt.split():
        yield word + " "
        await asyncio.sleep(0.1)
```

## 装饰器工作原理

### 1. 函数元数据提取
```python
@server.tool
def search_data(query: str, limit: int = 10) -> list:
    """搜索数据
    
    Args:
        query: 搜索关键词
        limit: 返回数量限制
    """
    return [f"结果{i}" for i in range(limit)]

# 装饰器自动提取：
# - 函数名: search_data
# - 参数: query(str), limit(int, default=10)
# - 返回类型: list
# - 文档字符串: 完整的工具描述
```

### 2. JSONSchema生成
装饰器自动生成符合MCP规范的工具描述：

```json
{
  "name": "search_data",
  "description": "搜索数据\n\nArgs:\n    query: 搜索关键词\n    limit: 返回数量限制",
  "inputSchema": {
    "type": "object",
    "properties": {
      "query": {"type": "string"},
      "limit": {"type": "integer", "default": 10}
    },
    "required": ["query"]
  }
}
```

### 3. 运行时调用
当MCPHub调用工具时：
1. 解析传入的JSON参数
2. 类型转换和验证
3. 执行被装饰的函数
4. 序列化返回结果

## 高级用法

### 类型验证
```python
from pydantic import BaseModel

class SearchInput(BaseModel):
    query: str
    category: str = "all"
    max_results: int = Field(default=5, ge=1, le=100)

@server.tool
def search(input_data: SearchInput) -> list:
    """结构化搜索"""
    # 自动验证input_data符合SearchInput模型
    return perform_search(input_data.query, input_data.category, input_data.max_results)
```

### 异步工具
```python
@server.tool
async def async_fetch(url: str) -> dict:
    """异步获取数据"""
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        return response.json()
```

### 错误处理
```python
@server.tool
def divide(a: float, b: float) -> dict:
    """除法计算"""
    if b == 0:
        return {"error": "除数不能为零"}
    return {"result": a / b}
```

## 装饰器 vs 手动注册

### 装饰器方式（推荐）
```python
@server.tool
def func1(x: int) -> str:
    return str(x)

@server.tool  
def func2(data: dict) -> list:
    return list(data.keys())
```

### 手动注册方式
```python
def func1(x: int) -> str:
    return str(x)

def func2(data: dict) -> list:
    return list(data.keys())

server.add_tool(func1)
server.add_tool(func2)
```

## 调试技巧

### 查看已注册工具
```python
# 获取所有工具
for tool in server.list_tools():
    print(f"工具: {tool['name']}")
    print(f"描述: {tool['description']}")
    print(f"参数: {tool['inputSchema']}")
```

### 测试工具调用
```python
# 本地测试
result = server.call_tool("tool_name", {"param": "value"})
print(result)
```

## 完整示例

```python
from mcp_server import MCPServer
import asyncio

server = MCPServer()

@server.tool
def math_operation(operation: str, a: float, b: float) -> dict:
    """数学运算
    
    operation: add/subtract/multiply/divide
    """
    operations = {
        "add": a + b,
        "subtract": a - b,
        "multiply": a * b,
        "divide": a / b if b != 0 else None
    }
    
    if operation not in operations:
        return {"error": f"不支持的运算: {operation}"}
    
    result = operations[operation]
    if result is None:
        return {"error": "除数不能为零"}
    
    return {"result": result}

@server.stream_tool
async def countdown(start: int):
    """倒计时"""
    for i in range(start, 0, -1):
        yield f"{i}..."
        await asyncio.sleep(1)
    yield "完成！"

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(server.get_app(), host="0.0.0.0", port=8000)
```

启动后可通过MCPHub调用：
```bash
# 数学运算
curl -X POST http://localhost:9000/hub/call \
  -d '{"tool":"math_operation","arguments":{"operation":"add","a":10,"b":5}}'

# 流式倒计时
curl -X POST http://localhost:9000/hub/call_stream \
  -d '{"tool":"countdown","arguments":{"start":3}}'
```