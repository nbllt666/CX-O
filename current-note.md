# current-note.md — 当前工作交接锚点

> 本文件为跨断面状态接力锚点，按 rules-5 §三 note 写作元原则维护。

## 做到哪了

- **fix-vrm-config-live-apply**（上一 spec）：核心修复已完成，变更文档已归档
- **fix-vrm-animation-wind-idle**（当前 spec）：全部 6 个 Task 已完成
  - Task 1: settingsStore 扩展 swayAmplitude/swayFrequency ✅
  - Task 2: VRMViewer 风场实例化 + idleAnimation 响应 + ResizeObserver ✅
  - Task 3: AvatarManager 动画标签页新增 sway 滑块 ✅
  - Task 4: VRMPanel 传递 idleAnimation + windConfig props ✅
  - Task 5: typecheck 零错误 + Playwright 验证通过 ✅
  - Task 6: 变更文档已归档 ✅
- **第一轮回退修复**（布局 + merge）：已完成
  - VRMPanel 根 div 加 h-full + AvatarPanel h-full → self-stretch ✅
  - settingsStore persist merge 函数深度合并 animation/wind ✅
  - canvas 高度 150px→613px, swayFrequency 0→0.5 ✅
- **第二轮回退修复**（stale closure + 动画优化）：已完成
  - VRMViewer 去掉 effectiveAnim ref，ac 直接从 animationConfig prop 计算 ✅
  - VRMAnimation updateSway 加入 spine 反向旋转 + head 同向旋转 ✅
  - VRMAnimation updateBreathing 加入 spine X 轴旋转 ✅
  - settingsStore swayAmplitude 默认值 0.01→0.02 ✅
  - AvatarManager sway 滑块 max 0.1→0.05 ✅
  - typecheck 零错误 + Playwright 参数验证通过 ✅
- **第三轮回退修复**（T-Pose + 动画幅度）：已完成
  - VRMViewer 初始骨骼旋转值增大（leftUpperArm Z 0.3→1.2 手臂自然下垂 + 前臂向内收弯曲 + 腿部微调）✅
  - settingsStore swayAmplitude 0.02→0.04, breathAmplitude 0.02→0.03 ✅
  - localStorage 重置 swayAmplitude=0.04, breathAmplitude=0.03, breathFrequency=0.3 ✅
  - typecheck 零错误 + Playwright 验证通过 ✅
- **第四轮回退修复**（THREE.Timer.update() 缺失）：已完成
  - VRMViewer animate loop 在 getDelta() 前添加 clockRef.current.update() ✅
  - 修复前 dt=0 动画完全无效 → 修复后 time=15.097, dt=1.0098, hipsRot.z=-0.012（Playwright 验证）✅
  - 清理临时调试代码 window.__vrmDebug ✅
  - typecheck 零错误 ✅
- **第五轮回退修复**（VTube Studio 风格 + 自由度 + Live2D 待机动画）：已完成
  - settingsStore AnimationSettings 新增 swayIrregularity/breathIrregularity/headIdleRange ✅
  - VRMAnimation 重写：双频率叠加+random walk+多骨骼协同+空闲头部漂移 ✅
  - VRMViewer 姿势调整为自然 A-Pose（leftUpperArm Z 1.2→0.9）✅
  - live2dEngine 新增待机动画（ParamBreath/ParamBodyAngle/ParamEyeLOpen）✅
  - Live2DViewer 接入 animationConfig ✅
  - AvatarManager UI 新增 3 个滑块 + Live2D 动画参数 ✅
  - typecheck 零错误 + localStorage 参数验证通过 ✅
- **第六轮回退修复**（手臂下垂 + 预览匹配 + 空闲微表情）：已完成
  - VRMViewer 手臂角度 leftUpperArm Z 1.05→1.4（完全下垂）✅
  - VRMViewer acRef/tcRef 修复 stale closure（loadModel 使用 ref.current 而非闭包值）✅
  - AvatarManager 新增 animConfig 同步 useEffect（store animation → local state）✅
  - VRMExpression 新增 applyIdleMicroExpressions（基线 relaxed + 噪声微微笑 + 偶尔惊讶）✅
  - settingsStore 新增 idleExpressionIntensity（默认 0.1）✅
  - AvatarManager 表情标签页新增空闲微表情滑块 ✅
  - typecheck 零错误 ✅
- **第七轮微调修复**（手臂穿模）：已完成
  - VRMViewer 手臂角度 leftUpperArm Z 1.4→1.2（69°，不贴躯干避免穿模）✅
  - VRMViewer 前臂 leftLowerArm Y -0.3→-0.2, Z 0.15→0.1（弯曲减小）✅
  - typecheck 零错误 ✅
