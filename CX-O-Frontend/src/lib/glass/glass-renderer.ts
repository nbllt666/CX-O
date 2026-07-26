/**
 * glass-renderer.ts — Liquid Glass WebGL 渲染器（核心）
 * ============================================================================
 * 模块: 模块4 WebGL 玻璃层
 * 契约: D2 glass_tier_config.schema.json (renderPipeline + shader + gpuMemoryManagement) +
 *        C1 frontend_glass_config.schema.json (webglUniforms + tierTriggers) +
 *        I1 frontend_glass.pyi (GlassRenderer + createGlassShader)
 * 用途: 四级 tier 降级链路 + 着色器编译 + uniform 校验 + 双 FBO ping-pong + instanced quad
 *
 * 四级 tier 降级（强制顺序，禁止跳级, D2 tiers + C1 tierTriggers）:
 *   Tier 1 WebGL2 → Tier 2 WebGL1 → Tier 3 CSS backdrop-filter → Tier 4 solid bg
 *
 * 三层 shader（D2 shader.fragmentShader）:
 *   - 折射层: uRefractionStrength（默认 0.08，C1 webglUniforms）
 *   - 色散层: uDispersionR/G/B（默认 0.075/0.080/0.085，禁止合并为单值）
 *   - 高光层: Fresnel pow(1-dot(N,V), uFresnelPower)（uFresnelPower 默认 2.5）
 *
 * 动态光影（D2 dynamicLighting + C1 webglUniforms）:
 *   - uPointerPosition: 30fps 节流
 *   - uScrollVelocity: 滚动速度驱动高光偏移
 *   - uTime: 每帧上传
 *
 * 跨模块导入: 仅 import 模块2 theme（registerGLContext/unregisterGLContext）+ 自身内部 + 第三方
 * 错误码: FE-GLA-001 (GLSL编译失败) / FE-GLA-002 (GPU上下文丢失) /
 *         FE-GLA-003 (FBO创建失败) / FE-GLA-004 (tier降级失败)
 * ============================================================================
 */

import vertexShaderSource from './shaders/vertex.vert?raw';
// refraction.frag / dispersion.frag / highlight.frag 为三层 shader 的独立参考实现（交付物）。
// 实际运行时由 combineFragmentShaders() 将三层 GLSL 内联组合为单一 fragment shader，
// 避免多 pass 渲染开销，实现 instanced quad 单 draw call（闭合判据 §6）。

import { GlassTier, getNextDowngradeTier } from './tier-detector';
import { PerformanceMonitor } from './performance-monitor';
import { GPUMemoryManager, GPUContextLossError } from './gpu-memory-manager';
import { FBOManager, FBOCreationError } from './fbo-ping-pong';
import { createInstancedQuadBuffer, drawInstancedQuads, type GlassInstance } from './draw-element';
import { registerGLContext, unregisterGLContext } from '@/lib/theme';

// ============================================================================
// 异常定义（I1 异常契约）
// ============================================================================

/**
 * GLSL 着色器编译失败异常（I1 GLSLCompileError, FE-GLA-001）。
 *
 * 抛出条件: createGlassShader 编译 vertex/fragment shader 时 gl.getShaderInfoLog 返回非空错误。
 * 调用方处理: 捕获后降级到 Tier 3（CSS backdrop-filter），并上报错误码 FE-GLA-001。
 */
export class GLSLCompileError extends Error {
  readonly errorCode: 'FE-GLA-001';
  readonly shaderType: 'vertex' | 'fragment';
  readonly infoLog: string;

  constructor(message: string, shaderType: 'vertex' | 'fragment', infoLog: string) {
    super(message);
    this.name = 'GLSLCompileError';
    this.errorCode = 'FE-GLA-001';
    this.shaderType = shaderType;
    this.infoLog = infoLog;
    Object.setPrototypeOf(this, GLSLCompileError.prototype);
  }
}

/**
 * 着色器程序链接失败异常（I1 ShaderLinkError, FE-GLA-001）。
 *
 * 抛出条件: createGlassShader 链接 program 时 gl.getProgramInfoLog 返回非空错误，或 link 状态为 false。
 * 调用方处理: 捕获后降级到 Tier 3，并上报错误码 FE-GLA-001。
 */
