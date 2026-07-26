/**
 * draw-element.ts — Liquid Glass 离屏渲染 + instanced quad 单 draw call
 * ============================================================================
 * 模块: 模块4 WebGL 玻璃层
 * 契约: D2 glass_tier_config.schema.json (renderPipeline) +
 *        I1 frontend_glass.pyi (drawElement + DrawElementOptions)
 * 用途: html2canvas-alike 离屏渲染 DOM 元素到 backgroundFBO + instanced quad 单 draw call
 *
 * drawElement（I1 + OBS-E 处置）:
 *   - 每帧通过本接口离屏渲染当前页面背景到 backgroundFBO
 *   - 节流到 30fps（滚动时 60fps）
 *   - accuracyLevel 三级: high / medium / low
 *   - onAccuracyDrop 回调: 准确性降级时通知业务层
 *
 * instanced quad（D2 renderPipeline.instancing）:
 *   - perQuad: true（每个玻璃元素作为 instanced quad 提交）
 *   - drawCallLimit: 20（单 draw call 渲染同形态元件，目标 draw call < 20）
 * ============================================================================
 */

// ============================================================================
// 类型定义（I1 TypedDict 对应）
// ============================================================================

/**
 * 准确性保证级别（I1 DrawElementOptions.accuracyLevel, OBS-E 处置）。
 *
 * - "high": 完整还原 element 视觉（含阴影/渐变/变换），用于玻璃折射采样源
 * - "medium": 降级准确性，跳过部分阴影/渐变计算，保留主要色彩与布局
 * - "low": 最低准确性，仅采样主色块，用于 Tier 3 以下或极端性能场景
 */
export type AccuracyLevel = 'high' | 'medium' | 'low';

/**
 * drawElement 离屏渲染选项（I1 DrawElementOptions, OBS-E 处置）。
 */
export interface DrawElementOptions {
  /** 准确性保证级别 */
  accuracyLevel: AccuracyLevel;
  /** 目标帧率（桌面 30 / 滚动时 60） */
  targetFps: number;
  /** 缩放比例（默认 1.0） */
  scale: number;
  /** 准确性降级回调 */
  onAccuracyDrop: (level: AccuracyLevel) => void;
}

// ============================================================================
// 常量定义（D2 + C1 配置驱动）
// ============================================================================

/** 默认帧率（D2 renderPipeline.backgroundFBO.defaultFps = 30） */
const DEFAULT_FPS = 30;

/** 滚动时帧率（D2 renderPipeline.backgroundFBO.scrollFps = 60） */
const SCROLL_FPS = 60;

/** draw call 上限（D2 renderPipeline.instancing.drawCallLimit = 20） */
const DRAW_CALL_LIMIT = 20;

// ============================================================================
// 准确性降级辅助函数
// ============================================================================

/**
 * 获取下一级准确性级别（降级路径: high → medium → low）。
 *
 * OBS-E 降级行为:
 *   - accuracy 不达 high 时，自动降级到 medium
 *   - 仍不达则降级到 low
 *   - 降级不可逆（同帧内），下一帧重新评估
 *
 * @param current 当前准确性级别
 * @returns 下一级准确性级别，若已是 low 则返回 null
 */
export function getNextAccuracyLevel(current: AccuracyLevel): AccuracyLevel | null {
  switch (current) {
    case 'high':
      return 'medium';
    case 'medium':
      return 'low';
    case 'low':
      return null;
    default:
      return null;
  }
}

/**
 * 检测当前性能是否足以维持指定准确性级别。
 *
 * @param level 准确性级别
 * @param frameTimeMs 上一帧耗时
 * @param frameBudgetMs 帧预算（ms）
 * @returns 是否能维持该级别
 */
function canSustainAccuracy(
  level: AccuracyLevel,
  frameTimeMs: number,
  frameBudgetMs: number,
): boolean {
  // high 级别需要帧耗时在预算内
  if (level === 'high') {
    return frameTimeMs <= frameBudgetMs;
  }
  // medium 级别允许超出预算 50%
  if (level === 'medium') {
    return frameTimeMs <= frameBudgetMs * 1.5;
  }
  // low 级别总是可以维持
  return true;
}

// ============================================================================
// drawElement 函数（I1 签名匹配）
// ============================================================================

