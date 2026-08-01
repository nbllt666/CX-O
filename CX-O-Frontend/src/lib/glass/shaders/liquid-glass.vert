/*
 * liquid-glass.vert — Liquid Glass 顶点着色器（WebGL 主体）
 * ============================================================================
 * 用途: 全屏 quad 顶点着色，输出 vUv（纹理坐标）与 vScreenPos（屏幕空间坐标）
 *
 * 设计要点:
 *   - aPosition: quad 顶点位置（NDC 坐标 [-1, 1]）
 *   - aTexCoord: 纹理坐标 [0, 1]
 *   - vUv: 传递给 fragment 的纹理坐标（用于背景采样）
 *   - vScreenPos: 屏幕空间坐标（用于玻璃区域判定）
 *   - 全屏 quad 不需要投影矩阵（NDC 坐标直接输出）
 * ============================================================================
 */

attribute vec2 aPosition;
attribute vec2 aTexCoord;

varying vec2 vUv;
varying vec2 vScreenPos;

void main() {
  vUv = aTexCoord;
  vScreenPos = aPosition;
  gl_Position = vec4(aPosition, 0.0, 1.0);
}
