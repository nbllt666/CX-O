import { useState } from 'react';
import { VRMTweakConfig } from '../../store/settingsStore';
import { Slider } from '../ui';

export interface AnimationConfig {
  // Lip Sync
  lipSyncSensitivity: number;
  lipSyncSmoothing: number;
  vowelWeightA: number;
  vowelWeightI: number;
  vowelWeightU: number;
  vowelWeightE: number;
  vowelWeightO: number;
  // Emotion
  emotionIntensity: number;
  emotionDuration: number;
  emotionRecoverSpeed: number;
  // VRM Idle
  breathFrequency: number;
  breathAmplitude: number;
  blinkInterval: number;
  blinkDuration: number;
  headFollowSpeed: number;
  bodyFollowDelay: number;
  // Live2D Motion
  motionTriggerProbability: number;
  focusSpeed: number;
}

export const DEFAULT_ANIMATION_CONFIG: AnimationConfig = {
  lipSyncSensitivity: 1.0,
  lipSyncSmoothing: 0.3,
  vowelWeightA: 1.0,
  vowelWeightI: 1.0,
  vowelWeightU: 1.0,
  vowelWeightE: 1.0,
  vowelWeightO: 1.0,
  emotionIntensity: 1.0,
  emotionDuration: 3.0,
  emotionRecoverSpeed: 0.5,
  breathFrequency: 0.3,
  breathAmplitude: 0.02,
  blinkInterval: 3.0,
  blinkDuration: 0.15,
  headFollowSpeed: 2.0,
  bodyFollowDelay: 0.3,
  motionTriggerProbability: 0.5,
  focusSpeed: 3.0,
};

interface VRMTweakPanelProps {
  config: VRMTweakConfig;
  animConfig?: AnimationConfig;
  onChange: (config: VRMTweakConfig) => void;
  onAnimChange?: (config: AnimationConfig) => void;
  onApply: () => void;
  onReset: () => void;
  avatarType?: 'vrm' | 'live2d';
}