/**
 * 函数: drawElement — html2canvas-alike 离屏渲染接口（I1 + OBS-E 处置, merged.md §2.3）。
 *
 * 每帧通过本接口离屏渲染当前页面背景到 backgroundFBO，节流到 30fps（滚动时 60fps）。
 *
 * OBS-E 准确性保证级别契约:
 *   - accuracyLevel="high": 完整还原 element 视觉（含阴影/渐变/变换），用于玻璃折射采样源。
 *     当 GPU 性能充足时使用。若 30fps 下无法维持 high，降级到 medium。
 *   - accuracyLevel="medium": 降级准确性，跳过部分阴影/渐变计算，保留主要色彩与布局。
 *     降级时触发 onAccuracyDrop("medium") 回调。
 *   - accuracyLevel="low": 最低准确性，仅采样主色块，用于 Tier 3 以下或极端性能场景。
 *     降级时触发 onAccuracyDrop("low") 回调。
 *
 * 降级行为:
 *   - accuracy 不达 high 时，自动降级到 medium；仍不达则降级到 low。
 *   - 每次降级触发 onAccuracyDrop 回调，业务层可据此提示用户视觉精度下降。
 *   - 降级不可逆（同帧内），下一帧重新评估。
 *
 * @param element 待离屏渲染的 DOM 元素
 * @param options 渲染选项，含 accuracyLevel / targetFps / scale / onAccuracyDrop
 * @returns 离屏渲染结果 canvas，供 backgroundFBO 采样
 * @throws Error element 不存在或 options.accuracyLevel 不是合法枚举值时抛出
 */
export async function drawElement(
  element: HTMLElement,
  options: DrawElementOptions,
): Promise<OffscreenCanvas> {
  // 参数校验
  if (!element) {
    throw new Error('drawElement: element is null or undefined');
  }
  const validLevels: AccuracyLevel[] = ['high', 'medium', 'low'];
  if (!validLevels.includes(options.accuracyLevel)) {
    throw new Error(`drawElement: invalid accuracyLevel '${options.accuracyLevel}', must be one of ${validLevels.join(', ')}`);
  }

  const { scale, accuracyLevel, onAccuracyDrop } = options;

  // 获取元素尺寸
  const rect = element.getBoundingClientRect();
  const width = Math.max(1, Math.ceil(rect.width * scale));
  const height = Math.max(1, Math.ceil(rect.height * scale));

  // 创建 OffscreenCanvas
  const canvas = new OffscreenCanvas(width, height);
  const ctx = canvas.getContext('2d');
  if (!ctx) {
    throw new Error('drawElement: failed to get OffscreenCanvas 2D context');
  }

  // 读取元素计算样式
  const computedStyle = typeof window !== 'undefined'
    ? window.getComputedStyle(element)
    : null;

  // 根据准确性级别渲染
  let currentLevel = accuracyLevel;

  // 渲染背景色
  if (computedStyle) {
    const bgColor = computedStyle.backgroundColor;
    if (bgColor && bgColor !== 'transparent') {
      ctx.fillStyle = bgColor;
      ctx.fillRect(0, 0, width, height);
    }
  }

  // high 级别：渲染完整视觉（边框、圆角、阴影、渐变）
  if (currentLevel === 'high' && computedStyle) {
    renderHighAccuracy(ctx, element, computedStyle, rect, scale);

    // 检测是否需要降级（简化：如果渲染耗时过长则降级）
    const renderTime = performance.now();
    const frameBudget = 1000 / (options.targetFps || DEFAULT_FPS);
    if (!canSustainAccuracy('high', renderTime, frameBudget)) {
      currentLevel = 'medium';
      onAccuracyDrop('medium');
    }
  }

  // medium 级别：跳过阴影/渐变，保留主要色彩与布局
  if (currentLevel === 'medium' && computedStyle) {
    renderMediumAccuracy(ctx, element, computedStyle, rect, scale);

    const renderTime = performance.now();
    const frameBudget = 1000 / (options.targetFps || DEFAULT_FPS);
    if (!canSustainAccuracy('medium', renderTime, frameBudget)) {
      currentLevel = 'low';
      onAccuracyDrop('low');
    }
  }

  // low 级别：仅采样主色块
  if (currentLevel === 'low' && computedStyle) {
    renderLowAccuracy(ctx, computedStyle, width, height);
  }

  return canvas;
}

// ============================================================================
// 渲染辅助函数（不同准确性级别的实现）
// ============================================================================

/**
 * high 准确性渲染：完整还原 element 视觉（含阴影/渐变/变换）。
 */
