import { VRM, VRMExpressionPresetName } from '@pixiv/three-vrm';

export interface VowelWeights {
  a: number;
  i: number;
  u: number;
  e: number;
  o: number;
}

export class VRMLipSync {
  private vrm: VRM | null = null;
  private currentWeights: VowelWeights = { a: 0, i: 0, u: 0, e: 0, o: 0 };
  private targetWeights: VowelWeights = { a: 0, i: 0, u: 0, e: 0, o: 0 };
  private smoothingFactor = 0.3;

  bindVRM(vrm: VRM): void {
    this.vrm = vrm;
  }

  setSmoothing(factor: number): void {
    this.smoothingFactor = Math.max(0.01, Math.min(1, factor));
  }

  updateWeights(weights: VowelWeights): void {
    this.targetWeights = weights;
  }

  update(deltaTime: number): void {
    if (!this.vrm) return;
    const em = this.vrm.expressionManager;
    if (!em) return;

    // Smooth interpolation
    const s = Math.min(1, this.smoothingFactor * deltaTime * 60);
    this.currentWeights.a += (this.targetWeights.a - this.currentWeights.a) * s;
    this.currentWeights.i += (this.targetWeights.i - this.currentWeights.i) * s;
    this.currentWeights.u += (this.targetWeights.u - this.currentWeights.u) * s;
    this.currentWeights.e += (this.targetWeights.e - this.currentWeights.e) * s;
    this.currentWeights.o += (this.targetWeights.o - this.currentWeights.o) * s;

    // Apply to VRM BlendShapes
    em.setValue(VRMExpressionPresetName.Aa, this.currentWeights.a);
    em.setValue(VRMExpressionPresetName.Ih, this.currentWeights.i);
    em.setValue(VRMExpressionPresetName.Ou, this.currentWeights.u);
    em.setValue(VRMExpressionPresetName.Ee, this.currentWeights.e);
    em.setValue(VRMExpressionPresetName.Oh, this.currentWeights.o);
  }

  reset(): void {
    this.currentWeights = { a: 0, i: 0, u: 0, e: 0, o: 0 };
    this.targetWeights = { a: 0, i: 0, u: 0, e: 0, o: 0 };
    if (!this.vrm) return;
    const em = this.vrm.expressionManager;
    if (!em) return;
    em.setValue(VRMExpressionPresetName.Aa, 0);
    em.setValue(VRMExpressionPresetName.Ih, 0);
    em.setValue(VRMExpressionPresetName.Ou, 0);
    em.setValue(VRMExpressionPresetName.Ee, 0);
    em.setValue(VRMExpressionPresetName.Oh, 0);
  }
}