export class ShaderLinkError extends Error {
  readonly errorCode: 'FE-GLA-001';
  readonly infoLog: string;

  constructor(message: string, infoLog: string) {
    super(message);
    this.name = 'ShaderLinkError';
    this.errorCode = 'FE-GLA-001';
    this.infoLog = infoLog;
    Object.setPrototypeOf(this, ShaderLinkError.prototype);
  }
}

/**
 * tier 降级失败异常（I1 TierDegradeError, FE-GLA-004）。
 *
 * 抛出条件: useGlassTier 尝试从 Tier N 降级到 Tier N+1 时，目标 tier 不可用或降级路径配置缺失。
 * 调用方处理: 捕获后强制降级到 Tier 4（solid bg 兜底），上报错误码 FE-GLA-004。
 */
export class TierDegradeError extends Error {
  readonly errorCode: 'FE-GLA-004';
  readonly fromTier: GlassTier;
  readonly toTier: GlassTier;

  constructor(message: string, fromTier: GlassTier, toTier: GlassTier) {
    super(message);
    this.name = 'TierDegradeError';
    this.errorCode = 'FE-GLA-004';
    this.fromTier = fromTier;
    this.toTier = toTier;
    Object.setPrototypeOf(this, TierDegradeError.prototype);
  }
}

// ============================================================================
// 类型定义（I1 TypedDict 对应）
// ============================================================================

/**
 * GlassRenderer 初始化选项（I1 GlassRendererOptions）。
 */
export interface GlassRendererOptions {
  /** 是否开启抗锯齿 */
  antialias: boolean;
  /** 是否开启 alpha 通道 */
  alpha: boolean;
  /** 是否预乘 alpha */
  premultipliedAlpha: boolean;
  /** 是否保留绘制缓冲 */
  preserveDrawingBuffer: boolean;
  /** FBO 总显存上限 MB（默认 48，C1 memoryLimits.fboMemoryLimit） */
  maxFboMemoryMB: number;
  /** 目标帧率（桌面 60 / 移动 30） */
  fps: number;
}

/**
 * 帧数据（I1 render 方法参数）。
 */
export interface FrameData {
  /** 背景纹理（来自 backgroundFBO） */
  backgroundTexture: WebGLTexture | null;
  /** 玻璃元件实例列表（instanced quad） */
  instances: GlassInstance[];
  /** uniform 值 */
  uniforms: GlassUniforms;
}

/**
 * 玻璃 uniform 值（C1 webglUniforms 对齐）。
 */
export interface GlassUniforms {
  /** 折射强度系数（默认 0.08，范围 [0, 0.3]） */
  uRefractionStrength: number;
  /** 色散 R 通道折射系数（默认 0.075） */
  uDispersionR: number;
  /** 色散 G 通道折射系数（默认 0.080） */
  uDispersionG: number;
  /** 色散 B 通道折射系数（默认 0.085） */
  uDispersionB: number;
  /** Fresnel 指数（默认 2.5） */
  uFresnelPower: number;
  /** 鼠标位置 vec2（归一化 [0,1]，30fps 节流） */
  uPointerPosition: [number, number];
  /** 滚动速度 vec2 */
  uScrollVelocity: [number, number];
  /** 时间（秒） */
  uTime: number;
  /** 玻璃着色 vec4（RGBA 0-1） */
  uGlassTint: [number, number, number, number];
}

// ============================================================================
// 配置默认值（C1 webglUniforms 对齐，禁止硬编码 magic number）
// ============================================================================

/**
 * WebGL uniform 默认值（C1 frontend_glass_config.schema.json webglUniforms）。
 * 所有可调参数走 C1 配置契约，禁止在着色器源码中硬编码。
 */
export const DEFAULT_GLASS_UNIFORMS: GlassUniforms = {
  uRefractionStrength: 0.08,
  uDispersionR: 0.075,
  uDispersionG: 0.080,
  uDispersionB: 0.085,
  uFresnelPower: 2.5,
  uPointerPosition: [0.5, 0.5],
  uScrollVelocity: [0, 0],
  uTime: 0,
  uGlassTint: [224 / 255, 187 / 255, 228 / 255, 0.08],
};

// ============================================================================
// createGlassShader 函数（I1 签名匹配）
// ============================================================================

