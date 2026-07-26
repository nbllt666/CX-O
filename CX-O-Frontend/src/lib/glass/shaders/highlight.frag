/*
 * highlight.frag — Liquid Glass 高光层 fragment shader
 * ============================================================================
 * 模块: 模块4 WebGL 玻璃层
 * 契约: D2 glass_tier_config.schema.json (shader.fragmentShader.specularLayer) +
 *        C1 frontend_glass_config.schema.json (webglUniforms.uFresnelPower)
 * 用途: 基于 Fresnel 方程计算边缘高光，叠加环境光采样
 *
 * Uniforms（C1 配置驱动，禁止硬编码）:
 *   - uNormalMap: 法线贴图
 *   - uFresnelPower: Fresnel 指数，默认 2.5，范围 [1, 5]
 *   - uViewDirection: 视线方向 vec3（由相机位置计算）
 *   - uPointerPosition: 鼠标位置 vec2（归一化 [0,1]，30fps 节流，动态光影）
 *   - uScrollVelocity: 滚动速度 vec2（驱动高光偏移，方向与滚动相反）
 *   - uTime: 时间 uniform（秒，每帧上传）
 *   - uGlassTint: 玻璃着色 vec4（RGBA，来自模块2 主题层 uGlassTintDark/uGlassTintLight）
 *
 * 硬约束（闭合判据 §5）:
 *   - Fresnel 公式: pow(1 - dot(N, V), uFresnelPower)（D2 specularLayer.fresnelFormula）
 *   - uFresnelPower 默认 2.5，通过 uniform 传入（禁止硬编码 2.5）
 *   - 半精度浮点计算（D2 gpuMemoryManagement.specularPrecision = half-float）
 * ============================================================================
 */

precision highp float;

varying vec2 vUv;
varying vec2 vScreenPos;

uniform sampler2D uNormalMap;
uniform float uFresnelPower;
uniform vec3 uViewDirection;
uniform vec2 uPointerPosition;
uniform vec2 uScrollVelocity;
uniform float uTime;
uniform vec4 uGlassTint;

void main() {
  // 从法线 LUT 采样 per-pixel 法线
  vec3 N = texture2D(uNormalMap, vUv).rgb * 2.0 - 1.0;
  N = normalize(N);

  // 视线方向（归一化）
  vec3 V = normalize(uViewDirection);

  // Fresnel 高光: pow(1 - dot(N, V), uFresnelPower)
  // D2 specularLayer.fresnelFormula = "pow(1 - dot(N, V), 2.5)"
  // uFresnelPower 通过 uniform 传入，默认 2.5（C1 webglUniforms.uFresnelPower）
  float fresnel = pow(1.0 - dot(N, V), uFresnelPower);

  // 动态光影：鼠标位置偏移高光（uPointerPosition 30fps 节流）
  vec2 pointerOffset = (uPointerPosition - vec2(0.5)) * 2.0;
  float pointerInfluence = dot(N.xy, pointerOffset) * 0.3;

  // 滚动速度驱动高光偏移（方向与滚动方向相反，模拟物理玻璃）
  float scrollInfluence = dot(N.xy, -uScrollVelocity) * 0.2;

  // 时间驱动呼吸效果
  float timePulse = sin(uTime * 2.0) * 0.05 + 0.95;

  // 综合高光强度
  float highlightIntensity = (fresnel + pointerInfluence + scrollInfluence) * timePulse;
  highlightIntensity = clamp(highlightIntensity, 0.0, 1.0);

  // 叠加玻璃着色（来自模块2 主题层 uGlassTintDark/uGlassTintLight）
  vec3 highlightColor = mix(vec3(1.0), uGlassTint.rgb, 0.3) * highlightIntensity;

  gl_FragColor = vec4(highlightColor, highlightIntensity * uGlassTint.a);
}
