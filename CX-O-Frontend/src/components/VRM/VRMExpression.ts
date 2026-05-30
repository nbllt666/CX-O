import { VRM, VRMExpressionPresetName } from '@pixiv/three-vrm';
import type { ExpressionLayer } from '../Avatar/avatarManifest';

export type EmotionType = 'happy' | 'angry' | 'sad' | 'surprised' | 'relaxed' | 'neutral';

export interface EmotionConfig {
  intensity: number;
  duration: number;
  recoverSpeed: number;
}

const LLM_EMOTION_MAP: Record<string, EmotionType> = {
  happy: 'happy',
  joy: 'happy',
  excited: 'happy',
  cheerful: 'happy',
  delighted: 'happy',
  glad: 'happy',
  pleased: 'happy',
  angry: 'angry',
  fury: 'angry',
  rage: 'angry',
  mad: 'angry',
  irritated: 'angry',
  annoyed: 'angry',
  sad: 'sad',
  sorrow: 'sad',
  grief: 'sad',
  melancholy: 'sad',
  depressed: 'sad',
  gloomy: 'sad',
  surprised: 'surprised',
  shock: 'surprised',
  amazed: 'surprised',
  astonished: 'surprised',
  startled: 'surprised',
  relaxed: 'relaxed',
  calm: 'relaxed',
  peaceful: 'relaxed',
  serene: 'relaxed',
  content: 'relaxed',
  neutral: 'neutral',
  default: 'neutral',
  none: 'neutral',
  idle: 'neutral',
};

const EMOTION_PRESET_MAP: Record<EmotionType, VRMExpressionPresetName[]> = {
  happy: [VRMExpressionPresetName.Happy],
  angry: [VRMExpressionPresetName.Angry],
  sad: [VRMExpressionPresetName.Sad],
  surprised: [VRMExpressionPresetName.Surprised],
  relaxed: [VRMExpressionPresetName.Relaxed],
  neutral: [],
};

const ALL_EMOTION_PRESETS: VRMExpressionPresetName[] = [
  VRMExpressionPresetName.Happy,
  VRMExpressionPresetName.Angry,
  VRMExpressionPresetName.Sad,
  VRMExpressionPresetName.Surprised,
  VRMExpressionPresetName.Relaxed,
];

export function mapLLMEmotion(emotion: string): EmotionType {
  return LLM_EMOTION_MAP[emotion.toLowerCase()] ?? 'neutral';
}

export class VRMExpression {
  private vrm: VRM | null = null;
  private targetEmotion: EmotionType = 'neutral';
  private emotionWeight = 0;
  private emotionTimer = 0;
  private config: EmotionConfig = {
    intensity: 1.0,
    duration: 3.0,
    recoverSpeed: 0.5,
  };
  private activeExpressionMix: ExpressionLayer[] = [];
  private mixBlendShapeValues: Map<string, number> = new Map();

  bindVRM(vrm: VRM): void {
    this.vrm = vrm;
  }

  setConfig(config: Partial<EmotionConfig>): void {
    this.config = { ...this.config, ...config };
  }

  setEmotion(emotion: EmotionType | string, intensity?: number): void {
    const resolvedEmotion = typeof emotion === 'string' && !this.isEmotionType(emotion)
      ? mapLLMEmotion(emotion)
      : emotion as EmotionType;

    if (this.targetEmotion === resolvedEmotion && intensity === undefined) return;
    this.targetEmotion = resolvedEmotion;
    if (intensity !== undefined) {
      this.emotionWeight = Math.max(0, Math.min(1, intensity));
    }
    this.emotionTimer = this.config.duration;
  }

  applyExpressionMix(mix: ExpressionLayer[]): void {
    this.activeExpressionMix = mix;
    this.rebuildMixBlendShapes();
  }

  getActiveExpressionMix(): ExpressionLayer[] {
    return this.activeExpressionMix;
  }