/**
 * 函数: createGlassShader — 编译并链接玻璃着色器程序（I1, merged.md §2.2）。
 *
 * fragment shader 实现三层叠加: 折射层 + 色散层（R 0.075 / G 0.080 / B 0.085）+ 高光层（Fresnel pow(1-dot(N,V),2.5)）。
 *
 * @param gl WebGL 上下文
 * @param vertexShaderSource vertex shader GLSL 源码
 * @param fragmentShaderSource fragment shader GLSL 源码
 * @returns 编译链接成功的着色器程序
 * @throws GLSLCompileError vertex/fragment shader 编译失败
 * @throws ShaderLinkError 着色器程序链接失败
 */
export function createGlassShader(
  gl: WebGLRenderingContext | WebGL2RenderingContext,
  vertexShaderSrc: string,
  fragmentShaderSrc: string,
): WebGLProgram {
  // 编译 vertex shader
  const vertShader = gl.createShader(gl.VERTEX_SHADER);
  if (!vertShader) {
    throw new GLSLCompileError('Failed to create vertex shader object', 'vertex', 'createShader returned null');
  }
  gl.shaderSource(vertShader, vertexShaderSrc);
  gl.compileShader(vertShader);

  if (!gl.getShaderParameter(vertShader, gl.COMPILE_STATUS)) {
    const infoLog = gl.getShaderInfoLog(vertShader) ?? 'Unknown compile error';
    gl.deleteShader(vertShader);
    throw new GLSLCompileError(
      `Vertex shader compilation failed: ${infoLog}`,
      'vertex',
      infoLog,
    );
  }

  // 编译 fragment shader
  const fragShader = gl.createShader(gl.FRAGMENT_SHADER);
  if (!fragShader) {
    gl.deleteShader(vertShader);
    throw new GLSLCompileError('Failed to create fragment shader object', 'fragment', 'createShader returned null');
  }
  gl.shaderSource(fragShader, fragmentShaderSrc);
  gl.compileShader(fragShader);

  if (!gl.getShaderParameter(fragShader, gl.COMPILE_STATUS)) {
    const infoLog = gl.getShaderInfoLog(fragShader) ?? 'Unknown compile error';
    gl.deleteShader(vertShader);
    gl.deleteShader(fragShader);
    throw new GLSLCompileError(
      `Fragment shader compilation failed: ${infoLog}`,
      'fragment',
      infoLog,
    );
  }

  // 链接程序
  const program = gl.createProgram();
  if (!program) {
    gl.deleteShader(vertShader);
    gl.deleteShader(fragShader);
    throw new ShaderLinkError('Failed to create program object', 'createProgram returned null');
  }
  gl.attachShader(program, vertShader);
  gl.attachShader(program, fragShader);
  gl.linkProgram(program);

  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    const infoLog = gl.getProgramInfoLog(program) ?? 'Unknown link error';
    gl.deleteShader(vertShader);
    gl.deleteShader(fragShader);
    gl.deleteProgram(program);
    throw new ShaderLinkError(
      `Shader program link failed: ${infoLog}`,
      infoLog,
    );
  }

  // 链接成功后删除 shader 对象（程序已保留引用）
  gl.deleteShader(vertShader);
  gl.deleteShader(fragShader);

  return program;
}

// ============================================================================
// GlassRenderer 类（I1 签名匹配）
// ============================================================================

/**
 * WebGL 玻璃渲染器（I1 GlassRenderer, merged.md §2.3 Canvas 渲染管线）。
 *
 * 管理双 FBO ping-pong + 折射/色散/高光合成 + blit 到主 canvas。
 * 单 draw call 渲染同形态元素（instanced quad），目标 draw call < 20。
 *
 * 四级 tier 降级链路（强制顺序，禁止跳级）:
 *   Tier 1 WebGL2 → Tier 2 WebGL1 → Tier 3 CSS → Tier 4 solid bg
 */
export class GlassRenderer {
  /** Canvas 元素 */
  private canvas: HTMLCanvasElement;

  /** GL 上下文 */
  private gl: WebGLRenderingContext | WebGL2RenderingContext | null = null;

  /** 是否为 WebGL2 */
  private isWebGL2 = false;

  /** 当前 tier */
  private currentTier: GlassTier;

