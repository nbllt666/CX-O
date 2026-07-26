import { VRM, VRMExpressionPresetName } from '@pixiv/three-vrm';

export class VRMAudioLipSync {
  private audioContext: AudioContext | null = null;
  private analyser: AnalyserNode | null = null;
  private source: MediaElementAudioSourceNode | null = null;
  private animationFrame: number | null = null;
  private vrm: VRM | null = null;
  private dataArray: Uint8Array | null = null;

  bindVRM(vrm: VRM): void {
    this.vrm = vrm;
  }

  start(audioElement: HTMLAudioElement): void {
    if (!this.vrm) {
      console.warn('VRM not bound, cannot start lip sync');
      return;
    }

    this.stop();

    try {
      this.audioContext = new (window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext)();
      this.analyser = this.audioContext.createAnalyser();
      this.analyser.fftSize = 256;
      this.analyser.smoothingTimeConstant = 0.8;

      this.source = this.audioContext.createMediaElementSource(audioElement);
      this.source.connect(this.analyser);
      this.analyser.connect(this.audioContext.destination);

      this.dataArray = new Uint8Array(this.analyser.frequencyBinCount);

      this.analyze();
    } catch (error) {
      console.error('Failed to start audio lip sync:', error);
    }
  }

  stop(): void {
    if (this.animationFrame !== null) {
      cancelAnimationFrame(this.animationFrame);
      this.animationFrame = null;
    }

    if (this.source) {
      this.source.disconnect();
      this.source = null;
    }

    if (this.analyser) {
      this.analyser.disconnect();
      this.analyser = null;
    }

    if (this.audioContext) {
      this.audioContext.close();
      this.audioContext = null;
    }

    this.resetMouth();
  }

  private analyze = (): void => {
    if (!this.analyser || !this.dataArray || !this.vrm) {
      return;
    }

    this.analyser.getByteFrequencyData(this.dataArray as Uint8Array<ArrayBuffer>);

    let sum = 0;
    for (let i = 0; i < this.dataArray.length; i++) {
      sum += this.dataArray[i];
    }
    const average = sum / this.dataArray.length;
    const normalizedVolume = Math.min(average / 100, 1);

    this.setMouthOpen(normalizedVolume);

    this.animationFrame = requestAnimationFrame(this.analyze);
  };

  private setMouthOpen(value: number): void {
    if (!this.vrm) return;

    const expressionManager = this.vrm.expressionManager;
    if (!expressionManager) return;

    expressionManager.setValue(VRMExpressionPresetName.Aa, value * 0.8);
    expressionManager.setValue(VRMExpressionPresetName.Ou, value * 0.3);
    expressionManager.setValue(VRMExpressionPresetName.Ih, value * 0.2);
  }

  private resetMouth(): void {
    if (!this.vrm) return;

    const expressionManager = this.vrm.expressionManager;
    if (!expressionManager) return;

    expressionManager.setValue(VRMExpressionPresetName.Aa, 0);
    expressionManager.setValue(VRMExpressionPresetName.Ou, 0);
    expressionManager.setValue(VRMExpressionPresetName.Ih, 0);
  }

  setExpression(preset: VRMExpressionPresetName, weight: number): void {
    if (!this.vrm) return;

    const expressionManager = this.vrm.expressionManager;
    if (!expressionManager) return;

    expressionManager.setValue(preset, weight);
  }

  resetAllExpressions(): void {
    if (!this.vrm) return;

    const expressionManager = this.vrm.expressionManager;
    if (!expressionManager) return;

    Object.values(VRMExpressionPresetName).forEach((preset) => {
      expressionManager.setValue(preset, 0);
    });
  }
}

export const createVRMLipSync = (): VRMAudioLipSync => {
  return new VRMAudioLipSync();
};