- **第八轮微调修复**（跟踪方向+限位+眼跟踪）：已完成
  - VRMAnimation pitch 符号修复（-asin → asin，修正上下反转）✅
  - settingsStore 新增 headTrackingLimit（默认 0.5 rad）+ eyeTrackingEnabled（默认 true）✅
  - VRMAnimation 限位改为可调（pitch 按 limit，yaw 按 limit*1.6）✅
  - VRMViewer loadModel 主动创建 lookAt target 并加入场景（修复眼球不跟踪）✅
  - VRMViewer mousemove 支持 eyeTrackingEnabled 开关 + 关闭时重置 headTarget ✅
  - AvatarManager 新增"跟踪限位"滑块 + "眼球跟踪"开关 ✅
  - typecheck 零错误 ✅
- **第九轮微调修复**（视线开关+眼球归位+配置应用+自动保存）：已完成
  - AvatarManager 预览 VRMViewer 补全 lookAtMouse/idleAnimation/lipSyncEnabled props（修复视线开关无效+配置不自动应用）✅
  - VRMViewer 新增 useEffect：eyeTrackingEnabled 为 false 时重置 lookAt target 到中性位置（修复眼球不归位）✅
  - settingsStore 新增 autoSave（默认 true）+ setAutoSave，纳入 partialize/merge 持久化 ✅
  - AvatarManager handleXxxChange 尊重 autoSave（false 时只更新 local state）✅
  - AvatarManager 新增 handleManualSave（批量 flush local state 到 store）✅
  - AvatarManager 底部新增"自动保存"toggle + "保存当前配置"按钮 UI ✅
  - typecheck 零错误 ✅

## 为什么

用户在上一 spec 修复后实测反馈 5 类问题（动画优化/风场要能调/待机动作要调/不少选项不生效/窗口自适应差），明确选择"创建新 spec 逐一处理"。

排查结论：
1. **风场不生效**：VRMViewer.tsx 完全没导入 VRMWindField，animate loop 未调用 windField.update()
2. **idleAnimation 不生效**：store 有字段但未传给 VRMViewer，VRMViewer 无条件运行动画
3. **sway 无 UI**：AnimationSettings 缺 swayAmplitude/swayFrequency 字段
4. **窗口自适应差**：VRMViewer 只监听 window resize，无 ResizeObserver，拖拽面板宽度不触发 canvas 重算
5. **"不少选项不生效"**：上述 4 类的汇总表现

## 未闭合项

| 项 | 性质 | 状态 |
|----|------|------|
| Task 1~6 代码实施 | 已完成 | ✅ 全部闭合 |
| typecheck + Playwright 验证 | 已完成 | ✅ 零错误 + 数据流验证通过 |
| 变更文档 | 已归档 | ✅ status="已完成"（含五回退修复追加） |
| 第一轮回退修复（布局+merge） | 已完成 | ✅ canvas 150px→613px, swayFreq 0→0.5 |
| 第二轮回退修复（stale closure+动画优化） | 已完成 | ✅ typecheck 零错误 + Playwright 参数验证通过 |
| 第三轮回退修复（T-Pose+动画幅度） | 已完成 | ✅ typecheck 零错误 + Playwright 验证通过 |
| 第四轮回退修复（THREE.Timer.update 缺失） | 已完成 | ✅ dt=0→dt=1.0098，动画运行（Playwright 验证） |
| 第五轮回退修复（VTube风格+自由度+Live2D） | 已完成 | ✅ typecheck 零错误 + 参数验证通过 |
| 第六轮回退修复（手臂下垂+预览匹配+微表情） | 已完成 | ✅ typecheck 零错误 |
| 第七轮微调修复（手臂穿模） | 已完成 | ✅ typecheck 零错误 |
| 第八轮微调修复（跟踪方向+限位+眼跟踪） | 已完成 | ✅ typecheck 零错误 |
| 第九轮微调修复（视线开关+眼球归位+配置应用+自动保存） | 已完成 | ✅ typecheck 零错误 |
| VRM+Live2D 动画自然度确认 | 阻断交付 | ⏳ 待用户重新确认（第九轮微调后） |
| GN-004 交付前最终审查 | 已通过 | ✅ PASS（第九轮微调后需复审） |

## 接续入口

- **当前断点**：第九轮微调修复已完成（视线开关 + 眼球归位 + 配置自动应用 + 自动保存/手动保存），typecheck 零错误，待用户重新确认
- **确认通过后**：GN-004 复审第九轮微调 → 交付完成 → note 标注"吸收完毕"
- **回退点**：若人类仍反馈视线开关/眼球归位/配置应用/自动保存问题，继续调整预览 props 传递/lookAt target 重置逻辑/autoSave 缓冲机制

---

## 阅读记录（事实摘录）

### 2026-07-08 排查记录

