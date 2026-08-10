/**
 * Live2D 动作触发：情绪动作组随机播放 / 说话点头 / 视线聚焦。
 * 行为口径对齐 CX-O-Frontend components/business/live2d/live2d-motion.ts。
 *
 * 动作组依赖模型 model3.json 的 Motions 定义；组不存在时静默跳过。
 */
import type { Live2DModel } from 'pixi-live2d-display';
import type { EmotionType } from '../types';

export interface MotionConfig {
  emotionMotionProbability: number;
  speechMotionProbability: number;
  nodProbability: number;
  waveProbability: number;
  focusSpeed: number;
}

const DEFAULT_CONFIG: MotionConfig = {
  emotionMotionProbability: 0.7,
  speechMotionProbability: 0.5,
  nodProbability: 0.3,
  waveProbability: 0.1,
  focusSpeed: 3.0,
};

export class Live2DMotion {
  private model: Live2DModel | null = null;
  private config: MotionConfig = { ...DEFAULT_CONFIG };

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
      // 模型不支持 focus 时跳过
    }
  }

  update(deltaTime: number): void {
    if (!this.model) return;

    if (this.isSpeaking) {
      this.speechTimer += deltaTime;

      // 说话中周期性点头
      if (this.speechTimer > 1.0) {
        this.triggerNod();
        this.speechTimer = 0;
      }

      // 说话中随机小动作
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
      // 动作组不存在时跳过
    }
  }

  reset(): void {
    this.isSpeaking = false;
    this.speechTimer = 0;
  }
}