  /** 初始化选项 */
  private options: GlassRendererOptions;

  /** GPU 内存管理器 */
  private memoryManager: GPUMemoryManager | null = null;

  /** FBO 管理器 */
  private fboManager: FBOManager | null = null;

  /** 性能监控器 */
  private performanceMonitor: PerformanceMonitor | null = null;

  /** 着色器程序映射（按 tier 不同编译不同 shader 组合） */
  private shaderPrograms: Map<string, WebGLProgram> = new Map();

  /** instanced quad 缓冲 */
  private instancedBuffers: { quadBuffer: WebGLBuffer; instanceBuffer: WebGLBuffer; vertexCount: number } | null = null;

  /** uPointerPosition 30fps 节流相关 */
  private lastPointerUpdate = 0;

  /** 30fps 节流间隔（ms） */
  private readonly pointerThrottleMs = 1000 / 30;

  /** 已注册的 GL 上下文（用于模块2 主题层上传 uniform） */
  private registeredGL = false;

  /**
   * 初始化渲染器（I1 __init__）。
   *
   * @param canvas 全屏 canvas 元素（玻璃层底衬）
   * @param options 初始化选项
   * @throws GPUContextLossError canvas.getContext 返回 null 时抛出（GPU 不可用）
   * @throws FBOCreationError 双 FBO 初始化失败时抛出
   */
  constructor(canvas: HTMLCanvasElement, options: GlassRendererOptions) {
    this.canvas = canvas;
    this.options = options;
    this.currentTier = GlassTier.TIER_1; // 初始假设 Tier 1，后续由 detectTier 校正

    this.initContext();
  }

  /**
   * 初始化 GL 上下文（按 Tier 1 WebGL2 → Tier 2 WebGL1 顺序尝试）。
   */
  private initContext(): void {
    // 显式声明 gl 类型为 WebGL1/WebGL2 联合，避免 getContext('webgl2') 推断窄化导致后续赋值冲突
    let gl: WebGLRenderingContext | WebGL2RenderingContext | null = this.canvas.getContext('webgl2', {
      antialias: this.options.antialias,
      alpha: this.options.alpha,
      premultipliedAlpha: this.options.premultipliedAlpha,
      preserveDrawingBuffer: this.options.preserveDrawingBuffer,
    }) as WebGL2RenderingContext | null;

    if (gl) {
      this.isWebGL2 = true;
      this.currentTier = GlassTier.TIER_1;
    } else {
      // Tier 2: 回退到 WebGL1
      gl = this.canvas.getContext('webgl', {
        antialias: this.options.antialias,
        alpha: this.options.alpha,
        premultipliedAlpha: this.options.premultipliedAlpha,
        preserveDrawingBuffer: this.options.preserveDrawingBuffer,
      }) as WebGLRenderingContext | null;

      if (gl) {
        this.isWebGL2 = false;
        this.currentTier = GlassTier.TIER_2;
      } else {
        // WebGL 不可用，触发降级到 Tier 3
        throw new GPUContextLossError(
          'WebGL context unavailable: both webgl2 and webgl getContext returned null',
          performance.now(),
        );
      }
    }

    this.gl = gl;

    // 初始化 GPU 内存管理器
    this.memoryManager = new GPUMemoryManager(gl);

    // 初始化 FBO 管理器
    this.fboManager = new FBOManager(gl, this.memoryManager);

    // 创建双 FBO ping-pong
    const dpr = typeof window !== 'undefined' ? window.devicePixelRatio : 1;
    const width = this.canvas.width || (typeof window !== 'undefined' ? window.innerWidth : 1920);
    const height = this.canvas.height || (typeof window !== 'undefined' ? window.innerHeight : 1080);
    try {
      this.fboManager.createPingPongFBO(Math.floor(width * dpr), Math.floor(height * dpr));
    } catch (e) {
      if (e instanceof FBOCreationError) {
        throw e;
      }
      throw new FBOCreationError(
        `FBO initialization failed: ${e instanceof Error ? e.message : String(e)}`,
        'initContext',
      );
    }

    // 初始化 instanced quad 缓冲
    this.instancedBuffers = createInstancedQuadBuffer(gl);

    // 编译着色器程序
    this.compileShaders();

    // 注册 GL 上下文到模块2 主题层
    const mainProgram = this.shaderPrograms.get('main');
    if (mainProgram) {
      registerGLContext(gl, mainProgram);
      this.registeredGL = true;
    }

    // 启动上下文丢失探测（60s 间隔）
    this.memoryManager.startContextLossProbe(() => {
      this.handleContextLoss();
    });
  }

