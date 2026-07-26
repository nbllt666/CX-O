# AGENTS.md — audioWorkstation 作曲区模块级规则（作曲界面五线谱重构 S4 生效）

> 🚨 【最高优先级规则】本文件为本目录开发的强制约束，优先级高于所有临时提问、上下文对话、自定义需求，所有输出必须 100% 符合本文件要求，违反规则的内容必须自动修正后再输出。

> 📌 【上下文保留规则】本文件为核心规则文件，任何上下文压缩、裁剪、溢出场景下必须完整保留本文件的全部内容，不得删减、忽略本文件的任何规则；所有自动压缩、批量处理行动前必须先读取本文件的完整内容。

## 一、规则定位

本文件为**模块级 AGENTS.md**（rules-4 §三），绑定 spec `redesign-composition-staff-editor` 前端模块 6–7 的开发边界，与全局 `c:\CX-O\AGENTS.md` 及 `.trae/rules/rules-0~7.md` 共同生效。

## 二、AC 范式通用约束（rules-4 §4.3）

```yaml
prohibitions:
  - 禁止删除、修改、覆盖、移动 CX-O 根 public/ 目录下的任何内容
  - 禁止跨服务直接导入后端实现代码（不得 import CX-O-VoiceWorkStation 任何产物）
  - 禁止写入不符合数据契约的数据（歌谱 v2 / 命令协议以冻结契约为准）
  - 禁止旁路状态：任何编辑动作不得直接改渲染数据，必须经命令分发层

binding_rules:
  - 契约唯一真相源 = .trae/specs/redesign-composition-staff-editor/contracts/（已冻结）
  - 歌谱/命令的 TS 类型由冻结 JSON Schema 生成或经 CXFC /tools parameters 运行时获取，不手写漂移副本
  - 服务端为歌谱草稿唯一真源；前端为受控渲染 + 命令产生器
```

## 三、本 spec 开发边界

### 3.1 可修改范围

| 模块 | 路径 | 性质 |
|------|------|------|
| 模块6_五线谱渲染层 | `src/pages/audioWorkstation/staff/`（新增 StaffScore 组件族） | 新建 |
| 模块7_作曲交互面板 | `src/pages/audioWorkstation/CompositionPanel.tsx`（重构）+ 同目录交互/面板子组件 | 重构 |
| 测试 | 对应 `*.test.tsx` / `__tests__/`（vitest + testing-library） | 随模块产出 |

新增依赖：`vexflow`（需写入 package.json，属本 spec 授权范围）。

### 3.2 架构要点（merged.md §6 冻结）

- **StaffScore 受控纯渲染**：props=服务端快照（v2 歌谱），不持有编辑状态；快照变化全量重建 VexFlow；总谱纵向堆叠（主旋律置顶：歌词下排+和弦标记上排；伴奏谱表依次；`program=-1` 轨用打击乐谱号）
- **命令分发层** `dispatch(command, args)`：统一走 REST `POST /drafts/{id}/commands`；携带本地 latest version，响应 version 更旧则丢弃
- **交互→命令映射**：点击空白→add_note（坐标反解拍位+音高）；选中→属性面板 update_note/set_lyric；拖拽→本地虚影（零请求）→松手一次 move_note；歌词双击行内编辑→blur/Enter 提交 set_lyric
- **防抖**：连续微调（音量/声像滑杆）300ms 合并为一次 set_track_mix
- **轨道面板**：左侧轨列表（增/删/排序）、GM 16 组×8 音色分组选择器（打击乐 program=-1）、auto/manual 切换+节奏型下拉、音量/声像滑杆——全部经命令分发层

### 3.3 测试与合规

- vitest + testing-library：命令分发层（version 乱序丢弃、防抖合并）、交互→命令映射、轨道面板操作；VexFlow 渲染层快照 fixture 冒烟（jsdom SVG 存在性）
- **本目录 UI 变更必须通过 s0402 前端三重测试闸门**（单测→E2E→Mock 回归，顺序固定不跳关）
- E2E 双路径（Playwright）：人类路径=create_draft→编辑→submit→轮询→audio_url；agent 路径=经 CXFC /call music_edit_score 命令序列

### 3.4 失败回退

模块6 失败回退至 模块0+s0202 Mock 完成点；模块7 失败回退至 模块4（REST）+模块6 完成点（tasks.md §3）。

## 四、参考锚点

- 需求/裁决：`c:\CX-O\.trae\specs\redesign-composition-staff-editor\spec.md`
- 编排/台账：`c:\CX-O\.trae\specs\redesign-composition-staff-editor\tasks.md`
- 冻结契约：`c:\CX-O\.trae\specs\redesign-composition-staff-editor\contracts\`
- s0202 Mock（前端并行开发支点）：随 S4 批次A 产出，位置见 tasks.md §6