- VRMViewer.tsx grep `wind|Wind`：只返回 mousemove/resize，无 VRMWindField 引用
- VRMViewer.tsx grep `idleAnimation|VRMAnimation|animationRef`：VRMAnimation 已导入使用，但 idleAnimation 未作为 prop
- VRMAnimation.ts：IdleConfig 含 swayAmplitude/swayFrequency，但 VRMAnimation.setConfig 只接收 Partial<IdleConfig>
- settingsStore.ts：AnimationSettings 接口不含 swayAmplitude/swayFrequency；VRMSettings 含 idleAnimation（默认 true）和 wind（VRMWindConfig）
- VRMEngine.ts resizeRuntime：调用 fitVRMModel，后者正确执行 renderer.setSize + camera.aspect 更新
- VRMViewer.tsx resize useEffect：只 `window.addEventListener('resize', h)`，无 ResizeObserver

## 诊断草稿（L1 静默记录层）

### 根因判定

1. 风场：渲染层缺失（VRMViewer 未消费 VRMWindField）
2. idleAnimation：prop 传递缺失 + 渲染层无条件执行
3. sway：数据层缺失（store 无字段）+ UI 层缺失（无滑块）
4. 窗口自适应：触发时机缺失（无 ResizeObserver）

### 修复策略

- 数据层→UI层→渲染层→传递层 顺序补齐
- Task 1/2/3 可并行（不同文件），Task 4 依赖 1/2 接口，Task 5/6 串行

## 审查记录

### 2026-07-08 GN-004 独立审查（spec 交付前闸门）

- **审查 agent id**：89ab57c5-59af-4d49-bac2-bf052a67765e
- **总判定**：警示放行（CAUTION-PASS）
- **硬性红线**：全部通过
- **SOFT_BLOCK**：无
- **根因真实性**：4 类根因全部经源码逐行核对，零推测性根因

**4 个非阻断观察项（已处理）**：

| 编号 | 内容 | 处理 |
|------|------|------|
| OBS-A | spec §五(2) 交接状态用"未开始"非三值标记 | ✅ 已修正为"未闭合" |
| OBS-B | reset() 不复位骨骼变换，方案"复位骨骼"描述与实现不符 | ✅ 已在 tasks.md Task 2 §3.2 补充实施提示（二选一方案） |
| OBS-C | [P]A 组 3 任务超并行上限，但实为主线程串行 | ✅ 已在 tasks.md 补注"[P]仅表示无文件冲突" |
| OBS-D | Task 5 风动视觉验证依赖测试模型 springBone | ✅ 已在 tasks.md Task 5 补注选模型要求 |

**未独立验证项**（GN-004 声明）：
- Task 5 Playwright 自动化验证可行性（未实际运行）
- VRM 模型加载运行时行为（基于静态分析）
- reset() 骨骼残留的视觉影响程度（基于源码推断）

### 2026-07-08 GN-004 交付前最终审查（PASS）

- **审查 agent id**：3f376aa6-fac7-4567-a56e-d0da078b4847
- **总判定**：通过（PASS）
- **审查范围**：独立读取 spec 三件套、变更文档 `20260708_模块0_修复VRM风场待机动画自适应.md`、current-note.md、4 个源文件原文（settingsStore.ts / VRMViewer.tsx / AvatarManager.tsx / VRMPanel.tsx）；独立运行 typecheck（零错误）；检查 git status

**5 个 rubric 项全部 PASS**：

| Rubric 项 | 结论 |
|-----------|------|
| Task 闭合真实性 | PASS — checklist 未勾选项诚实标记（VRM 视觉响应、最终闭合判据），无假闭合 |
| 变更文档完整性 | PASS — frontmatter 元数据完整 + 四章节齐全 + status="已完成"且有验证结果 |
| note 交接状态 | PASS — 三段交接结构完整，状态使用三值标记 |
| 代码质量 | PASS — typecheck 零错误，无 lint 警告，代码风格一致 |
| 影响面安全性 | PASS — 修改仅限 4 个前端文件，不涉及 public/ 契约/后端，无跨模块污染 |

**2 个非阻断观察项**：

| 编号 | 内容 | 处理 |
|------|------|------|
| OBS-Final-1 | ResizeObserver useEffect 依赖 `[]`，首次挂载时 canvasRef.current.parentElement 可能尚未就绪（边缘情况） | 已有 window resize 兜底 + `h()` 初始触发，低风险；可选优化：在 requestAnimationFrame 回调中延迟创建 ro |
| OBS-Final-2 | VRM 3D 视觉响应未独立验证（typecheck 和 Playwright 仅验证代码正确性和数据流，未验证 3D 渲染行为） | 须人类在浏览器中用含 springBone 的 VRM 测试模型确认 4 项视觉效果 |

**3 个未独立验证项**（GN-004 声明，基于执行者自述）：
- Playwright store 数据流验证（基于执行者自述，未独立运行）
- VRM 3D 视觉响应（风动/骨骼复位/摇摆/canvas 自适应）
- VRMWindField 运行时行为（基于静态代码分析）

