import { useState, useRef, useEffect } from 'react';

export interface SliderProps {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (value: number) => void;
  format?: (value: number) => string;
}

export function Slider({
  label,
  value,
  min,
  max,
  step,
  onChange,
  format = (v) => v.toFixed(2),
}: SliderProps) {
  const [editing, setEditing] = useState(false);
  const [editValue, setEditValue] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing && inputRef.current) inputRef.current.select();
  }, [editing]);

  const commitEdit = () => {
    const v = parseFloat(editValue);
    if (!isNaN(v)) {
      const clamped = Math.max(min, Math.min(max, Math.round(v / step) * step));
      onChange(clamped);
    }
    setEditing(false);
  };

  return (
    <div className="flex flex-col gap-0.5">
      <div className="flex justify-between">
        <span className="text-xs text-[var(--color-text-secondary)]">{label}</span>
        {editing ? (
          <input
            ref={inputRef}
            type="number"
            value={editValue}
            min={min}
            max={max}
            step={step}
            onChange={(e) => setEditValue(e.target.value)}
            onBlur={commitEdit}
            onKeyDown={(e) => { if (e.key === 'Enter') commitEdit(); if (e.key === 'Escape') setEditing(false); }}
            className="text-[10px] text-[var(--color-text-primary)] tabular-nums w-16 text-right bg-[var(--color-bg-secondary)] border border-[var(--color-border)] rounded px-1 py-0 outline-none focus:border-[var(--color-accent)]"
          />
        ) : (
          <span
            className="text-[10px] text-[var(--color-text-tertiary)] tabular-nums w-12 text-right cursor-pointer hover:text-[var(--color-text-primary)] transition-colors"
            onClick={() => { setEditValue(String(value)); setEditing(true); }}
            title="点击输入值"
          >
            {format(value)}
          </span>
        )}
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
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
