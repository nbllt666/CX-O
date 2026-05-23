console.log('VITE_WS_URL:', import.meta.env.VITE_WS_URL);
console.log('VITE_API_URL:', import.meta.env.VITE_API_URL);
console.log('WS_BASE_URL calculation:', (import.meta.env.VITE_API_URL || 'http://127.0.0.1:8100').replace('http', 'ws'));
