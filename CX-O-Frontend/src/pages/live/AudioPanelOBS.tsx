import { useEffect } from 'react';
import { AudioPanel } from './AudioPanel';

export function AudioPanelOBS() {
  useEffect(() => {
    document.body.style.background = 'transparent';
    document.documentElement.style.background = 'transparent';
    return () => {
      document.body.style.background = '';
      document.documentElement.style.background = '';
    };
  }, []);

  return (
    <div style={{ backgroundColor: 'transparent' }}>
      <AudioPanel standalone />
    </div>
  );
}
