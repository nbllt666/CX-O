/*
 * liquid-glass.frag — Liquid Glass 片段着色器（WebGL 主体）
 * ============================================================================
 * 用途: 渲染全屏液态玻璃效果
 *   - 程序化背景（粉紫青渐变 + 噪声）
 *   - 玻璃区域折射/色散/高光（DOM 扫描位置传入）
 *   - 全局动态光影（指针光斑 + 流动光带）
 *
 * Uniforms:
 *   - uTime: 时间（秒）
 *   - uPointer: 指针位置 [0,1]
 *   - uScrollVelocity: 滚动速度 vec2
 *   - uTint: 主题着色（粉紫青）
 *   - uIntensity: 全局强度（reduced-motion 时为 0）
 *   - uGlassElements[8]: 玻璃区域 x,y,w,h（NDC）
 *   - uGlassCount: 玻璃区域数量
 * ============================================================================
 */

precision highp float;

varying vec2 vUv;
varying vec2 vScreenPos;

uniform float uTime;
uniform vec2  uPointer;
uniform vec2  uScrollVelocity;
uniform vec3  uTint;
uniform float uIntensity;
uniform vec4  uGlassElements[8];
uniform int   uGlassCount;

// ============================================================================
// 简易噪声（避免纹理依赖）
// ============================================================================

float hash(vec2 p) {
  return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
}

float noise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  float a = hash(i);
  float b = hash(i + vec2(1.0, 0.0));
  float c = hash(i + vec2(0.0, 1.0));
  float d = hash(i + vec2(1.0, 1.0));
  vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(a, b, u.x) + (c - a) * u.y * (1.0 - u.x) + (d - b) * u.x * u.y;
}

// ============================================================================
// 程序化背景（粉紫青渐变 + 噪声）
// ============================================================================

vec3 sampleBackground(vec2 uv) {
  // 垂直渐变：顶部深紫 → 底部深蓝
  vec3 top = vec3(0.12, 0.08, 0.22);     // 深紫
  vec3 bottom = vec3(0.05, 0.06, 0.15);  // 深蓝
  vec3 grad = mix(bottom, top, uv.y);

  // 加入噪声纹理（模拟环境光变化）
  float n = noise(uv * 8.0 + uTime * 0.05) * 0.03;
  return grad + n;
}

// ============================================================================
// 判断像素是否在某个玻璃区域内
// ============================================================================

bool isInGlassRegion(vec2 screenPos, out vec2 elementCenter, out vec2 elementSize) {
  for (int i = 0; i < 8; i++) {
    if (i >= uGlassCount) break;
    vec4 elem = uGlassElements[i];
    vec2 center = elem.xy;
    vec2 halfSize = elem.zw * 0.5;
    if (all(greaterThanEqual(screenPos, center - halfSize)) &&
        all(lessThanEqual(screenPos, center + halfSize))) {
      elementCenter = center;
      elementSize = elem.zw;
      return true;
    }
  }
  return false;
}

// ============================================================================
// 主函数
// ============================================================================

void main() {
  vec2 uv = vUv;
  vec2 screenPos = vScreenPos;

  // 1. 基础背景
  vec3 bgColor = sampleBackground(uv);

  // 2. 玻璃区域处理
  vec2 elemCenter = vec2(0.0);
  vec2 elemSize = vec2(0.0);
  bool inGlass = isInGlassRegion(screenPos, elemCenter, elemSize);

  vec3 finalColor = bgColor;
  float alpha = 1.0;

  if (inGlass) {
    // 玻璃区域内：折射 + 色散 + 高光

    // 折射：偏移背景采样坐标（中心偏折弱，边缘偏折强）
    vec2 toCenter = (screenPos - elemCenter) / max(elemSize, vec2(0.01));
    float distortion = 0.08 * (1.0 - length(toCenter));
    vec2 refractUv = uv + toCenter * distortion;

    // 色散：RGB 通道不同偏移（模拟色差边缘）
    float r = sampleBackground(refractUv + vec2(0.003, 0.0)).r;
    float g = sampleBackground(refractUv).g;
    float b = sampleBackground(refractUv - vec2(0.003, 0.0)).b;
    vec3 refractedColor = vec3(r, g, b);

    // Fresnel 高光（边缘亮）
    float edge = max(abs(toCenter.x), abs(toCenter.y));
    float fresnel = pow(edge, 3.0) * 0.6;

    // 顶部光带（光从上方洒下，iOS 26 标志性效果）
    float topLight = pow(1.0 - (screenPos.y - (elemCenter.y - elemSize.y * 0.5)) / max(elemSize.y, 0.01), 4.0) * 0.3;

    // 玻璃着色（粉紫青体系）
    vec3 tinted = mix(refractedColor, uTint, 0.08);

    finalColor = tinted + fresnel + topLight;
    alpha = 0.85;
  }

  // 3. 全局动态光影
  // 指针光斑（柔和的二次元光晕）
  vec2 toPointer = vUv - uPointer;
  float pointerGlow = exp(-length(toPointer) * 8.0) * 0.15 * uIntensity;
  finalColor += uTint * pointerGlow;

  // 流动光带（模拟环境光在玻璃面的流动）
  vec2 bandUv = vUv + vec2(uTime * 0.02, uTime * 0.015) + uScrollVelocity * 0.3;
  float band = noise(bandUv * 4.0) * 0.04 * uIntensity;
  finalColor += vec3(band);

  gl_FragColor = vec4(finalColor, alpha);
}
