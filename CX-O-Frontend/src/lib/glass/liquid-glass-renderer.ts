/**
 * liquid-glass-renderer.ts — Liquid Glass WebGL 渲染器（核心，简化版）
 * ============================================================================
 * 用途: 全屏 quad 单 draw call 渲染液态玻璃效果
 *
 * 与原 glass-renderer.ts（750 LOC）的关键差异:
 *   - ✅ 正确调用 vertexAttribPointer + enableVertexAttribArray（原代码完全缺失）
 *   - ✅ 单 draw call 全屏渲染（无需 instanced quad / 双 FBO / 纹理绑定）
 *   - ✅ 程序化背景生成（无需 DOM-to-texture / html2canvas）
 *   - ✅ 玻璃区域位置通过 uniform array 传入（无需 DOM 离屏渲染）
 *
 * 降级链路:
 *   - WebGL2 不可用 → 尝试 WebGL1 → 失败抛 GPUContextLossError
 *   - Shader 编译失败 → 抛 GLSLCompileError
 *   - 运行时上下文丢失 → isContextLost() 返回 true
 * ============================================================================
 */

import vertexShaderSource from './shaders/liquid-glass.vert?raw';
import fragmentShaderSource from './shaders/liquid-glass.frag?raw';

// ============================================================================
// 异常定义
// ============================================================================

export class GPUContextLossError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'GPUContextLossError';
    Object.setPrototypeOf(this, GPUContextLossError.prototype);
  }
}

export class GLSLCompileError extends Error {
  readonly shaderType: 'vertex' | 'fragment';
  readonly infoLog: string;

  constructor(message: string, shaderType: 'vertex' | 'fragment', infoLog: string) {
    super(message);
    this.name = 'GLSLCompileError';
    this.shaderType = shaderType;
    this.infoLog = infoLog;
    Object.setPrototypeOf(this, GLSLCompileError.prototype);
  }
}

// ============================================================================
// 类型定义
// ============================================================================

/** 玻璃元素矩形（NDC 坐标） */
export interface GlassElementRect {
  /** 中心 x（NDC [-1, 1]） */
  x: number;
  /** 中心 y（NDC [-1, 1]） */
  y: number;
  /** 宽度（NDC） */
  w: number;
  /** 高度（NDC） */
  h: number;
}

/** 渲染 uniform 值 */
export interface GlassUniforms {
  /** 时间（秒） */
  uTime: number;
  /** 指针位置 [0,1] */
  uPointer: [number, number];
  /** 滚动速度 */
  uScrollVelocity: [number, number];
  /** 主题着色 RGB（0-1） */
  uTint: [number, number, number];
  /** 全局强度（0-1，reduced-motion 时为 0） */
  uIntensity: number;
}

// ============================================================================
// 常量
// ============================================================================

/** 玻璃元素最大数量（shader 中 uGlassElements[8]） */
const MAX_GLASS_ELEMENTS = 8;

// ============================================================================
// LiquidGlassRenderer 类
// ============================================================================

export class LiquidGlassRenderer {
  private canvas: HTMLCanvasElement;
  private gl: WebGLRenderingContext | WebGL2RenderingContext | null = null;
  private isWebGL2 = false;
  private program: WebGLProgram | null = null;
  private quadBuffer: WebGLBuffer | null = null;

  // 顶点属性 location
  private aPositionLoc = -1;
  private aTexCoordLoc = -1;

  // uniform location
  private uniforms: Record<string, WebGLUniformLocation | null> = {};

  constructor(canvas: HTMLCanvasElement) {
    this.canvas = canvas;
    this.initContext();
    this.compileShaders();
    this.initBuffers();
    this.cacheUniformLocations();
  }

  /**
   * 初始化 GL 上下文（WebGL2 → WebGL1 降级）。
   */
  private initContext(): void {
    let gl: WebGLRenderingContext | WebGL2RenderingContext | null =
      this.canvas.getContext('webgl2', {
        antialias: true,
        alpha: true,
        premultipliedAlpha: false,
        preserveDrawingBuffer: false,
      }) as WebGL2RenderingContext | null;

    if (gl) {
      this.isWebGL2 = true;
    } else {
      gl = this.canvas.getContext('webgl', {
        antialias: true,
        alpha: true,
        premultipliedAlpha: false,
        preserveDrawingBuffer: false,
      }) as WebGLRenderingContext | null;

      if (!gl) {
        throw new GPUContextLossError(
          'WebGL context unavailable: both webgl2 and webgl getContext returned null',
        );
      }
      this.isWebGL2 = false;
    }

    this.gl = gl;

    // 启用混合
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
  }

