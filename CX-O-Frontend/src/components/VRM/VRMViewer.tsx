import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { VRM, VRMLoaderPlugin, VRMExpressionPresetName } from '@pixiv/three-vrm';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMAudioLipSync } from './AudioLipSync';

interface VRMViewerProps {
  modelPath: string;
  modelDataRef: React.RefObject<ArrayBuffer | undefined>;
  dataVersion: number;
  scale?: number;
  position?: [number, number, number];
  lipSyncEnabled?: boolean;
  lookAtMouse?: boolean;
  mouthOpenY?: number;
  onModelLoaded?: () => void;
  onError?: (error: Error) => void;
}

export function VRMViewer({
  modelPath,
  modelDataRef,
  dataVersion,
  scale = 1.0,
  position = [0, 0, 0],
  lipSyncEnabled = true,
  lookAtMouse = true,
  mouthOpenY = 0,
  onModelLoaded,
  onError,
}: VRMViewerProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const sceneRef = useRef<THREE.Scene | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const vrmRef = useRef<VRM | null>(null);
  const clockRef = useRef(new THREE.Timer());
  const lipSyncRef = useRef<VRMAudioLipSync | null>(null);
  const animationFrameRef = useRef<number | null>(null);
  const activeBlobUrlRef = useRef<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const propsRef = useRef({ scale, position, onModelLoaded, onError });
  const lastVersionRef = useRef(-1);

  propsRef.current = { scale, position, onModelLoaded, onError };

  const waitForCanvas = (): Promise<HTMLCanvasElement> => {
    return new Promise((resolve, reject) => {
      let attempts = 0;
      const check = () => {
        if (canvasRef.current && canvasRef.current.clientWidth > 0 && canvasRef.current.clientHeight > 0) {
          resolve(canvasRef.current);
          return;
        }
        if (++attempts >= 100) reject(new Error('Canvas not ready'));
        else requestAnimationFrame(check);
      };
      check();
    });
  };

  useEffect(() => {
    if (dataVersion === lastVersionRef.current) return;
    lastVersionRef.current = dataVersion;

    console.log(`[VRMViewer] Load #${dataVersion} started`);
    let cancelled = false;

    const loadModel = async () => {
      const modelData = modelDataRef.current;
      const useBuf = modelData && modelData.byteLength > 0;
      const usePath = !useBuf && modelPath && modelPath.length > 0;

      if (!useBuf && !usePath) {
        if (!cancelled) { setLoadError('MODEL_NOT_CONFIGURED'); setIsLoading(false); }
        return;
      }

      let url: string | null = null;
      let isBlob = false;

      if (useBuf) {
        url = URL.createObjectURL(new Blob([modelData], { type: 'application/octet-stream' }));
        isBlob = true;
      } else {
        url = modelPath;
      }

      if (!url) return;

      try {
        if (!cancelled) { setIsLoading(true); setLoadError(null); }
        if (rendererRef.current) { try { rendererRef.current.dispose(); } catch(e){/*ignore*/} rendererRef.current = null; }

        const canvas = await waitForCanvas();
        if (cancelled) return;

        const w = canvas.clientWidth || 300, h = canvas.clientHeight || 400;
        const scene = new THREE.Scene();
        sceneRef.current = scene;
        const cam = new THREE.PerspectiveCamera(30, w / h, 0.1, 20);
        cam.position.set(0, 1, 1.5);
        cameraRef.current = cam;

        const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
        renderer.setSize(w, h);
        renderer.setPixelRatio(window.devicePixelRatio);
        renderer.outputColorSpace = THREE.SRGBColorSpace;
        rendererRef.current = renderer;

        scene.add(new THREE.DirectionalLight(1, 1).translateX(1).translateY(1).translateZ(1));
        scene.add(new THREE.AmbientLight(0xffffff, 0.5));

        const loader = new GLTFLoader();
        loader.register((p) => new VRMLoaderPlugin(p));
        const gltf = await loader.loadAsync(url);

        if (cancelled || dataVersion !== lastVersionRef.current) return;

        const vrm = gltf.userData.vrm as VRM;
        if (!vrm) throw new Error('Not a VRM model');

        vrmRef.current = vrm;
        vrm.scene.scale.setScalar(propsRef.current.scale);
        vrm.scene.position.set(...propsRef.current.position);
        vrm.scene.rotation.y = Math.PI;
        scene.add(vrm.scene);

        lipSyncRef.current = new VRMAudioLipSync();
        lipSyncRef.current.bindVRM(vrm);

        if (!cancelled) setIsLoading(false);
        propsRef.current.onModelLoaded?.();

        const animate = () => {
          if (cancelled || dataVersion !== lastVersionRef.current) return;
          const dt = clockRef.current.getDelta();
          if (vrmRef.current) vrmRef.current.update(dt);
          if (rendererRef.current && sceneRef.current && cameraRef.current)
            rendererRef.current.render(sceneRef.current, cameraRef.current);
          animationFrameRef.current = requestAnimationFrame(animate);
        };
        animate();

        if (isBlob) activeBlobUrlRef.current = url;
      } catch (err) {
        if (cancelled || dataVersion !== lastVersionRef.current) return;
        console.error('[VRMViewer] Load failed:', err);
        const msg = err instanceof Error ? err.message : '';
        if (msg.includes('<!doctype') || msg.includes('Unexpected token')) setLoadError('MODEL_FILE_NOT_FOUND');
        else setLoadError('LOAD_FAILED');
        setIsLoading(false);
        propsRef.current.onError?.(err instanceof Error ? err : new Error(String(err)));
      } finally {
        if ((cancelled || dataVersion !== lastVersionRef.current) && isBlob) {
          URL.revokeObjectURL(url!);
        }
      }
    };

    loadModel();

    return () => {
      cancelled = true;
      if (animationFrameRef.current) cancelAnimationFrame(animationFrameRef.current);
      if (rendererRef.current) { try { rendererRef.current.dispose(); } catch(e){/*ignore*/} rendererRef.current = null; }
      if (activeBlobUrlRef.current) { URL.revokeObjectURL(activeBlobUrlRef.current); activeBlobUrlRef.current = null; }
    };
  }, [dataVersion, modelPath]);

  useEffect(() => {
    if (lipSyncEnabled && vrmRef.current && mouthOpenY !== undefined) {
      const em = vrmRef.current.expressionManager;
      if (em) {
        em.setValue(VRMExpressionPresetName.Aa, mouthOpenY * 0.8);
        em.setValue(VRMExpressionPresetName.Ou, mouthOpenY * 0.3);
        em.setValue(VRMExpressionPresetName.Ih, mouthOpenY * 0.2);
      }
    }
  }, [mouthOpenY, lipSyncEnabled]);

  useEffect(() => {
    if (!lookAtMouse || !vrmRef.current) return;
    const h = (e: MouseEvent) => {
      if (!vrmRef.current || !canvasRef.current) return;
      const r = canvasRef.current.getBoundingClientRect();
      const x = ((e.clientX - r.left) / r.width) * 2 - 1;
      const y = -((e.clientY - r.top) / r.height) * 2 + 1;
      const la = vrmRef.current.lookAt;
      if (la?.target) la.target.position.set(x * 2, y * 1.5 + 1, 1.5);
    };
    window.addEventListener('mousemove', h);
    return () => window.removeEventListener('mousemove', h);
  }, [lookAtMouse]);

  useEffect(() => {
    const h = () => {
      if (!canvasRef.current || !rendererRef.current || !cameraRef.current) return;
      const w = canvasRef.current.clientWidth, h2 = canvasRef.current.clientHeight;
      rendererRef.current.setSize(w, h2);
      cameraRef.current.aspect = w / h2;
      cameraRef.current.updateProjectionMatrix();
    };
    window.addEventListener('resize', h);
    return () => window.removeEventListener('resize', h);
  }, []);

  useEffect(() => { if (vrmRef.current) vrmRef.current.scene.scale.setScalar(scale); }, [scale]);
  useEffect(() => { if (vrmRef.current) vrmRef.current.scene.position.set(position[0], position[1], position[2]); }, [position]);

  if (loadError) {
    const m: Record<string, string> = { MODEL_NOT_CONFIGURED: '模型未配置', MODEL_FILE_NOT_FOUND: '模型文件不存在', LOAD_FAILED: '模型加载失败' };
    return (
      <div className="flex flex-col items-center justify-center h-full text-center p-4">
        <svg className="w-16 h-16 mx-auto text-[var(--color-text-tertiary)]" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" /></svg>
        <p className="text-sm text-[var(--color-text-secondary)] mt-3">{m[loadError] ?? '?'}</p>
        <p className="text-xs text-[var(--color-text-tertiary)] mt-1">请上传模型或刷新页面</p>
      </div>
    );
  }

  return (
    <div className="relative w-full h-full">
      {isLoading && <div className="absolute inset-0 flex items-center justify-center bg-[var(--color-bg-secondary)]"><div className="flex flex-col items-center"><div className="w-8 h-8 border-2 border-[var(--color-accent)] border-t-transparent rounded-full animate-spin" /><p className="text-sm text-[var(--color-text-secondary)] mt-2">加载中...</p></div></div>}
      <canvas ref={canvasRef} className="w-full h-full" style={{ opacity: isLoading ? 0 : 1 }} />
    </div>
  );
}