**GN-004 后续要求**：
1. 须人类确认 VRM 3D 视觉响应（4 项视觉效果）
2. 主线程须更新 note 写入本次审查结论 ✅ 本次编辑已完成
3. 低风险观察项可选优化

## 终态处理

- 本 note 在 spec 全部 Task 闭合 + 变更文档归档后标注"吸收完毕"

---

## 阻断回退记录（2026-07-08 人类反馈）

### 用户反馈

- **反馈内容**：VRM 3D 视觉响应确认结果 = "部分效果异常"，补充说明"动画面板完全无效"
- **性质**：阻断交付 — spec 预期视觉效果正常，实际动画面板完全无效
- **影响**：GN-004 已通过但交付无法闭合，需回退排查

### 排查与修复

**根因 1：VRM 面板高度严重不足（布局 bug）**
- VRMPanel 根 div 缺少 h-full → 面板高度只有 208px（内容撑开）
- AvatarPanel 的 h-full 在 flex 布局中不生效 → 需要改用 self-stretch
- canvas 只有 150px（默认高度）→ VRM 模型几乎不可见
- **修复**：VRMPanel.tsx 根 div 加 h-full + AvatarPanel.tsx h-full → self-stretch
- **验证**：canvas 高度从 150px → 613px ✅

**根因 2：swayFrequency=0（localStorage 旧数据）**
- persist 旧数据中 swayFrequency=0，导致摇摆完全不工作
- Zustand persist 默认浅合并未正确填充新字段默认值
- **修复**：settingsStore.ts 添加 merge 函数深度合并 animation/wind + 手动重置 swayFrequency=0.5
- **验证**：swayFrequency 从 0 → 0.5 ✅

**根因 3（排除）：canvas 未渲染内容**
- readPixels 全 0 是因为 WebGLRenderer 未设置 preserveDrawingBuffer（正常行为）
- 不是模型未加载的证据

### 修复状态（第一轮）

- ✅ VRMPanel.tsx 根 div 加 h-full
- ✅ AvatarPanel.tsx h-full → self-stretch
- ✅ settingsStore.ts persist merge 函数
- ✅ typecheck 零错误
- ✅ canvas 高度 613px（Playwright 验证）
- ✅ swayFrequency=0.5（Playwright 验证）
- ⏳ VRM 模型视觉响应待用户重新确认

---

## 第二轮阻断回退记录（2026-07-08 用户二次反馈）

### 用户反馈

- **反馈内容**：第一轮回退修复后用户重新验证，反馈两个问题：
  1. "配置界面没有实时更新" — AvatarManager 参数修改未实时反映到 VRM 模型
  2. "待机动作太不自然了" — 待机动画效果僵硬
- **性质**：阻断交付 — 第一轮回退修复解决了布局和 merge 问题，但暴露出 VRMViewer 的 stale closure bug 和动画自然度问题
- **影响**：GN-004 已通过但交付仍无法闭合，需进行第二轮回退排查

### 排查与修复

**根因 4：VRMViewer 的 effectiveAnim ref 导致 stale closure**
- VRMViewer.tsx 使用 `effectiveAnim` ref 存储 animationConfig
- ref 更新不触发重新渲染，导致 `ac` 始终是旧值
- animationConfig useEffect 的依赖项（ac.swayAmplitude 等）永远不会变化
- 结果：AvatarManager 调整参数后，VRMAnimation.setConfig 永远不会被重新调用
- **修复**：去掉 `effectiveAnim` ref，`ac` 直接从 `animationConfig` prop 计算（`{ ...DEFAULT_ANIMATION_SETTINGS, ...animationConfig }`），确保 prop 变化时立即反映到 `ac`，useEffect 依赖项正确触发

**根因 5：待机动画僵硬**
- swayAmplitude=0.1 太大（0.1 弧度 ≈ 5.7度，身体晃动幅度过大）
- updateSway 只旋转 hips Z 轴，spine 和 head 不参与，身体僵硬
- updateBreathing 只缩放 chest，缺乏 spine 的协同运动
- **修复**：
  1. VRMAnimation.ts updateSway 加入 spine 反向旋转（`-sway * 0.6`）和 head 轻微同向旋转（`sway * 0.3`）
  2. VRMAnimation.ts updateBreathing 加入 spine 轻微 X 轴旋转（`breath * breathAmplitude * 0.5`），模拟呼吸时的身体起伏
  3. settingsStore.ts DEFAULT_ANIMATION_SETTINGS 的 swayAmplitude 从 0.01 调整为 0.02
  4. AvatarManager.tsx sway 滑块 max 从 0.1 调整为 0.05（合理范围）
  5. localStorage 旧数据重置 swayAmplitude=0.02, breathAmplitude=0.015

### 修改文件清单（第二轮追加）

