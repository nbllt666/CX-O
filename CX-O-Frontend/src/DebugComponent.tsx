import { useEffect } from 'react';

export const DebugComponent = () => {
  useEffect(() => {
    console.log('VITE_WS_URL:', import.meta.env.VITE_WS_URL);
    console.log('VITE_API_URL:', import.meta.env.VITE_API_URL);
    const calculatedWsUrl = (import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000').replace('http', 'ws');
    console.log('Calculated WS URL:', calculatedWsUrl);
  }, []);

  return null;
};
