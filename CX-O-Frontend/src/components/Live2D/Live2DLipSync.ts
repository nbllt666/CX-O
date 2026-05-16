import type { Live2DModel } from 'pixi-live2d-display';

export interface VowelWeights {
  a: number;
  i: number;
  u: number;
  e: number;
  o: number;
}

export class Live2DLipSync {
  private model: Live2DModel | null = null;
  private currentWeights: VowelWeights = { a: 0, i: 0, u: 0, e: 0, o: 0 };
  private targetWeights: VowelWeights = { a: 0, i: 0, u: 0, e: 0, o: 0 };
  private smoothingFactor = 0.3;

  bindModel(model: Live2DModel): void {
    this.model = model;
  }

  setSmoothing(factor: number): void {
    this.smoothingFactor = Math.max(0.01, Math.min(1, factor));
  }

  updateWeights(weights: VowelWeights): void {
    this.targetWeights = weights;
  }

  update(deltaTime: number): void {
    if (!this.model) return;
    const coreModel = this.model.internalModel?.coreModel as Record<string, unknown> | undefined;
    if (!coreModel) return;

    // Smooth interpolation
    const s = Math.min(1, this.smoothingFactor * deltaTime * 60);
    this.currentWeights.a += (this.targetWeights.a - this.currentWeights.a) * s;
    this.currentWeights.i += (this.targetWeights.i - this.currentWeights.i) * s;
    this.currentWeights.u += (this.targetWeights.u - this.currentWeights.u) * s;
    this.currentWeights.e += (this.targetWeights.e - this.currentWeights.e) * s;
    this.currentWeights.o += (this.targetWeights.o - this.currentWeights.o) * s;

    const setParam = (id: string, value: number) => {
      if (typeof coreModel.setParameterValueById === 'function') {
        (coreModel.setParameterValueById as (id: string, value: number) => void)(id, value);
      } else if (typeof coreModel.setParameterValue === 'function') {
        const getIndex = coreModel.getParameterIndex as ((name: string) => number) | undefined;
        const idx = getIndex?.(id);
        if (idx !== undefined && idx >= 0) {
          (coreModel.setParameterValue as (index: number, value: number) => void)(idx, value);
        }
      }
    };

    setParam('ParamMouthA', this.currentWeights.a);
    setParam('ParamMouthI', this.currentWeights.i);
    setParam('ParamMouthU', this.currentWeights.u);
    setParam('ParamMouthE', this.currentWeights.e);
    setParam('ParamMouthO', this.currentWeights.o);
  }

  reset(): void {
    this.currentWeights = { a: 0, i: 0, u: 0, e: 0, o: 0 };
    this.targetWeights = { a: 0, i: 0, u: 0, e: 0, o: 0 };
    if (!this.model) return;
    const coreModel = this.model.internalModel?.coreModel as Record<string, unknown> | undefined;
    if (!coreModel) return;

    const setParam = (id: string, value: number) => {
      if (typeof coreModel.setParameterValueById === 'function') {
        (coreModel.setParameterValueById as (id: string, value: number) => void)(id, value);
      } else if (typeof coreModel.setParameterValue === 'function') {
        const getIndex = coreModel.getParameterIndex as ((name: string) => number) | undefined;
        const idx = getIndex?.(id);
        if (idx !== undefined && idx >= 0) {
          (coreModel.setParameterValue as (index: number, value: number) => void)(idx, value);
        }
      }
    };

    setParam('ParamMouthA', 0);
    setParam('ParamMouthI', 0);
    setParam('ParamMouthU', 0);
    setParam('ParamMouthE', 0);
    setParam('ParamMouthO', 0);
  }
}
