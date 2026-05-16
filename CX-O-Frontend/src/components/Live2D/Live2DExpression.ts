import type { Live2DModel } from 'pixi-live2d-display';

export type EmotionType = 'happy' | 'angry' | 'sad' | 'surprised' | 'relaxed' | 'neutral';

export interface EmotionConfig {
  intensity: number;
  duration: number;
  recoverSpeed: number;
}

export class Live2DExpression {
  private model: Live2DModel | null = null;
  private currentEmotion: EmotionType = 'neutral';
  private targetEmotion: EmotionType = 'neutral';
  private emotionWeight = 0;
  private emotionTimer = 0;
  private config: EmotionConfig = {
    intensity: 1.0,
    duration: 3.0,
    recoverSpeed: 0.5,
  };

  bindModel(model: Live2DModel): void {
    this.model = model;
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
    if (!this.model) return;

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

    // Apply expression
    const expressions = this.model.internalModel?.expressions;
    if (!expressions) return;

    if (this.emotionWeight > 0.01 && this.currentEmotion !== 'neutral') {
      const expressionName = this.currentEmotion;
      const idx = expressions.findIndex((e: { name: string }) => e.name === expressionName);
      if (idx >= 0) {
        try {
          this.model.setExpression(idx);
        } catch {
          // Expression not available
        }
      }
    } else if (this.emotionWeight < 0.01) {
      try {
        this.model.resetExpression();
      } catch {
        // Ignore
      }
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
    if (!this.model) return;
    try {
      this.model.resetExpression();
    } catch {
      // Ignore
    }
  }
}
