import { VRM, VRMExpressionPresetName } from '@pixiv/three-vrm';

export type EmotionType = 'happy' | 'angry' | 'sad' | 'surprised' | 'relaxed' | 'neutral';

export interface EmotionConfig {
  intensity: number;
  duration: number;
  recoverSpeed: number;
}

export class VRMExpression {
  private vrm: VRM | null = null;
  private currentEmotion: EmotionType = 'neutral';
  private targetEmotion: EmotionType = 'neutral';
  private emotionWeight = 0;
  private emotionTimer = 0;
  private config: EmotionConfig = {
    intensity: 1.0,
    duration: 3.0,
    recoverSpeed: 0.5,
  };

  private emotionMap: Record<EmotionType, VRMExpressionPresetName[]> = {
    happy: [VRMExpressionPresetName.Happy],
    angry: [VRMExpressionPresetName.Angry],
    sad: [VRMExpressionPresetName.Sad],
    surprised: [VRMExpressionPresetName.Surprised],
    relaxed: [VRMExpressionPresetName.Relaxed],
    neutral: [],
  };

  bindVRM(vrm: VRM): void {
    this.vrm = vrm;
  }

  setConfig(config: Partial<EmotionConfig>): void {
    this.config = { ...this.config, ...config };
  }

  setEmotion(emotion: EmotionType): void {
    if (this.targetEmotion === emotion) return;
    this.targetEmotion = emotion;
    this.emotionTimer = this.config.duration;
  }

  update(deltaTime: number): void {
    if (!this.vrm) return;
    const em = this.vrm.expressionManager;
    if (!em) return;

    // Update emotion timer
    if (this.emotionTimer > 0) {
      this.emotionTimer -= deltaTime;
      if (this.emotionTimer <= 0) {
        this.targetEmotion = 'neutral';
      }
    }

    // Smooth weight transition
    const targetWeight = this.targetEmotion === 'neutral' ? 0 : this.config.intensity;
    const speed = this.targetEmotion === 'neutral' ? this.config.recoverSpeed : 2.0;
    const diff = targetWeight - this.emotionWeight;
    if (Math.abs(diff) > 0.001) {
      this.emotionWeight += diff * Math.min(1, speed * deltaTime * 5);
    } else {
      this.emotionWeight = targetWeight;
    }

    // Reset all emotion blend shapes
    Object.values(VRMExpressionPresetName).forEach((preset) => {
      if ([VRMExpressionPresetName.Happy, VRMExpressionPresetName.Angry,
           VRMExpressionPresetName.Sad, VRMExpressionPresetName.Surprised,
           VRMExpressionPresetName.Relaxed].includes(preset)) {
        em.setValue(preset, 0);
      }
    });

    // Apply current emotion
    if (this.emotionWeight > 0.01 && this.targetEmotion !== 'neutral') {
      const presets = this.emotionMap[this.targetEmotion];
      presets.forEach((preset) => {
        em.setValue(preset, this.emotionWeight);
      });
    }

    // Update current emotion when transition completes
    if (this.emotionWeight < 0.01 && this.targetEmotion === 'neutral') {
      this.currentEmotion = 'neutral';
    } else if (this.emotionWeight > 0.99 && this.targetEmotion !== 'neutral') {
      this.currentEmotion = this.targetEmotion;
    }
  }

  reset(): void {
    this.currentEmotion = 'neutral';
    this.targetEmotion = 'neutral';
    this.emotionWeight = 0;
    this.emotionTimer = 0;
    if (!this.vrm) return;
    const em = this.vrm.expressionManager;
    if (!em) return;
    Object.values(VRMExpressionPresetName).forEach((preset) => {
      if ([VRMExpressionPresetName.Happy, VRMExpressionPresetName.Angry,
           VRMExpressionPresetName.Sad, VRMExpressionPresetName.Surprised,
           VRMExpressionPresetName.Relaxed].includes(preset)) {
        em.setValue(preset, 0);
      }
    });
  }
}