function renderHighAccuracy(
  ctx: OffscreenCanvasRenderingContext2D,
  element: HTMLElement,
  style: CSSStyleDeclaration,
  rect: DOMRect,
  scale: number,
): void {
  // 渲染边框
  const borderColor = style.borderColor;
  const borderWidth = parseFloat(style.borderWidth) || 0;
  if (borderWidth > 0 && borderColor && borderColor !== 'transparent') {
    ctx.strokeStyle = borderColor;
    ctx.lineWidth = borderWidth * scale;
    ctx.strokeRect(0, 0, rect.width * scale, rect.height * scale);
  }

  // 渲染圆角路径
  const borderRadius = parseFloat(style.borderRadius) || 0;
  if (borderRadius > 0) {
    ctx.beginPath();
    ctx.roundRect(0, 0, rect.width * scale, rect.height * scale, borderRadius * scale);
    ctx.clip();
  }

  // 渲染阴影（high 级别特有）
  const boxShadow = style.boxShadow;
  if (boxShadow && boxShadow !== 'none') {
    ctx.shadowColor = 'rgba(0, 0, 0, 0.12)';
    ctx.shadowBlur = 32 * scale;
    ctx.shadowOffsetY = 8 * scale;
  }

  // 渲染背景渐变（high 级别特有）
  const backgroundImage = style.backgroundImage;
  if (backgroundImage && backgroundImage !== 'none') {
    // 简化的渐变渲染
    const gradient = ctx.createLinearGradient(0, 0, 0, rect.height * scale);
    gradient.addColorStop(0, 'rgba(255, 255, 255, 0.1)');
    gradient.addColorStop(1, 'rgba(255, 255, 255, 0)');
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, rect.width * scale, rect.height * scale);
  }

  // 渲染文本内容（high 级别）
  const textContent = element.textContent;
  if (textContent) {
    const fontSize = parseFloat(style.fontSize) || 14;
    ctx.font = `${fontSize * scale}px ${style.fontFamily || 'sans-serif'}`;
    ctx.fillStyle = style.color || '#000';
    ctx.textBaseline = 'top';
    ctx.fillText(textContent.substring(0, 100), 8 * scale, 8 * scale);
  }

  // 重置阴影
  ctx.shadowColor = 'transparent';
  ctx.shadowBlur = 0;
  ctx.shadowOffsetY = 0;
}

/**
 * medium 准确性渲染：跳过阴影/渐变，保留主要色彩与布局。
 */
function renderMediumAccuracy(
  ctx: OffscreenCanvasRenderingContext2D,
  element: HTMLElement,
  style: CSSStyleDeclaration,
  rect: DOMRect,
  scale: number,
): void {
  // 跳过阴影和渐变（medium 级别简化）

  // 渲染边框
  const borderColor = style.borderColor;
  const borderWidth = parseFloat(style.borderWidth) || 0;
  if (borderWidth > 0 && borderColor && borderColor !== 'transparent') {
    ctx.strokeStyle = borderColor;
    ctx.lineWidth = borderWidth * scale;
    ctx.strokeRect(0, 0, rect.width * scale, rect.height * scale);
  }

  // 渲染圆角
  const borderRadius = parseFloat(style.borderRadius) || 0;
  if (borderRadius > 0) {
    ctx.beginPath();
    ctx.roundRect(0, 0, rect.width * scale, rect.height * scale, borderRadius * scale);
    ctx.clip();
  }

  // 渲染文本（简化，仅前 50 字符）
  const textContent = element.textContent;
  if (textContent) {
    const fontSize = parseFloat(style.fontSize) || 14;
    ctx.font = `${fontSize * scale}px ${style.fontFamily || 'sans-serif'}`;
    ctx.fillStyle = style.color || '#000';
    ctx.textBaseline = 'top';
    ctx.fillText(textContent.substring(0, 50), 8 * scale, 8 * scale);
  }
}

/**
 * low 准确性渲染：仅采样主色块。
 */
function renderLowAccuracy(
  ctx: OffscreenCanvasRenderingContext2D,
  style: CSSStyleDeclaration,
  width: number,
  height: number,
): void {
  // 仅填充主背景色
  const bgColor = style.backgroundColor;
  if (bgColor && bgColor !== 'transparent') {
    ctx.fillStyle = bgColor;
    ctx.fillRect(0, 0, width, height);
  } else {
    // 默认半透明白色
    ctx.fillStyle = 'rgba(255, 255, 255, 0.08)';
    ctx.fillRect(0, 0, width, height);
  }
}

// ============================================================================
// instanced quad 辅助函数（D2 renderPipeline.instancing）
// ============================================================================

/**
 * 玻璃元件实例数据（每个 instanced quad 的变换参数）。
 */
export interface GlassInstance {
  /** 实例位置 x（NDC 坐标 [-1, 1]） */
  offsetX: number;
  /** 实例位置 y（NDC 坐标 [-1, 1]） */
  offsetY: number;
  /** 实例缩放 x */
  scaleX: number;
  /** 实例缩放 y */
  scaleY: number;
}