- `c:/CX-O/CX-O-Frontend/src/components/VRM/VRMViewer.tsx`（去掉 effectiveAnim ref，ac 直接从 prop 计算）
- `c:/CX-O/CX-O-Frontend/src/components/VRM/VRMAnimation.ts`（updateSway 加入 spine/head 协同 + updateBreathing 加入 spine 起伏）
- `c:/CX-O/CX-O-Frontend/src/store/settingsStore.ts`（swayAmplitude 默认值 0.01→0.02）
- `c:/CX-O/CX-O-Frontend/src/components/Avatar/AvatarManager.tsx`（sway 滑块 max 0.1→0.05）

### 修复状态（第二轮）

- ✅ VRMViewer.tsx 去掉 effectiveAnim ref（stale closure 修复）
- ✅ VRMAnimation.ts updateSway 加入 spine 反向旋转 + head 同向旋转
- ✅ VRMAnimation.ts updateBreathing 加入 spine X 轴旋转
- ✅ settingsStore.ts swayAmplitude 默认值 0.01→0.02
- ✅ AvatarManager.tsx sway 滑块 max 0.1→0.05
- ✅ typecheck 零错误
- ✅ canvas 高度 613px（Playwright 验证）
- ✅ swayAmplitude=0.02, swayFrequency=0.5, breathAmplitude=0.015（Playwright 验证）
- ⏳ 配置界面实时更新 + 待机动作自然度 + 4 项视觉效果待用户重新确认

### 诊断反思（L1 静默记录）

- stale closure 是 React ref 滥用的典型反模式——ref 用于跨渲染保持可变值，但不触发重新渲染。当 `ac` 依赖 ref.current 时，`ac` 本质上变成了"渲染时快照"，useEffect 依赖项永远不变化
- 修复原则：prop 是单一数据源，直接从 prop 计算派生值，让 React 的依赖追踪机制自然生效
- 动画自然度的关键在于骨骼协同——单一骨骼旋转会显得僵硬，多骨骼按比例协同（hips 主导 + spine 反向补偿 + head 轻微跟随）才能模拟真实人体运动

---

## 第三轮阻断回退记录（2026-07-08 用户三次反馈）

### 用户反馈

- **反馈内容**：第二轮回退修复后用户重新验证，反馈"动作为什么还是接近T POSE？改的自然一点"
- **性质**：阻断交付 — 模型初始姿势接近 T-Pose，手臂几乎水平，待机动画幅度太小几乎不可见
- **影响**：GN-004 已通过但交付仍无法闭合，需进行第三轮回退排查

### 排查与修复

**根因 6：VRMViewer loadModel 中初始骨骼旋转值太小，手臂几乎水平**
- leftUpperArm Z=0.3（约 17 度）仅让手臂从 T-Pose 水平位置向下旋转 17 度
- 视觉上仍接近 T-Pose，手臂几乎水平张开
- 前臂 leftLowerArm Z=0.1（约 6 度）弯曲也几乎不可见
- **修复**：
  - leftUpperArm Z: 0.3 → 1.2（约 69 度，手臂自然下垂）
  - rightUpperArm Z: -0.3 → -1.2
  - leftLowerArm: 新增 Y=-0.3（前臂向内收）+ Z 0.1→0.35（前臂弯曲约 20 度）
  - rightLowerArm: 新增 Y=0.3 + Z -0.1→-0.35
  - 腿部旋转微调（Z 轴轻微外八 + X 轴自然站姿）

**根因 7：待机动画幅度太小，几乎不可见**
- swayAmplitude=0.02（约 1.1 度）摇摆几乎看不到
- breathAmplitude=0.015~0.02（约 0.9~1.1 度）呼吸几乎看不到
- **修复**：
  - swayAmplitude: 0.02 → 0.04（约 2.3 度，可感知的自然摇摆）
  - breathAmplitude: 0.02 → 0.03（约 1.7 度，可感知的自然呼吸）
  - localStorage 旧数据重置 swayAmplitude=0.04, breathAmplitude=0.03, breathFrequency=0.3

### 修改文件清单（第三轮追加）

- `c:/CX-O/CX-O-Frontend/src/components/VRM/VRMViewer.tsx`（初始骨骼旋转值增大，手臂自然下垂 + 前臂向内收弯曲 + 腿部微调）
- `c:/CX-O/CX-O-Frontend/src/store/settingsStore.ts`（swayAmplitude 0.02→0.04, breathAmplitude 0.02→0.03）

### 修复状态（第三轮）

- ✅ VRMViewer.tsx 初始骨骼旋转值增大（leftUpperArm Z 0.3→1.2 手臂自然下垂）
- ✅ VRMViewer.tsx 前臂加入 Y 轴向内收 + Z 轴弯曲
- ✅ settingsStore.ts swayAmplitude 0.02→0.04, breathAmplitude 0.02→0.03
- ✅ localStorage 重置 swayAmplitude=0.04, breathAmplitude=0.03, breathFrequency=0.3
- ✅ typecheck 零错误
- ✅ canvas 高度 613px（Playwright 验证）
- ✅ localStorage 参数验证通过（Playwright）
- ⏳ VRM 模型自然站姿 + 待机动作自然度待用户重新确认