  /**
   * 编译着色器程序。
   *
   * Tier 1: 折射 + 色散 + 高光（三层完整）
   * Tier 2: 折射 + 高光（关闭色散层，不编译 dispersion.frag）
   *
   * 着色器编译失败必须降级到下一 tier，不得静默继续（闭合判据 §13）。
   */
  private compileShaders(): void {
    if (!this.gl) return;

    try {
      // 编译主着色器程序（vertex + 组合 fragment）
      // Tier 1/2 都需要折射层 + 高光层
      // Tier 1 额外需要色散层（通过 uniform 控制，不是单独 shader）
      const combinedFragment = this.combineFragmentShaders(this.currentTier);
      const program = createGlassShader(
        this.gl,
        vertexShaderSource,
        combinedFragment,
      );
      this.shaderPrograms.set('main', program);
    } catch (e) {
      if (e instanceof GLSLCompileError || e instanceof ShaderLinkError) {
        // 着色器编译失败 → 降级到下一 tier（闭合判据 §13）
        this.downgradeOnShaderFailure(e);
      } else {
        throw e;
      }
    }
  }

  /**
   * 组合 fragment shader（根据 tier 决定是否包含色散层）。
   *
   * Tier 1: 折射 + 色散 + 高光（三层完整）
   * Tier 2: 折射 + 高光（关闭色散层）
   */
  private combineFragmentShaders(tier: GlassTier): string {
    // 基础 precision 声明
    const header = `
precision highp float;
varying vec2 vUv;
varying vec2 vScreenPos;
uniform sampler2D uBackgroundTexture;
uniform sampler2D uNormalMap;
uniform vec2 uTextureSize;
`;

    // 折射层（Tier 1/2 都使用）
    const refractionPart = `
uniform float uRefractionStrength;
vec3 refractionSample(vec2 uv) {
  vec3 normal = texture2D(uNormalMap, uv).rgb * 2.0 - 1.0;
  normal = normalize(normal);
  vec3 incident = vec3(0.0, 0.0, 1.0);
  vec3 refracted = refract(incident, normal, 1.0 / 1.5);
  vec2 offset = refracted.xy * uRefractionStrength;
  return texture2D(uBackgroundTexture, uv + offset).rgb;
}
`;

    // 色散层（仅 Tier 1 使用，Tier 2 关闭）
    let dispersionPart = '';
    if (tier === GlassTier.TIER_1) {
      dispersionPart = `
uniform float uDispersionR;
uniform float uDispersionG;
uniform float uDispersionB;
vec3 dispersionSample(vec2 uv) {
  vec3 normal = texture2D(uNormalMap, uv).rgb * 2.0 - 1.0;
  normal = normalize(normal);
  vec3 incident = vec3(0.0, 0.0, 1.0);
  vec3 refracted = refract(incident, normal, 1.0 / 1.5);
  vec2 baseOffset = refracted.xy;
  float r = texture2D(uBackgroundTexture, uv + baseOffset * uDispersionR).r;
  float g = texture2D(uBackgroundTexture, uv + baseOffset * uDispersionG).g;
  float b = texture2D(uBackgroundTexture, uv + baseOffset * uDispersionB).b;
  return vec3(r, g, b);
}
`;
    }

    // 高光层（Tier 1/2 都使用）
    const highlightPart = `
uniform float uFresnelPower;
uniform vec3 uViewDirection;
uniform vec2 uPointerPosition;
uniform vec2 uScrollVelocity;
uniform float uTime;
uniform vec4 uGlassTint;
vec3 highlightSample(vec2 uv) {
  vec3 N = texture2D(uNormalMap, uv).rgb * 2.0 - 1.0;
  N = normalize(N);
  vec3 V = normalize(uViewDirection);
  float fresnel = pow(1.0 - dot(N, V), uFresnelPower);
  vec2 pointerOffset = (uPointerPosition - vec2(0.5)) * 2.0;
  float pointerInfluence = dot(N.xy, pointerOffset) * 0.3;
  float scrollInfluence = dot(N.xy, -uScrollVelocity) * 0.2;
  float timePulse = sin(uTime * 2.0) * 0.05 + 0.95;
  float highlightIntensity = (fresnel + pointerInfluence + scrollInfluence) * timePulse;
  highlightIntensity = clamp(highlightIntensity, 0.0, 1.0);
  return mix(vec3(1.0), uGlassTint.rgb, 0.3) * highlightIntensity;
}
`;

    // 主函数：组合三层
    let mainFunc: string;
    if (tier === GlassTier.TIER_1) {
      mainFunc = `
void main() {
  vec2 uv = vUv;
  vec3 refractionColor = refractionSample(uv);
  vec3 dispersionColor = dispersionSample(uv);
  vec3 highlightColor = highlightSample(uv);
  vec3 finalColor = mix(refractionColor, dispersionColor, 0.5);
  finalColor = mix(finalColor, finalColor + highlightColor, 0.6);
  gl_FragColor = vec4(finalColor, 1.0);
}
`;
    } else {
      // Tier 2: 无色散层
      mainFunc = `
void main() {
  vec2 uv = vUv;
  vec3 refractionColor = refractionSample(uv);
  vec3 highlightColor = highlightSample(uv);
  vec3 finalColor = refractionColor + highlightColor * 0.6;
  gl_FragColor = vec4(finalColor, 1.0);
}
`;
    }

    return header + refractionPart + dispersionPart + highlightPart + mainFunc;
  }

