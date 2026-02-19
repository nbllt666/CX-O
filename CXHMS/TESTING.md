# CXHMS 测试文档

## 测试架构概览

本项目包含完整的测试套件，覆盖前端和后端的所有主要功能。

## 前端测试

### 测试框架
- **Vitest**: 单元测试框架
- **jsdom**: DOM 测试环境
- **@testing-library/jest-dom**: DOM 断言库

### 测试文件

| 文件 | 描述 |
|------|------|
| `frontend/src/lib/utils.test.ts` | 工具函数测试 |
| `frontend/src/store/chatStore.test.ts` | 聊天状态管理测试 |
| `frontend/src/store/themeStore.test.ts` | 主题状态管理测试 |
| `frontend/src/api/client.test.ts` | API 客户端测试 |

### 运行前端测试

```bash
cd frontend

# 安装依赖
npm install

# 运行测试
npm test

# 监视模式
npm run test:watch

# 生成覆盖率报告
npm run test:coverage
```

## 后端测试

### 测试框架
- **pytest**: Python 测试框架
- **pytest-asyncio**: 异步测试支持
- **FastAPI TestClient**: API 测试客户端

### 测试结构

```
backend/tests/
├── conftest.py              # 测试配置和 fixtures
├── test_api/                # API 端点测试
│   ├── test_health.py       # 健康检查测试
│   ├── test_chat.py         # 聊天 API 测试
│   ├── test_agents.py       # Agent API 测试
│   └── test_memory.py       # 记忆 API 测试
├── test_core/               # 核心模块单元测试
│   ├── test_memory_manager.py
│   └── test_llm_client.py
└── test_integration/        # 集成测试
    └── test_chat_flow.py
```

### 运行后端测试

```bash
# 运行所有测试
python -m pytest backend/tests -v

# 运行特定模块
python -m pytest backend/tests/test_api -v
python -m pytest backend/tests/test_core -v
python -m pytest backend/tests/test_integration -v

# 生成覆盖率报告
python -m pytest backend/tests --cov=backend --cov-report=html

# 使用 pytest.ini 配置
python -m pytest
```

## 统一测试运行器

使用 `run_tests.py` 运行所有测试：

```bash
# 运行所有测试
python run_tests.py

# 只运行前端测试
python run_tests.py --frontend-only

# 只运行后端测试
python run_tests.py --backend-only

# 带覆盖率报告
python run_tests.py --coverage

# 运行特定测试
python run_tests.py --test backend/tests/test_api/test_health.py
```

## 测试覆盖范围

### 前端测试覆盖

1. **工具函数** (`utils.test.ts`)
   - `cn()` - Tailwind 类名合并
   - `formatDate()` - 日期格式化
   - `formatRelativeTime()` - 相对时间格式化
   - `truncateText()` - 文本截断
   - `getImportanceColor()` - 重要性颜色
   - `getImportanceLabel()` - 重要性标签

2. **状态管理** (`chatStore.test.ts`, `themeStore.test.ts`)
   - 初始状态验证
   - 状态更新操作
   - 异步操作
   - 错误处理
   - 本地存储持久化

3. **API 客户端** (`client.test.ts`)
   - 健康检查
   - 聊天 API
   - Agent API
   - 记忆 API
   - 错误处理

### 后端测试覆盖

1. **API 测试** (`test_api/`)
   - 健康检查端点
   - 聊天端点 (发送消息、流式响应、历史记录)
   - Agent 端点 (CRUD 操作)
   - 记忆端点 (CRUD、搜索、统计)
   - 参数验证
   - 错误处理

2. **核心模块测试** (`test_core/`)
   - 记忆管理器 (添加、获取、更新、删除)
   - 会话管理
   - Agent 管理
   - LLM 客户端
   - 嵌入生成

3. **集成测试** (`test_integration/`)
   - 端到端聊天流程
   - 多端点协调
   - API 文档访问

## 测试配置

### 前端配置 (`vitest.config.ts`)

```typescript
export default defineConfig({
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html']
    }
  }
})
```

### 后端配置 (`pytest.ini`)

```ini
[pytest]
testpaths = backend/tests
python_files = test_*.py
addopts = -v --tb=short --strict-markers
markers =
    unit: Unit tests
    integration: Integration tests
    api: API tests
```

## 编写新测试

### 前端测试示例

```typescript
import { describe, it, expect } from 'vitest'
import { myFunction } from './myModule'

describe('MyModule', () => {
  it('should do something', () => {
    const result = myFunction()
    expect(result).toBe('expected')
  })
})
```

### 后端测试示例

```python
import pytest
from fastapi.testclient import TestClient

def test_my_endpoint(client: TestClient):
    """Test my endpoint."""
    response = client.get("/api/my-endpoint")
    assert response.status_code == 200
    data = response.json()
    assert "expected_field" in data
```

## 持续集成建议

在 CI/CD 管道中运行测试：

```yaml
# .github/workflows/test.yml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.10'
      
      - name: Setup Node
        uses: actions/setup-node@v3
        with:
          node-version: '18'
      
      - name: Run all tests
        run: python run_tests.py
```

## 测试状态

- ✅ 前端测试: 4 个测试文件
- ✅ 后端 API 测试: 30 个测试用例
- ✅ 后端单元测试: 2 个测试文件
- ✅ 集成测试: 1 个测试文件

总计: **30+ 测试用例** 覆盖所有主要功能模块
