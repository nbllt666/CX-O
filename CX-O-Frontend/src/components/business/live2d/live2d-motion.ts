import type { Live2DModel } from 'pixi-live2d-display';

export type EmotionType = 'happy' | 'angry' | 'sad' | 'surprised' | 'relaxed' | 'neutral';

export interface MotionConfig {
  emotionMotionProbability: number;
  speechMotionProbability: number;
  nodProbability: number;
  waveProbability: number;
  focusSpeed: number;
}

export class Live2DMotion {
  private model: Live2DModel | null = null;
  private config: MotionConfig = {
    emotionMotionProbability: 0.7,
    speechMotionProbability: 0.5,
    nodProbability: 0.3,
    waveProbability: 0.1,
    focusSpeed: 3.0,
  };

  private emotionMotionMap: Record<EmotionType, string[]> = {
    happy: ['happy', 'joy', 'excited'],
    angry: ['angry', 'mad', 'frustrated'],
    sad: ['sad', 'cry', 'depressed'],
    surprised: ['surprised', 'shock', 'amazed'],
    relaxed: ['relaxed', 'calm', 'peaceful'],
    neutral: ['idle'],
  };

  private isSpeaking = false;
  private speechTimer = 0;

  bindModel(model: Live2DModel): void {
    this.model = model;
  }

  setConfig(config: Partial<MotionConfig>): void {
    this.config = { ...this.config, ...config };
  }

  setSpeaking(speaking: boolean): void {
    this.isSpeaking = speaking;
    if (speaking) {
      this.speechTimer = 0;
    }
  }

  triggerEmotionMotion(emotion: EmotionType): void {
    if (!this.model) return;
    if (Math.random() > this.config.emotionMotionProbability) return;

    const motionGroups = this.emotionMotionMap[emotion];
    if (!motionGroups || motionGroups.length === 0) return;

    const group = motionGroups[Math.floor(Math.random() * motionGroups.length)];
    this.tryStartMotion(group);
  }

  triggerNod(): void {
    if (!this.model) return;
    if (Math.random() > this.config.nodProbability) return;
    this.tryStartMotion('nod');
  }

  triggerWave(): void {
    if (!this.model) return;
    if (Math.random() > this.config.waveProbability) return;
    this.tryStartMotion('wave');
  }

  setFocus(x: number, y: number): void {
    if (!this.model) return;
    try {
      this.model.focus(x, y, false);
    } catch {
      // Focus not supported
    }
  }

  update(deltaTime: number): void {
    if (!this.model) return;

    if (this.isSpeaking) {
      this.speechTimer += deltaTime;

      // Trigger nod during speech
      if (this.speechTimer > 1.0) {
        this.triggerNod();
        this.speechTimer = 0;
      }

      // Random motion during speech
      if (Math.random() < this.config.speechMotionProbability * deltaTime) {
        this.tryStartMotion('talk');
      }
    }
  }

  private tryStartMotion(group: string): void {
    if (!this.model?.internalModel?.motionManager) return;

    try {
      const motionManager = this.model.internalModel.motionManager;
      if (motionManager.startRandomMotion) {
        motionManager.startRandomMotion(group, 2);
      }
    } catch {
      // Motion group not available
    }
  }

  reset(): void {
    this.isSpeaking = false;
    this.speechTimer = 0;
  }
}
