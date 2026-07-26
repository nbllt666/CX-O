# staff/__mocks__ — s0202 预生成 Mock（前后端并行开发支点）

> 本目录为 `redesign-composition-staff-editor` spec 的 s0202 交付物：在后端模块3（draft_registry）就绪前，为前端模块6/7 提供可独立开发的 Mock 依赖。

## 文件清单

| 文件 | 来源 | 说明 |
|------|------|------|
| `types.ts` | **生成** | 歌谱 v2 / 命令协议 / 音乐枚举清单的 TS 类型，由 `scripts/gen_music_types.py` 从后端 JSON Schema 生成 |
| `fixtures.ts` | **生成** | 5 组歌谱夹具（v2×3 + v1×2），由 `gen_music_types.py` 从 `tests/fixtures/score_fixtures.json` 生成 |
| `inventory.ts` | **生成** | GM 128 音色 / 4 节奏型 / 10 鼓键映射，由 `gen_music_types.py` 从 `workstation/music/inventory.py` 生成 |
| `mockDraftBackend.ts` | **手写** | 20 命令 Mock 执行器，模拟后端 draft_registry + validate_score + arranger 外部行为 |
| `mockDraftBackend.smoke.test.ts` | **手写** | vitest 冒烟测试：20 命令全路径 + 异常路径 + 版本/快照一致性 |
| `README.md` | **手写** | 本文件 |

## 生成物再生成

```bash
cd CX-O-Frontend
python scripts/gen_music_types.py
```

再生成条件（满足其一即应执行）：
- `contracts/score-v2.schema.json` 版本变更
- `contracts/command-protocol.schema.json` 版本变更
- `contracts/music-inventory.schema.json` 版本变更
- `CX-O-VoiceWorkStation/tests/fixtures/score_fixtures.json` 内容变更
- `CX-O-VoiceWorkStation/workstation/music/inventory.py` 内容变更

## Mock 与真实后端的差异（Mock 简化声明）

以下差异已登记，真实后端就绪后以其为准：

| # | 差异 | 影响 |
|---|------|------|
| 1 | `validateScore` 为契约子集的手写校验（非 jsonschema 全量） | 错误文本格式对齐后端但不逐字一致；前端开发时以 `ok`/`errors` 结构为准 |
| 2 | `undo/redo` 栈记录整谱快照（后端记录逆操作 before 片段） | 外部行为等价，内存占用略高（Mock 场景可忽略） |
| 3 | `arrangeEvents` 为 mock 级确定性编排（三和弦简化解析、无视 time_signature） | 生成事件数量/音高可能与真实 arranger 不同，仅保证"同输入同输出" |
| 4 | 纯内存注册表，无落盘 / TTL 清扫 / REST 传输层 | `draft_id` 为 `draft_N` 自增，刷新页面后草稿丢失 |
| 5 | `changed_paths` 恒为 `["$"]` | 契约允许首版返回全谱路径标记，前端按全量重渲染处理即可 |

## 使用方式

```typescript
import { createMockDraftBackend } from './__mocks__/mockDraftBackend';
import { getFixture } from './__mocks__/fixtures';

// 创建 Mock 实例
const backend = createMockDraftBackend();

// 以夹具为种子创建草稿
const result = backend.seedFromFixture('full_multitrack_v2');
if (result.success) {
  console.log(result.snapshot); // ScoreV2 完整快照
}

// 执行命令
const addResult = backend.execute({
  command: 'add_note',
  args: { draft_id: result.draft_id!, track: 'melody', pitch: 'D4', beats: 2, lyric: '你' },
});
```

## 验证

```bash
cd CX-O-Frontend
npm run typecheck   # tsc --noEmit
npm run test        # vitest run（含本目录冒烟测试）
```

## 契约锚点

- `contracts/score-v2.schema.json`：歌谱 v2 形状、v1→v2 迁移规则、轨 id 唯一性
- `contracts/command-protocol.schema.json`：20 命令分发、command_result 形状、10 错误码
- `contracts/music-inventory.schema.json`：音色/节奏型/鼓键枚举
- `contracts/README.md` §4：note_id 轨内序号寻址、空白草稿 C4 占位语义
