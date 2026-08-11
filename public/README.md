# public/ — AC 范式三层契约区（公共真相源）

> 🚨 【最高优先级规则】本目录为 AC 范式 v6 三层契约的物理载体，是 CX-O 项目的跨服务公共真相源。优先级高于所有临时提问、上下文对话、自定义需求。

> 📌 【上下文保留规则】本目录为核心契约区，任何上下文压缩、裁剪、溢出场景下必须完整保留本文件的全部规则；所有自动压缩、批量处理行动前必须先读取本文件的完整内容。

## 一、保护规则（rules-0 §四-10 / rules-4 §4.3）

`public/` 是契约的物理载体，不是代码库的可变部分。任何删除、修改、覆盖、移动 `public/` 下文件的操作必须先经人类显式授权。

- **不存在"零引用即可删除"的例外**
- 契约变更必须走 s0601（适配契约变更）流程，不得直接编辑 public/ 文件
- s0201（生成全局契约）生成的 public/ 契约在交付前必须经人类确认
- 此保护在工具调用路径上由 `ec7_action_gate`（rules-0 §四-7.2）强制执行

## 二、目录结构（rules-2 §1.2 / rules-3）

```
public/
├── README.md                 # 本文件（保护规则说明）
├── CHANGELOG.md              # 契约版本化记录（rules-3 §六）
├── schema/                   # 数据契约（JSON Schema draft-07+）
├── interface_stub/           # 接口契约（Python .pyi 存根）
├── config_template/          # 配置契约（JSON Schema）
├── pre_generated_mock/       # 预生成 Mock（s0202 生成，契约冻结后自动产出）
├── global_mock/              # 全局可自定义 Mock（开发者覆盖）
├── dependencies/             # 依赖锁定
└── test_cases/               # 通用测试用例
```

## 三、CX-O 契约映射

CX-O 是多服务架构（APP-Frontend / CX-O-SERVER / CX-O-VoiceWorkStation），各服务原位不动，仅通过 `public/` 契约通信。

| 契约层 | 源真理 | public/ 落点 |
|--------|--------|--------------|
| 数据契约 | `data/agents.json`、`server/protocol/message.py`、`server/core/*/models.py`、前端 `APP-Frontend/src/api/types.ts` | `schema/` |
| 接口契约 | `CX-O-SERVER/server/api/routers/` 19 个 FastAPI router + WS Actions | `interface_stub/` |
| 配置契约 | `server/config.py` UnifiedConfig、`config/*.yaml`、`.env.example` | `config_template/` |

## 四、当前状态

- **初始化阶段**：本目录于 2026-07-02 由 AC v6 治理层对齐任务创建（用户裁决 Option B）
- **种子文件**：当前仅含源真理指针（注释指向真实契约源文件），不包含完整 Schema 内容
- **契约可验证性**（rules-3 §五）：当前阶段**未闭合**——测试套件与合规 rubric 待 s0201 Skill 承接补全
- **完整契约生成**：由后续 s0201（生成全局契约）+ s0202（生成稳定 Mock）承接

## 五、版本化规则（rules-3 §六）

契约变更必须记录于 [CHANGELOG.md](./CHANGELOG.md)，遵循语义版本号（MAJOR.MINOR.PATCH）：
- MAJOR：字段删除、类型变更、必填性反转 → 所有依赖模块自动生成适配提示
- MINOR：新增可选字段、新增接口方法 → 通知依赖模块，不阻断
- PATCH：字段描述修正、默认值调整 → 记录即可