### 诊断反思（L1 静默记录，第三轮）

- T-Pose 问题的根因是初始骨骼旋转值设置不当——VRM 模型默认 T-Pose 是零旋转状态，要让手臂自然下垂需要约 1.2 弧度（69 度）的 Z 轴旋转，0.3 弧度远远不够
- 动画幅度的"自然"范围：摇摆 1~3 度（0.02~0.05 弧度）可感知但不夸张；呼吸 1~2 度（0.02~0.035 弧度）微妙但可见
- 前臂向内收（Y 轴旋转）是让手臂看起来自然的关键——单纯 Z 轴下垂会让前臂仍然指向外侧，加入 Y 轴旋转让前臂自然朝向身体前方

---

## 第四轮阻断回退记录（2026-07-08 用户四次反馈）

### 用户反馈

- **反馈内容**：第三轮回退修复后用户重新验证，反馈"动画无效（至少在配置界面是这样）"
- **性质**：阻断交付 — 前三轮修复了姿势和幅度，但动画根本未运行（dt=0）
- **影响**：GN-004 已通过但交付仍无法闭合，需进行第四轮回退排查

### 排查与修复

**根因 8：VRMViewer 使用 THREE.Timer 但未调用 update()，导致 getDelta() 永远返回 0**

- VRMViewer.tsx 第 69 行 `const clockRef = useRef(new THREE.Timer())` 使用 `THREE.Timer`
- Three.js r184 的 `THREE.Timer.getDelta()` 依赖 `Timer.update()` 更新内部时间状态
- animate loop 中只调用 `getDelta()` 没有 `update()`，导致 dt 永远为 0
- 结果：`VRMAnimation.update(0)` 中 `this.time += 0`，所有基于 time 的动画计算结果为 0，动画完全无效

**排查过程**：

1. 检查 VRMPanel、AvatarManager 数据流 — 均正确
2. 在 VRMViewer animate 循环中添加临时调试代码 `window.__vrmDebug`
3. Playwright evaluate 检查：
   - 第一次：`time: 0, hipsRot.z: 0` — 动画时间不增长
   - 增加调试项后第二次：`dt: 0` — delta time 为 0
4. 确认 THREE.js r184 的 `THREE.Timer.getDelta()` 需要先调用 `update()`

**修复**：

- VRMViewer.tsx 第 269 行添加 `clockRef.current.update();`（在 `getDelta()` 之前）
- 清理临时调试代码 `window.__vrmDebug`（第 280-291 行）

### 修改文件清单（第四轮追加）

- `c:/CX-O/CX-O-Frontend/src/components/VRM/VRMViewer.tsx`（animate loop 添加 clockRef.current.update() + 移除调试代码）

### 修复状态（第四轮）

- ✅ VRMViewer.tsx animate loop 添加 clockRef.current.update()
- ✅ 清理临时调试代码 window.__vrmDebug
- ✅ typecheck 零错误
- ✅ 动画运行验证（Playwright）：
  - 修复前：`time: 0, dt: 0, frame: 19, hipsRot.z: 0`（动画完全无效）
  - 修复后：`time: 15.097, dt: 1.0098, frame: 18, hipsRot.z: -0.012`（动画运行正常）
- ⏳ VRM 模型动画自然度待用户重新确认

### 已知遗留（非阻断）

- **VRMEngine.ts 第 316 行潜在 bug**：VRMEngine 的 animate loop 也有 `clock.getDelta()` 没有 `clock.update()` 的 bug，但当前 VRMViewer 路径取消了 VRMEngine 的 animate loop（`cancelAnimationFrame`），不影响 VRMViewer 路径。可选修复。

### 诊断反思（L1 静默记录，第四轮）

- `THREE.Timer` vs `THREE.Clock` 的 API 差异是隐蔽陷阱：
  - `THREE.Clock.getDelta()` 内部自动更新 `oldTime`，无需手动 update
  - `THREE.Timer.getDelta()` 依赖 `update()` 手动更新时间状态，不调用则返回 0
- 这类 bug 的特征：代码无任何报错，typecheck 通过，但运行时行为完全静默失败
- 排查方法：在 animate loop 中输出 dt 和关键动画状态变量，若 dt=0 则立即定位到时钟问题
- 教训：使用 Three.js API 时必须区分 Clock 和 Timer 的使用模式，不能混用调用约定
- 四轮回退修复的反思：前三轮都在调整动画参数和姿势，但根本问题是动画根本没运行。若一开始就检查 dt 值，可一次性定位根因。后续遇到"动画无效"类问题，应优先检查时钟和 dt 值，而非调整参数