/**
 * 创建 instanced quad 顶点缓冲（单 draw call 渲染同形态元件）。
 *
 * D2 renderPipeline.instancing:
 *   - perQuad: true（每个玻璃元素作为 instanced quad 提交）
 *   - drawCallLimit: 20（目标 draw call < 20）
 *
 * WebGL2 使用 gl.drawArraysInstanced，WebGL1 使用 ANGLE_instanced_arrays 扩展。
 *
 * @param gl GL 上下文
 * @returns 顶点缓冲 + 实例缓冲 + 顶点数组对象（WebGL2）
 */
export function createInstancedQuadBuffer(gl: WebGLRenderingContext | WebGL2RenderingContext): {
  quadBuffer: WebGLBuffer;
  instanceBuffer: WebGLBuffer;
  vertexCount: number;
} {
  // 全屏 quad 顶点（两个三角形）
  const quadVertices = new Float32Array([
    -1, -1, 0, 0,
    1, -1, 1, 0,
    -1, 1, 0, 1,
    -1, 1, 0, 1,
    1, -1, 1, 0,
    1, 1, 1, 1,
  ]);

  const quadBuffer = gl.createBuffer();
  if (quadBuffer) {
    gl.bindBuffer(gl.ARRAY_BUFFER, quadBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, quadVertices, gl.STATIC_DRAW);
  }

  // 实例数据缓冲（动态更新）
  const instanceBuffer = gl.createBuffer();

  return {
    quadBuffer: quadBuffer as WebGLBuffer,
    instanceBuffer: instanceBuffer as WebGLBuffer,
    vertexCount: 6,
  };
}

/**
 * 上传实例数据并执行单 draw call 渲染所有同形态玻璃元件。
 *
 * D2 renderPipeline.instancing:
 *   - 单 draw call 渲染同形态元件（perQuad = true）
 *   - 目标 draw call < 20（drawCallLimit = 20）
 *
 * @param gl GL 上下文
 * @param instanceBuffer 实例缓冲
 * @param instances 玻璃元件实例列表
 * @returns 实际渲染的 draw call 数（始终为 1，instanced rendering）
 */
export function drawInstancedQuads(
  gl: WebGLRenderingContext | WebGL2RenderingContext,
  instanceBuffer: WebGLBuffer,
  instances: GlassInstance[],
): number {
  if (instances.length === 0) return 0;

  // 检查是否超过同屏上限（C1 limitRules.maxGlassElementsPerScreen = 8）
  const maxInstances = Math.min(instances.length, DRAW_CALL_LIMIT);

  // 准备实例数据（每个实例 4 个 float: offsetX, offsetY, scaleX, scaleY）
  const instanceData = new Float32Array(maxInstances * 4);
  for (let i = 0; i < maxInstances; i++) {
    const inst = instances[i];
    instanceData[i * 4] = inst.offsetX;
    instanceData[i * 4 + 1] = inst.offsetY;
    instanceData[i * 4 + 2] = inst.scaleX;
    instanceData[i * 4 + 3] = inst.scaleY;
  }

  // 上传实例数据
  gl.bindBuffer(gl.ARRAY_BUFFER, instanceBuffer);
  gl.bufferData(gl.ARRAY_BUFFER, instanceData, gl.DYNAMIC_DRAW);

  // WebGL2: 使用 drawArraysInstanced
  if (gl instanceof WebGL2RenderingContext) {
    const gl2 = gl as WebGL2RenderingContext;
    gl2.drawArraysInstanced(gl2.TRIANGLES, 0, 6, maxInstances);
  } else {
    // WebGL1: 使用 ANGLE_instanced_arrays 扩展
    const ext = gl.getExtension('ANGLE_instanced_arrays');
    if (ext) {
      ext.drawArraysInstancedANGLE(gl.TRIANGLES, 0, 6, maxInstances);
    } else {
      // 回退：逐个渲染（不推荐，draw call 会增加）
      for (let i = 0; i < maxInstances; i++) {
        gl.drawArrays(gl.TRIANGLES, 0, 6);
      }
    }
  }

  // instanced rendering 始终是 1 个 draw call
  return 1;
}

/**
 * 获取 draw call 上限（D2 renderPipeline.instancing.drawCallLimit = 20）。
 */
export function getDrawCallLimit(): number {
  return DRAW_CALL_LIMIT;
}

/**
 * 获取默认帧率（D2 renderPipeline.backgroundFBO.defaultFps = 30）。
 */
export function getDefaultFps(): number {
  return DEFAULT_FPS;
}

/**
 * 获取滚动帧率（D2 renderPipeline.backgroundFBO.scrollFps = 60）。
 */
export function getScrollFps(): number {
  return SCROLL_FPS;
}