  /**
   * 编译着色器程序。
   */
  private compileShaders(): void {
    if (!this.gl) return;

    const gl = this.gl;

    // 编译 vertex shader
    const vertShader = gl.createShader(gl.VERTEX_SHADER);
    if (!vertShader) {
      throw new GLSLCompileError('Failed to create vertex shader', 'vertex', 'createShader returned null');
    }
    gl.shaderSource(vertShader, vertexShaderSource);
    gl.compileShader(vertShader);

    if (!gl.getShaderParameter(vertShader, gl.COMPILE_STATUS)) {
      const infoLog = gl.getShaderInfoLog(vertShader) ?? 'Unknown compile error';
      gl.deleteShader(vertShader);
      throw new GLSLCompileError(`Vertex shader compilation failed: ${infoLog}`, 'vertex', infoLog);
    }

    // 编译 fragment shader
    const fragShader = gl.createShader(gl.FRAGMENT_SHADER);
    if (!fragShader) {
      gl.deleteShader(vertShader);
      throw new GLSLCompileError('Failed to create fragment shader', 'fragment', 'createShader returned null');
    }
    gl.shaderSource(fragShader, fragmentShaderSource);
    gl.compileShader(fragShader);

    if (!gl.getShaderParameter(fragShader, gl.COMPILE_STATUS)) {
      const infoLog = gl.getShaderInfoLog(fragShader) ?? 'Unknown compile error';
      gl.deleteShader(vertShader);
      gl.deleteShader(fragShader);
      throw new GLSLCompileError(`Fragment shader compilation failed: ${infoLog}`, 'fragment', infoLog);
    }

    // 链接程序
    const program = gl.createProgram();
    if (!program) {
      gl.deleteShader(vertShader);
      gl.deleteShader(fragShader);
      throw new GLSLCompileError('Failed to create program', 'fragment', 'createProgram returned null');
    }
    gl.attachShader(program, vertShader);
    gl.attachShader(program, fragShader);
    gl.linkProgram(program);

    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      const infoLog = gl.getProgramInfoLog(program) ?? 'Unknown link error';
      gl.deleteShader(vertShader);
      gl.deleteShader(fragShader);
      gl.deleteProgram(program);
      throw new GLSLCompileError(`Shader program link failed: ${infoLog}`, 'fragment', infoLog);
    }

    // 链接成功后删除 shader 对象
    gl.deleteShader(vertShader);
    gl.deleteShader(fragShader);