---

## 第五轮阻断回退记录（2026-07-09 用户五次反馈）

### 用户反馈

- **反馈内容**：第四轮回退修复后（动画已运行）用户重新验证，反馈：
  1. "整个模型摇晃太不自然了" — 摇摆运动太机械
  2. "呼吸等应当提供更高自由度" — 配置参数不够丰富
  3. "默认姿势应该更自然一点，类似于vtube studio" — 初始姿势不够自然
  4. "注意live2d也要改" — Live2D 也要有待机动画
- **性质**：阻断交付 — 动画虽运行但自然度不足，且 Live2D 完全缺失待机动画
- **影响**：GN-004 已通过但交付仍无法闭合，需进行第五轮回退排查

### 排查与修复

**根因 9：VRM 摇摆动画太机械**
- `updateSway` 使用纯正弦波，完全周期性，没有随机性或物理感
- **修复**：双频率叠加（慢速主摇摆 + 快速微抖）+ random walk 微随机性 + 多骨骼协同（hips/spine/chest/head）

**根因 10：VRM 呼吸动画太规律**
- `updateBreathing` 使用纯正弦波，频率固定
- **修复**：呼吸频率微随机变化（每 3-5 秒更新）+ 噪声幅度变化

**根因 11：VRM 默认姿势不够自然**
- leftUpperArm Z=1.2（69度）完全下垂，手臂贴身
- **修复**：leftUpperArm Z 1.2→0.9（52度，自然 A-Pose，手臂略向外）

**根因 12：Live2D 完全没有待机动画**
- Live2DViewer 接收 animationConfig 但完全未使用
- **修复**：live2dEngine 新增 updateIdleAnimation（ParamBreath/ParamBodyAngleXZ/ParamEyeLOpen/ParamEyeROpen）+ Live2DViewer 接入 animationConfig

**自由度扩展**：
- 新增 swayIrregularity（摇摆不规律度，0-1，默认 0.3）
- 新增 breathIrregularity（呼吸不规律度，0-1，默认 0.2）
- 新增 headIdleRange（头部空闲漂移范围，0-0.1，默认 0.03）
- AvatarManager VRM 和 Live2D 分支均新增对应滑块

### 修改文件清单（第五轮追加）

- `c:/CX-O/CX-O-Frontend/src/store/settingsStore.ts`（AnimationSettings 新增 3 参数 + merge 深度合并 live2d.animation）
- `c:/CX-O/CX-O-Frontend/src/components/VRM/VRMAnimation.ts`（重写：SimpleNoise 类 + updateSway/updateBreathing/updateHeadFollow）
- `c:/CX-O/CX-O-Frontend/src/components/VRM/VRMViewer.tsx`（初始骨骼旋转值 A-Pose + setConfig 传新参数）
- `c:/CX-O/CX-O-Frontend/src/components/Live2D/live2dEngine.ts`（IdleAnimationState + updateIdleAnimation + setIdleAnimationConfig/Enabled）
- `c:/CX-O/CX-O-Frontend/src/components/Live2D/Live2DViewer.tsx`（接入 animationConfig + useEffect 更新）
- `c:/CX-O/CX-O-Frontend/src/components/Avatar/AvatarManager.tsx`（VRM 新增 3 滑块 + Live2D 新增待机动画参数）

### 修复状态（第五轮）

- ✅ settingsStore AnimationSettings 新增 3 参数 + merge 深度合并
- ✅ VRMAnimation 重写（SimpleNoise + 双频率叠加 + random walk + 空闲头部漂移）
- ✅ VRMViewer 姿势调整（A-Pose，leftUpperArm Z 0.9）
- ✅ live2dEngine 待机动画（呼吸/摇摆/眨眼）
- ✅ Live2DViewer 接入 animationConfig
- ✅ AvatarManager UI 扩展（VRM 3 新滑块 + Live2D 待机动画参数）
- ✅ typecheck 零错误
- ✅ localStorage 参数验证通过（Playwright）
- ⏳ VRM+Live2D 动画自然度待用户重新确认

### 诊断反思（L1 静默记录，第五轮）

- VTube Studio 风格的核心是"微随机性"——纯正弦波太机械，需要多频率叠加 + noise + random walk 模拟自然运动
- 呼吸的关键：频率微变化（不是固定频率）+ 幅度微变化（噪声调制）
- 摇摆的关键：双频率叠加（慢+快）+ random walk 不规律度 + 多骨骼协同分配
- Live2D 待机动画通过标准 Cubism 参数实现（ParamBreath/ParamBodyAngle/ParamEyeLOpen），不需要模型内置 motion
- Live2D 参数范围与 VRM 不同：ParamBodyAngle 是度数（-30~30），需要将弧度转换为度数
- PIXI ticker 回调签名是 `() => void`，delta time 通过 `app.ticker.deltaMS` 获取，不是回调参数