  /**
   * 着色器编译失败时降级到下一 tier（闭合判据 §13: 不得静默继续）。
   */
  private downgradeOnShaderFailure(error: GLSLCompileError | ShaderLinkError): void {
    const nextTier = getNextDowngradeTier(this.currentTier);
    if (nextTier === null) {
      // 已在 Tier 4，无法继续降级
      throw new TierDegradeError(
        `Shader compilation failed at Tier 4 and no further downgrade possible: ${error.message}`,
        this.currentTier,
        GlassTier.TIER_4,
      );
    }

    // 尝试降级到下一 tier
    this.currentTier = nextTier;

    if (nextTier >= GlassTier.TIER_3) {
      // Tier 3/4 不需要 WebGL，切换到 CSS 降级
      // 释放 GL 资源
      this.disposeGLResources();
      return;
    }

    // Tier 2: 重新编译着色器（关闭色散层）
    try {
      const combinedFragment = this.combineFragmentShaders(this.currentTier);
      if (this.gl) {
        const program = createGlassShader(this.gl, vertexShaderSource, combinedFragment);
        this.shaderPrograms.set('main', program);
      }
    } catch (e) {
      // 降级后仍失败，继续降级
      if (e instanceof GLSLCompileError || e instanceof ShaderLinkError) {
        this.downgradeOnShaderFailure(e);
      } else {
        throw e;
      }
    }
  }

  /**
   * 渲染一帧（I1 render）。
   *
   * @param frame 帧数据，含背景纹理 + 玻璃元件列表 + uniform 值
   * @throws GPUContextLossError 渲染过程中检测到上下文丢失
   * @throws GLSLCompileError shader 未编译或已被释放
   */
  render(frame: FrameData): void {
    if (!this.gl || !this.fboManager) {
      throw new GLSLCompileError('Renderer not initialized or disposed', 'fragment', 'GL context or FBO manager is null');
    }

    // 检测上下文丢失
    if (this.gl.isContextLost()) {
      throw new GPUContextLossError(
        'WebGL context lost during render',
        performance.now(),
      );
    }

    // Tier 3/4: 不使用 WebGL 渲染（由 CSS 处理）
    if (this.currentTier >= GlassTier.TIER_3) {
      return;
    }

    const gl = this.gl;
    const program = this.shaderPrograms.get('main');
    if (!program) {
      throw new GLSLCompileError('Main shader program not found', 'fragment', 'program is null');
    }

    // 上传 uniform（带类型校验）
    this.setUniforms(program, frame.uniforms);

    // 渲染到 glassFBO
    const glassFBO = this.fboManager.getGlassFBO();
    if (glassFBO) {
      gl.bindFramebuffer(gl.FRAMEBUFFER, glassFBO.framebuffer);
      gl.viewport(0, 0, glassFBO.width, glassFBO.height);
      gl.clear(gl.COLOR_BUFFER_BIT);

      // 使用 instanced quad 单 draw call 渲染所有玻璃元件
      gl.useProgram(program);
      if (this.instancedBuffers) {
        const drawCalls = drawInstancedQuads(
          gl,
          this.instancedBuffers.instanceBuffer,
          frame.instances,
        );
        // 上报 draw call 数到性能监控器
        this.performanceMonitor?.reportDrawCalls(drawCalls);
      }

      // blit glassFBO 到主 canvas
      this.fboManager.blitToMainCanvas(glassFBO);
    }

    // 上报 GPU 内存到性能监控器
    if (this.memoryManager) {
      this.performanceMonitor?.reportGpuMemory(this.memoryManager.getGpuMemoryUsageMB());
    }
  }