  private isEmotionType(value: string): value is EmotionType {
    return ['happy', 'angry', 'sad', 'surprised', 'relaxed', 'neutral'].includes(value);
  }

  private rebuildMixBlendShapes(): void {
    this.mixBlendShapeValues.clear();
    if (!this.vrm) return;
    const em = this.vrm.expressionManager;
    if (!em) return;

    for (const layer of this.activeExpressionMix) {
      const presetName = this.layerKeyToPreset(layer.key);
      if (presetName && em.getValue(presetName as keyof typeof VRMExpressionPresetName) !== undefined) {
        const current = this.mixBlendShapeValues.get(presetName) ?? 0;
        this.mixBlendShapeValues.set(presetName, Math.min(1, current + layer.weight));
      }
    }
  }

  private layerKeyToPreset(key: string): string | null {
    const lower = key.toLowerCase();
    const presetMap: Record<string, string> = {
      happy: 'Happy',
      angry: 'Angry',
      sad: 'Sad',
      surprised: 'Surprised',
      relaxed: 'Relaxed',
      neutral: 'Neutral',
      blink: 'Blink',
      blinkl: 'BlinkL',
      blinkr: 'BlinkR',
      aa: 'Aa',
      ih: 'Ih',
      ou: 'Ou',
      ee: 'Ee',
      oh: 'Oh',
      a: 'A',
      i: 'I',
      u: 'U',
      e: 'E',
      o: 'O',
      lookup: 'LookUp',
      lookdown: 'LookDown',
      lookleft: 'LookLeft',
      lookright: 'LookRight',
    };
    return presetMap[lower] ?? null;
  }

  update(deltaTime: number): void {
    if (!this.vrm) return;
    const em = this.vrm.expressionManager;
    if (!em) return;

    if (this.emotionTimer > 0) {
      this.emotionTimer -= deltaTime;
      if (this.emotionTimer <= 0) {
        this.targetEmotion = 'neutral';
      }
    }

    const targetWeight = this.targetEmotion === 'neutral' ? 0 : this.config.intensity;
    const speed = this.targetEmotion === 'neutral' ? this.config.recoverSpeed : 2.0;
    const diff = targetWeight - this.emotionWeight;
    if (Math.abs(diff) > 0.001) {
      this.emotionWeight += diff * Math.min(1, speed * deltaTime * 5);
    } else {
      this.emotionWeight = targetWeight;
    }

    Object.values(VRMExpressionPresetName).forEach((preset) => {
      if (ALL_EMOTION_PRESETS.includes(preset as VRMExpressionPresetName)) {
        em.setValue(preset, 0);
      }
    });

    if (this.emotionWeight > 0.01 && this.targetEmotion !== 'neutral') {
      const presets = EMOTION_PRESET_MAP[this.targetEmotion];
      presets.forEach((preset) => {
        em.setValue(preset, this.emotionWeight);
      });
    }

    for (const [name, value] of this.mixBlendShapeValues) {
      const current = em.getValue(name as keyof typeof VRMExpressionPresetName);
      if (typeof current === 'number') {
        const isEmotionPreset = ALL_EMOTION_PRESETS.includes(name as VRMExpressionPresetName);
        if (!isEmotionPreset || this.emotionWeight < 0.01) {
          em.setValue(name as keyof typeof VRMExpressionPresetName, value);
        }
      }
    }
  }

  reset(): void {
    this.targetEmotion = 'neutral';
    this.emotionWeight = 0;
    this.emotionTimer = 0;
    this.activeExpressionMix = [];
    this.mixBlendShapeValues.clear();
    if (!this.vrm) return;
    const em = this.vrm.expressionManager;
    if (!em) return;
    Object.values(VRMExpressionPresetName).forEach((preset) => {
      if (ALL_EMOTION_PRESETS.includes(preset as VRMExpressionPresetName)) {
        em.setValue(preset, 0);
      }
    });
  }
}
