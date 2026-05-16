import { useState } from 'react';
import { VRMTweakConfig } from './VRMViewer';

interface VRMTweakPanelProps {
  config: VRMTweakConfig;
  onChange: (config: VRMTweakConfig) => void;
  onApply: () => void;
  onReset: () => void;
}

export function VRMTweakPanel({ config, onChange, onApply, onReset }: VRMTweakPanelProps) {
  const [activeTab, setActiveTab] = useState<'camera' | 'light' | 'rotation'>('camera');

  const update = <K extends keyof VRMTweakConfig>(key: K, value: VRMTweakConfig[K]) => {
    onChange({ ...config, [key]: value });
  };

  const updateCamera = <K extends keyof VRMTweakConfig['camera']>(key: K, value: number) => {
    onChange({ ...config, camera: { ...config.camera, [key]: value } });
  };

  const updateLight = <K extends keyof VRMTweakConfig['light']>(key: K, value: number) => {
    onChange({ ...config, light: { ...config.light, [key]: value } });
  };

  return (
    <div className="flex flex-col gap-2 text-xs select-none" style={{ width: 220 }}>
      <div className="flex gap-1 border-b border-[var(--color-border)] pb-1">
        {(['camera', 'light', 'rotation'] as const).map(tab => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-2 py-0.5 rounded transition-colors ${
              activeTab === tab
                ? 'bg-[var(--color-accent)] text-white'
                : 'text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]'
            }`}
          >
            {{ camera: '相机', light: '灯光', rotation: '旋转' }[tab]}
          </button>
        ))}
      </div>

      <div className="flex flex-col gap-1.5 max-h-[280px] overflow-y-auto pr-1">
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

function Slider({
  label,
  value,
  min,
  max,
  step,
  onChange,
  format = v => v.toFixed(2),
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (v: number) => void;
  format?: (v: number) => string;
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <div className="flex justify-between">
        <span className="text-[var(--color-text-secondary)]">{label}</span>
        <span className="text-[var(--color-text-tertiary)] tabular-nums w-12 text-right">{format(value)}</span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={e => onChange(parseFloat(e.target.value))}
        className="w-full h-1 rounded-full appearance-none cursor-pointer accent-[var(--color-accent)]
          [&::-webkit-slider-runnable-track]:rounded-full [&::-webkit-slider-runnable-track]:h-1
          [&::-webkit-slider-runnable-track]:bg-[var(--color-bg-secondary)]
          [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3
          [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-[var(--color-accent)]
          [&::-webkit-slider-thumb]:mt-[-4px]"
      />
    </div>
  );
}
