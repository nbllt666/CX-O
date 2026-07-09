import { VRM, VRMExpressionPresetName } from '@pixiv/three-vrm';
import type { ExpressionLayer } from '../Avatar/avatarManifest';

export type EmotionType = 'happy' | 'angry' | 'sad' | 'surprised' | 'relaxed' | 'neutral';

export interface EmotionConfig {
  intensity: number;
  duration: number;
  recoverSpeed: number;
  idleExpressionIntensity: number;
}

class SimpleNoise {
  private perm: number[] = [];

  constructor(seed: number = 42) {
    for (let i = 0; i < 256; i++) this.perm[i] = i;
    let s = seed;
    for (let i = 255; i > 0; i--) {
      s = (s * 16807) % 2147483647;
      const j = s % (i + 1);
      [this.perm[i], this.perm[j]] = [this.perm[j], this.perm[i]];
    }
    for (let i = 0; i < 256; i++) this.perm[256 + i] = this.perm[i];
  }

  noise(x: number): number {
    const xi = Math.floor(x) & 255;
    const xf = x - Math.floor(x);
    const u = xf * xf * (3 - 2 * xf);
    const a = this.perm[xi] / 255;
    const b = this.perm[xi + 1] / 255;
    return a * (1 - u) + b * u;
  }
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
    idleExpressionIntensity: 0.1,
  };
  private activeExpressionMix: ExpressionLayer[] = [];
  private mixBlendShapeValues: Map<string, number> = new Map();

  private idleTime = 0;
  private idleSmileNoise = new SimpleNoise(211);
  private idleBrowNoise = new SimpleNoise(307);

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

    this.idleTime += deltaTime;

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
    } else {
      this.applyIdleMicroExpressions(em);
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

  private applyIdleMicroExpressions(em: NonNullable<VRM['expressionManager']>): void {
    const idleIntensity = this.config.idleExpressionIntensity;
    if (idleIntensity < 0.001) return;

    // 基线放松表情（微弱的常量 relaxed，让脸不显得僵硬）
    const relaxedWeight = idleIntensity * 0.4;
    em.setValue(VRMExpressionPresetName.Relaxed, relaxedWeight);

    // 噪声驱动的微微笑（缓慢来去，约 15-20 秒周期）
    const smileNoise = this.idleSmileNoise.noise(this.idleTime * 0.07);
    const smileWeight = Math.max(0, smileNoise) * idleIntensity * 0.7;
    if (smileWeight > 0.001) {
      em.setValue(VRMExpressionPresetName.Happy, smileWeight);
    }

    // 偶尔的微弱惊讶（眉毛抬升，非常罕见且微弱）
    const browNoise = this.idleBrowNoise.noise(this.idleTime * 0.04);
    const browWeight = Math.max(0, browNoise - 0.6) * idleIntensity * 0.3;
    if (browWeight > 0.001) {
      em.setValue(VRMExpressionPresetName.Surprised, browWeight);
    }
  }

  reset(): void {
    this.targetEmotion = 'neutral';
    this.emotionWeight = 0;
    this.emotionTimer = 0;
    this.activeExpressionMix = [];
    this.mixBlendShapeValues.clear();
    this.idleTime = 0;
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
