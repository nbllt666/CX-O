/**
 * BlendShape 插值器：驱动层（L2 指令）写入的目标权重经指数平滑过渡到表情。
 *
 * 分层管线中的定位（见 vrmEngine.ts startRuntimeLoop 的 L0→L3 注释）：
 * - L2 指令：setBlendShapes 通过 setExpression 写入目标权重（override / additive）
 * - L3 平滑：update 以 lerpSpeed=5.0 把 currentWeights 指数趋近 targetWeights，
 *   残差 <0.001 时直接归位，随后写入 vrm.expressionManager。
 *
 * fadeOutUnusedExpressions 用于把已退出活跃集合的表情目标置 0，
 * 由后续 update 平滑归零，避免瞬时跳变。
 */
export class BlendShapeInterpolator {
  private targetWeights: Record<string, number> = {};
  private currentWeights: Record<string, number> = {};

  setExpression(
    name: string,
    value: number,
    priority: 'override' | 'additive' = 'override',
  ): void {
    if (priority === 'override') {
      this.targetWeights[name] = Math.min(Math.max(value, 0), 1);
    } else {
      this.targetWeights[name] = Math.min(1, (this.targetWeights[name] || 0) + value);
    }
  }

  fadeOutUnusedExpressions(active: string[]): void {
    const activeSet = new Set(active);
    for (const key of Object.keys(this.targetWeights)) {
      if (!activeSet.has(key)) {
        this.targetWeights[key] = 0;
      }
    }
  }

  update(dt: number, vrm: import('@pixiv/three-vrm').VRM): void {
    const lerpSpeed = 5.0;
    const em = vrm.expressionManager;
    if (!em) return;

    for (const name of Object.keys(this.targetWeights)) {
      const target = this.targetWeights[name];
      const current = this.currentWeights[name] || 0;
      let next = current + (target - current) * Math.min(1, lerpSpeed * dt);
      if (Math.abs(target - next) < 0.001) {
        next = target;
      }
      em.setValue(name as any, next);
      this.currentWeights[name] = next;
    }
  }

  reset(): void {
    this.targetWeights = {};
    this.currentWeights = {};
  }
}