  /**
   * 设置 uniform（带类型校验，闭合判据 §14: uniform 在 setUniform 前必须校验类型与契约一致）。
   */
  private setUniforms(program: WebGLProgram, uniforms: GlassUniforms): void {
    if (!this.gl) return;
    const gl = this.gl;

    // 校验并设置 float 类型 uniform
    this.setFloatUniform(gl, program, 'uRefractionStrength', uniforms.uRefractionStrength, 0, 0.3);
    this.setFloatUniform(gl, program, 'uFresnelPower', uniforms.uFresnelPower, 1, 5);
    this.setFloatUniform(gl, program, 'uTime', uniforms.uTime, 0, Infinity);

    // 色散层 uniform（仅 Tier 1）
    if (this.currentTier === GlassTier.TIER_1) {
      this.setFloatUniform(gl, program, 'uDispersionR', uniforms.uDispersionR, 0, 0.15);
      this.setFloatUniform(gl, program, 'uDispersionG', uniforms.uDispersionG, 0, 0.15);
      this.setFloatUniform(gl, program, 'uDispersionB', uniforms.uDispersionB, 0, 0.15);
    }

    // uPointerPosition 30fps 节流（D2 dynamicLighting.uPointerPosition.throttleFps = 30）
    const now = performance.now();
    if (now - this.lastPointerUpdate >= this.pointerThrottleMs) {
      this.setVec2Uniform(gl, program, 'uPointerPosition', uniforms.uPointerPosition);
      this.lastPointerUpdate = now;
    }

    // uScrollVelocity（滚动速度驱动高光偏移）
    this.setVec2Uniform(gl, program, 'uScrollVelocity', uniforms.uScrollVelocity);

    // uGlassTint（玻璃着色，来自模块2 主题层）
    this.setVec4Uniform(gl, program, 'uGlassTint', uniforms.uGlassTint);

    // uViewDirection（视线方向，默认 [0, 0, 1]）
    const viewDirLoc = gl.getUniformLocation(program, 'uViewDirection');
    if (viewDirLoc) {
      gl.uniform3f(viewDirLoc, 0, 0, 1);
    }
  }

  /**
   * 设置 float uniform（带范围校验）。
   */
  private setFloatUniform(
    gl: WebGLRenderingContext | WebGL2RenderingContext,
    program: WebGLProgram,
    name: string,
    value: number,
    min: number,
    max: number,
  ): void {
    // 校验类型与范围（闭合判据 §14）
    if (typeof value !== 'number' || isNaN(value)) {
      throw new Error(`Uniform '${name}' type mismatch: expected number, got ${typeof value}`);
    }
    if (value < min || value > max) {
      throw new Error(`Uniform '${name}' out of range: ${value} not in [${min}, ${max}]`);
    }
    const loc = gl.getUniformLocation(program, name);
    if (loc) {
      gl.uniform1f(loc, value);
    }
  }

  /**
   * 设置 vec2 uniform（带类型校验）。
   */
  private setVec2Uniform(
    gl: WebGLRenderingContext | WebGL2RenderingContext,
    program: WebGLProgram,
    name: string,
    value: [number, number],
  ): void {
    if (!Array.isArray(value) || value.length !== 2) {
      throw new Error(`Uniform '${name}' type mismatch: expected vec2, got ${typeof value}`);
    }
    const loc = gl.getUniformLocation(program, name);
    if (loc) {
      gl.uniform2f(loc, value[0], value[1]);
    }
  }