export function VRMTweakPanel({
  config,
  animConfig = DEFAULT_ANIMATION_CONFIG,
  onChange,
  onAnimChange,
  onApply,
  onReset,
  avatarType = 'vrm',
}: VRMTweakPanelProps) {
  const [activeTab, setActiveTab] = useState<'camera' | 'light' | 'rotation' | 'lipSync' | 'emotion' | 'animation'>('camera');

  const update = <K extends keyof VRMTweakConfig>(key: K, value: VRMTweakConfig[K]) => {
    onChange({ ...config, [key]: value });
  };

  const updateCamera = <K extends keyof VRMTweakConfig['camera']>(key: K, value: number) => {
    onChange({ ...config, camera: { ...config.camera, [key]: value } });
  };

  const updateLight = <K extends keyof VRMTweakConfig['light']>(key: K, value: number) => {
    onChange({ ...config, light: { ...config.light, [key]: value } });
  };

  const updateAnim = <K extends keyof AnimationConfig>(key: K, value: AnimationConfig[K]) => {
    onAnimChange?.({ ...animConfig, [key]: value });
  };

  const tabs = [
    { key: 'camera' as const, label: '相机' },
    { key: 'light' as const, label: '灯光' },
    { key: 'rotation' as const, label: '旋转' },
    { key: 'lipSync' as const, label: '口型' },
    { key: 'emotion' as const, label: '表情' },
    { key: 'animation' as const, label: '动画' },
  ];

  return (
    <div className="flex flex-col gap-2 text-xs select-none" style={{ width: 240 }}>
      <div className="flex gap-1 border-b border-[var(--color-border)] pb-1 flex-wrap">
        {tabs.map(tab => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`px-2 py-0.5 rounded transition-colors ${
              activeTab === tab.key
                ? 'bg-[var(--color-accent)] text-white'
                : 'text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="flex flex-col gap-1.5 max-h-[320px] overflow-y-auto pr-1">
        {activeTab === 'camera' && (
          <>
            <Slider label="X 偏移" value={config.camera.offsetX} min={-3} max={3} step={0.05}
              onChange={v => updateCamera('offsetX', v)} />
            <Slider label="Y 高度" value={config.camera.offsetY} min={0} max={4} step={0.05}
              onChange={v => updateCamera('offsetY', v)} />
            <Slider label="Z 距离" value={config.camera.offsetZ} min={0.5} max={6} step={0.1}
              onChange={v => updateCamera('offsetZ', v)} />
            <Slider label="注视点 Y" value={config.camera.lookAtY} min={0} max={1.5} step={0.02}
              onChange={v => updateCamera('lookAtY', v)} />
          </>
        )}

        {activeTab === 'light' && (
          <>
            <Slider label="主光强度" value={config.light.directionalIntensity} min={0} max={5} step={0.1}
              onChange={v => updateLight('directionalIntensity', v)} />
            <Slider label="环境光" value={config.light.ambientIntensity} min={0} max={3} step={0.1}
              onChange={v => updateLight('ambientIntensity', v)} />
            <Slider label="补光" value={config.light.pointIntensity} min={0} max={3} step={0.1}
              onChange={v => updateLight('pointIntensity', v)} />
          </>
        )}

        {activeTab === 'rotation' && (
          <>
            <Slider label="X 轴旋转" value={config.modelRotationX} min={-Math.PI} max={Math.PI} step={0.05}
              onChange={v => update('modelRotationX', v)} format={v => `${(v * 180 / Math.PI).toFixed(0)}°`} />
            <Slider label="Y 轴旋转" value={config.modelRotationY} min={-Math.PI} max={Math.PI} step={0.05}
              onChange={v => update('modelRotationY', v)} format={v => `${(v * 180 / Math.PI).toFixed(0)}°`} />
            <Slider label="Z 轴旋转" value={config.modelRotationZ} min={-Math.PI} max={Math.PI} step={0.05}
              onChange={v => update('modelRotationZ', v)} format={v => `${(v * 180 / Math.PI).toFixed(0)}°`} />
          </>
        )}

        {activeTab === 'lipSync' && (
          <>
            <Slider label="灵敏度" value={animConfig.lipSyncSensitivity} min={0} max={2} step={0.1}
              onChange={v => updateAnim('lipSyncSensitivity', v)} />
            <Slider label="平滑度" value={animConfig.lipSyncSmoothing} min={0.01} max={1} step={0.05}
              onChange={v => updateAnim('lipSyncSmoothing', v)} />
            <div className="text-[var(--color-text-secondary)] text-[10px] mt-1">元音权重</div>
            <Slider label="A" value={animConfig.vowelWeightA} min={0} max={2} step={0.1}
              onChange={v => updateAnim('vowelWeightA', v)} />
            <Slider label="I" value={animConfig.vowelWeightI} min={0} max={2} step={0.1}
              onChange={v => updateAnim('vowelWeightI', v)} />
            <Slider label="U" value={animConfig.vowelWeightU} min={0} max={2} step={0.1}
              onChange={v => updateAnim('vowelWeightU', v)} />
            <Slider label="E" value={animConfig.vowelWeightE} min={0} max={2} step={0.1}
              onChange={v => updateAnim('vowelWeightE', v)} />
            <Slider label="O" value={animConfig.vowelWeightO} min={0} max={2} step={0.1}
              onChange={v => updateAnim('vowelWeightO', v)} />
          </>
        )}

        {activeTab === 'emotion' && (
          <>
            <Slider label="表情强度" value={animConfig.emotionIntensity} min={0} max={2} step={0.1}
              onChange={v => updateAnim('emotionIntensity', v)} />
            <Slider label="持续时间" value={animConfig.emotionDuration} min={0.5} max={10} step={0.5}
              onChange={v => updateAnim('emotionDuration', v)} format={v => `${v.toFixed(1)}s`} />
            <Slider label="恢复速度" value={animConfig.emotionRecoverSpeed} min={0.1} max={2} step={0.1}
              onChange={v => updateAnim('emotionRecoverSpeed', v)} />
          </>
        )}

        {activeTab === 'animation' && (
          <>
            {avatarType === 'vrm' ? (
              <>
                <div className="text-[var(--color-text-secondary)] text-[10px]">呼吸</div>
                <Slider label="频率" value={animConfig.breathFrequency} min={0.1} max={1} step={0.05}
                  onChange={v => updateAnim('breathFrequency', v)} />
                <Slider label="幅度" value={animConfig.breathAmplitude} min={0} max={0.1} step={0.005}
                  onChange={v => updateAnim('breathAmplitude', v)} />
                <div className="text-[var(--color-text-secondary)] text-[10px] mt-1">眨眼</div>
                <Slider label="间隔" value={animConfig.blinkInterval} min={1} max={8} step={0.5}
                  onChange={v => updateAnim('blinkInterval', v)} format={v => `${v.toFixed(1)}s`} />
                <Slider label="持续时间" value={animConfig.blinkDuration} min={0.05} max={0.3} step={0.01}
                  onChange={v => updateAnim('blinkDuration', v)} format={v => `${(v * 1000).toFixed(0)}ms`} />
                <div className="text-[var(--color-text-secondary)] text-[10px] mt-1">跟随</div>
                <Slider label="头部速度" value={animConfig.headFollowSpeed} min={0.5} max={5} step={0.1}
                  onChange={v => updateAnim('headFollowSpeed', v)} />
                <Slider label="身体延迟" value={animConfig.bodyFollowDelay} min={0} max={1} step={0.05}
                  onChange={v => updateAnim('bodyFollowDelay', v)} />
              </>
            ) : (
              <>
                <div className="text-[var(--color-text-secondary)] text-[10px]">动作</div>
                <Slider label="触发概率" value={animConfig.motionTriggerProbability} min={0} max={1} step={0.05}
                  onChange={v => updateAnim('motionTriggerProbability', v)} />
                <div className="text-[var(--color-text-secondary)] text-[10px] mt-1">视线</div>
                <Slider label="跟随速度" value={animConfig.focusSpeed} min={1} max={5} step={0.1}
                  onChange={v => updateAnim('focusSpeed', v)} />
              </>
            )}
          </>
        )}
      </div>

      <div className="flex gap-2 pt-1 border-t border-[var(--color-border)]">
        <button
          onClick={onApply}
          className="flex-1 px-3 py-1.5 rounded bg-[var(--color-accent)] text-white hover:brightness-110 transition-all font-medium"
        >
          应用参数
        </button>
        <button
          onClick={onReset}
          className="px-3 py-1.5 rounded bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)] border border-[var(--color-border)] transition-colors"
        >
          重置
        </button>
      </div>
    </div>
  );
}