---

## 第六轮阻断回退记录（2026-07-09 用户六次反馈）

### 用户反馈

- **反馈内容**：第五轮修复后用户重新验证，反馈三个问题：
  1. "手臂完全放下来吧" — 手臂角度仍不够下垂（leftUpperArm Z=1.05 约 60 度，仍向外张）
  2. "表情方面也要优化" — 表情僵硬，无空闲微表情
  3. "修复每次进入VRM 虚拟形象配置都需要拖动一下滑块才能把预览恢复到设置的配置的问题" — 配置界面预览与设置不匹配
- **性质**：阻断交付 — 姿势/表情/预览匹配三方面均需修复
- **影响**：GN-004 已通过但交付仍无法闭合，需进行第六轮回退排查

### 排查与修复

**根因 9（编号重用）：手臂角度仍不够下垂**
- leftUpperArm Z=1.05（约 60 度）手臂仍向外张，用户要求完全下垂
- **修复**：leftUpperArm Z 1.05→1.4（约 80 度），leftLowerArm Y -0.15→-0.3（前臂向内收更多）, Z 0.25→0.15（前臂弯曲减小）

**根因 10：配置界面预览不匹配（stale closure）**
- VRMViewer 的 `loadModel` 在 `useEffect [dataVersion, modelPath]` 中定义，闭包捕获 `ac`/`tc`
- 异步加载模型期间若 `animationConfig`/`tweakConfig` prop 变化，`loadModel` 仍使用旧闭包值
- 模型加载完成后应用旧配置 → 预览与设置不一致
- AvatarManager 缺少 `animation` → `animConfig` 同步 useEffect（`tweak` 有同步，`animation` 没有）
- **修复**：
  1. VRMViewer 添加 `acRef`/`tcRef`，`loadModel` 中使用 `acRef.current`/`tcRef.current`
  2. AvatarManager 添加 `vrm.animation`/`live2d.animation` → `animConfig` 同步 useEffect

**根因 11：表情僵硬，无空闲微表情**
- VRMExpression.update() 在无主动情绪时将所有表情预设归零，面部完全静止
- 缺乏 VTube Studio 风格的空闲微表情
- **修复**：VRMExpression 新增 `applyIdleMicroExpressions()`：
  - 基线 relaxed 表情（微弱常量，intensity*0.4）
  - 噪声驱动微微笑（约 15 秒周期，intensity*0.7）
  - 偶尔微弱惊讶（罕见且微弱，intensity*0.3）
  - 新增 `idleExpressionIntensity` 配置参数（默认 0.1，范围 0-0.3）
  - AvatarManager 表情标签页新增滑块（VRM only）

### 修改文件清单（第六轮追加）

- `c:/CX-O/CX-O-Frontend/src/components/VRM/VRMViewer.tsx`（手臂角度 1.05→1.4 + acRef/tcRef + idleExpressionIntensity）
- `c:/CX-O/CX-O-Frontend/src/components/VRM/VRMExpression.ts`（SimpleNoise + applyIdleMicroExpressions + idleExpressionIntensity）
- `c:/CX-O/CX-O-Frontend/src/store/settingsStore.ts`（AnimationSettings 新增 idleExpressionIntensity）
- `c:/CX-O/CX-O-Frontend/src/components/Avatar/AvatarManager.tsx`（animConfig 同步 + 空闲微表情滑块）

### 修复状态（第六轮）

- ✅ VRMViewer 手臂角度 leftUpperArm Z 1.4（完全下垂）
- ✅ VRMViewer acRef/tcRef 修复 stale closure
- ✅ AvatarManager animConfig 同步 useEffect
- ✅ VRMExpression applyIdleMicroExpressions（基线 relaxed + 噪声微微笑 + 偶尔惊讶）
- ✅ settingsStore idleExpressionIntensity（默认 0.1）
- ✅ AvatarManager 空闲微表情滑块
- ✅ typecheck 零错误
- ⏳ 配置界面预览匹配 + 表情自然度 + 手臂姿势待用户重新确认

### 诊断反思（L1 静默记录，第六轮）

- React stale closure 的典型场景：useEffect 闭包捕获渲染时的值，异步操作完成时值可能已过期。修复方式是用 ref 保持最新值的引用
- AvatarManager 的 `tweakConfig` 有同步 useEffect 但 `animConfig` 没有——这是一个不对称的遗漏，两个都是从 store 初始化的 local state，应该有同等的同步机制
- 空闲微表情的关键是"微"——intensity 0.1 意味着表情权重最大约 0.04-0.07，肉眼可见但不突兀。过大就会显得表情在乱动
- VRMExpression 的 update() 每帧重置所有表情预设为 0，然后重新应用——这是一种"声明式"的表情管理，每帧从零开始构建最终状态，避免状态累积