    this.program = program;
  }

  /**
   * 初始化全屏 quad 顶点缓冲。
   *
   * 关键修复：正确设置 vertexAttribPointer + enableVertexAttribArray
   * （原 draw-element.ts 完全缺失这两步，导致顶点数据无法进入 GPU）
   */
  private initBuffers(): void {
    if (!this.gl || !this.program) return;

    const gl = this.gl;

    // 全屏 quad 顶点（两个三角形，6 个顶点）
    // 每个顶点 4 个 float：position(x,y) + texCoord(u,v)
    const quadVertices = new Float32Array([
      // position    // texCoord
      -1, -1,        0, 0,
       1, -1,        1, 0,
      -1,  1,        0, 1,
      -1,  1,        0, 1,
       1, -1,        1, 0,
       1,  1,        1, 1,
    ]);

    this.quadBuffer = gl.createBuffer();
    if (!this.quadBuffer) {
      throw new GLSLCompileError('Failed to create quad buffer', 'vertex', 'createBuffer returned null');
    }

    gl.bindBuffer(gl.ARRAY_BUFFER, this.quadBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, quadVertices, gl.STATIC_DRAW);

    // 获取顶点属性 location
    this.aPositionLoc = gl.getAttribLocation(this.program, 'aPosition');
    this.aTexCoordLoc = gl.getAttribLocation(this.program, 'aTexCoord');

    // ✅ 关键修复：设置顶点属性指针（原代码完全缺失）
    if (this.aPositionLoc >= 0) {
      gl.enableVertexAttribArray(this.aPositionLoc);
      gl.vertexAttribPointer(this.aPositionLoc, 2, gl.FLOAT, false, 16, 0);
    }

    if (this.aTexCoordLoc >= 0) {
      gl.enableVertexAttribArray(this.aTexCoordLoc);
      gl.vertexAttribPointer(this.aTexCoordLoc, 2, gl.FLOAT, false, 16, 8);
    }
  }

  /**
   * 缓存 uniform location（避免每帧查询）。
   */
  private cacheUniformLocations(): void {
    if (!this.gl || !this.program) return;

    const gl = this.gl;
    const uniformNames = [
      'uTime',
      'uPointer',
      'uScrollVelocity',
      'uTint',
      'uIntensity',
      'uGlassElements',
      'uGlassCount',
    ];

    for (const name of uniformNames) {
      this.uniforms[name] = gl.getUniformLocation(this.program, name);
    }
  }

  /**
   * 渲染一帧。
   *
   * @param elements 玻璃元素列表（NDC 坐标）
   * @param uniforms uniform 值
   */
  render(elements: GlassElementRect[], uniforms: GlassUniforms): void {
    if (!this.gl || !this.program) return;

    const gl = this.gl;

    // 检测上下文丢失
    if (this.isContextLost()) {
      throw new GPUContextLossError('WebGL context lost during render');
    }

    // 设置视口
    gl.viewport(0, 0, this.canvas.width, this.canvas.height);

    // 清空
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);

    // 使用着色器程序
    gl.useProgram(this.program);

    // 确保顶点属性绑定（防止其他代码干扰）
    gl.bindBuffer(gl.ARRAY_BUFFER, this.quadBuffer);
    if (this.aPositionLoc >= 0) {
      gl.enableVertexAttribArray(this.aPositionLoc);
      gl.vertexAttribPointer(this.aPositionLoc, 2, gl.FLOAT, false, 16, 0);
    }
    if (this.aTexCoordLoc >= 0) {
      gl.enableVertexAttribArray(this.aTexCoordLoc);
      gl.vertexAttribPointer(this.aTexCoordLoc, 2, gl.FLOAT, false, 16, 8);
    }

    // 上传 uniform
    this.setUniform1f('uTime', uniforms.uTime);
    this.setUniform2f('uPointer', uniforms.uPointer);
    this.setUniform2f('uScrollVelocity', uniforms.uScrollVelocity);
    this.setUniform3f('uTint', uniforms.uTint);
    this.setUniform1f('uIntensity', uniforms.uIntensity);

    // 上传玻璃元素（最多 MAX_GLASS_ELEMENTS 个）
    const count = Math.min(elements.length, MAX_GLASS_ELEMENTS);
    const elementData = new Float32Array(MAX_GLASS_ELEMENTS * 4);
    for (let i = 0; i < count; i++) {
      const elem = elements[i];
      elementData[i * 4] = elem.x;
      elementData[i * 4 + 1] = elem.y;
      elementData[i * 4 + 2] = elem.w;
      elementData[i * 4 + 3] = elem.h;
    }

    const glassElementsLoc = this.uniforms['uGlassElements'];
    if (glassElementsLoc) {
      gl.uniform4fv(glassElementsLoc, elementData);
    }

    const glassCountLoc = this.uniforms['uGlassCount'];
    if (glassCountLoc) {
      gl.uniform1i(glassCountLoc, count);
    }

    // 单 draw call 渲染全屏 quad
    gl.drawArrays(gl.TRIANGLES, 0, 6);
  }

  /**
   * 设置 float uniform。
   */
  private setUniform1f(name: string, value: number): void {
    if (!this.gl) return;
    const loc = this.uniforms[name];
    if (loc) {
      this.gl.uniform1f(loc, value);
    }
  }

  /**
   * 设置 vec2 uniform。
   */
  private setUniform2f(name: string, value: [number, number]): void {
    if (!this.gl) return;
    const loc = this.uniforms[name];
    if (loc) {
      this.gl.uniform2f(loc, value[0], value[1]);
    }
  }

  /**
   * 设置 vec3 uniform。
   */
  private setUniform3f(name: string, value: [number, number, number]): void {
    if (!this.gl) return;
    const loc = this.uniforms[name];
    if (loc) {
      this.gl.uniform3f(loc, value[0], value[1], value[2]);
    }
  }

  /**
   * 调整 canvas 尺寸（DPR 适配）。
   */
  resize(width: number, height: number): void {
    const dpr = typeof window !== 'undefined' ? window.devicePixelRatio : 1;
    this.canvas.width = Math.floor(width * dpr);
    this.canvas.height = Math.floor(height * dpr);
  }

  /**
   * 检测上下文是否丢失。
   */
  isContextLost(): boolean {
    if (!this.gl) return true;
    return this.gl.isContextLost();
  }

  /**
   * 是否使用 WebGL2。
   */
  isUsingWebGL2(): boolean {
    return this.isWebGL2;
  }

  /**
   * 释放资源。
   */
  dispose(): void {
    if (!this.gl) return;

    if (this.quadBuffer) {
      this.gl.deleteBuffer(this.quadBuffer);
      this.quadBuffer = null;
    }

    if (this.program) {
      this.gl.deleteProgram(this.program);
      this.program = null;
    }

    this.gl = null;
  }
}