  /**
   * 设置 vec4 uniform（带类型校验）。
   */
  private setVec4Uniform(
    gl: WebGLRenderingContext | WebGL2RenderingContext,
    program: WebGLProgram,
    name: string,
    value: [number, number, number, number],
  ): void {
    if (!Array.isArray(value) || value.length !== 4) {
      throw new Error(`Uniform '${name}' type mismatch: expected vec4, got ${typeof value}`);
    }
    const loc = gl.getUniformLocation(program, name);
    if (loc) {
      gl.uniform4f(loc, value[0], value[1], value[2], value[3]);
    }
  }

  /**
   * 处理 GPU 上下文丢失（FE-GLA-002）。
   * 降级到 Tier 3 并释放资源。
   */
  private handleContextLoss(): void {
    this.currentTier = GlassTier.TIER_3;
    this.disposeGLResources();
  }

  /**
   * 释放 GL 资源（内部方法）。
   */
  private disposeGLResources(): void {
    if (this.memoryManager) {
      const framebuffers: WebGLFramebuffer[] = [];
      const textures: WebGLTexture[] = [];
      if (this.fboManager) {
        const bgFBO = this.fboManager.getBackgroundFBO();
        const glassFBO = this.fboManager.getGlassFBO();
        if (bgFBO) {
          framebuffers.push(bgFBO.framebuffer);
          textures.push(bgFBO.texture);
        }
        if (glassFBO) {
          framebuffers.push(glassFBO.framebuffer);
          textures.push(glassFBO.texture);
        }
      }
      const programs = Array.from(this.shaderPrograms.values());
      this.memoryManager.cleanup(framebuffers, programs, textures);
    }

    if (this.fboManager) {
      this.fboManager.dispose();
    }

    this.shaderPrograms.clear();
    this.instancedBuffers = null;

    // 注销 GL 上下文
    if (this.registeredGL) {
      unregisterGLContext();
      this.registeredGL = false;
    }

    this.gl = null;
  }

  /**
   * 释放 GPU 资源（I1 dispose）。
   *
   * 调用 gl.deleteFramebuffer / gl.deleteProgram / gl.deleteTexture 显式释放。
   */
  dispose(): void {
    this.disposeGLResources();
  }

  /**
   * 获取 GPU 上下文丢失状态（I1 getContextLossStatus）。
   *
   * @returns 上下文丢失状态
   */
  getContextLossStatus() {
    if (this.memoryManager) {
      return this.memoryManager.getContextLossStatus();
    }
    return {
      isLost: false,
      lastCheckTime: 0,
      recoveredTier: null,
    };
  }

  /**
   * 获取当前 tier。
   */
  getCurrentTier(): GlassTier {
    return this.currentTier;
  }

  /**
   * 获取当前是否使用 WebGL2 上下文（供性能监控与调试使用）。
   *
   * WebGL2 支持 textureLod / instanced rendering 原生扩展，
   * WebGL1 需依赖 ANGLE_instanced_arrays 扩展（由 createInstancedQuadBuffer 处理）。
   */
  isUsingWebGL2(): boolean {
    return this.isWebGL2;
  }

  /**
   * 设置性能监控器（供 useGlassTier 注入）。
   */
  setPerformanceMonitor(monitor: PerformanceMonitor): void {
    this.performanceMonitor = monitor;
  }

  /**
   * 降级到指定 tier（强制顺序，禁止跳级）。
   *
   * @param targetTier 目标 tier
   * @throws TierDegradeError 降级失败时抛出
   */
  downgradeTo(targetTier: GlassTier): void {
    // 校验降级顺序（禁止跳级）
    const nextTier = getNextDowngradeTier(this.currentTier);
    if (nextTier === null || targetTier > nextTier) {
      throw new TierDegradeError(
        `Cannot downgrade from Tier ${this.currentTier} to Tier ${targetTier}: must follow sequential order`,
        this.currentTier,
        targetTier,
      );
    }

    this.currentTier = targetTier;

    // Tier 3/4: 释放 GL 资源
    if (targetTier >= GlassTier.TIER_3) {
      this.disposeGLResources();
    }
  }
}
