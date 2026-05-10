import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { VRM, VRMLoaderPlugin, VRMExpressionPresetName } from '@pixiv/three-vrm';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMAudioLipSync } from './AudioLipSync';

interface VRMViewerProps {
  modelPath: string;
  modelData?: ArrayBuffer;
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
  modelData,
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
  const blobUrlRef = useRef<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [isCanvasReady, setIsCanvasReady] = useState(false);
  const propsRef = useRef({ scale, position, onModelLoaded, onError });

  propsRef.current = { scale, position, onModelLoaded, onError };

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    let checkCount = 0;
    const maxChecks = 50;

    const checkCanvasReady = () => {
      if (canvas.clientWidth > 0 && canvas.clientHeight > 0) {
        console.log('[VRMViewer] Canvas ready:', canvas.clientWidth, 'x', canvas.clientHeight);
        setIsCanvasReady(true);
      } else if (checkCount < maxChecks) {
        checkCount++;
        requestAnimationFrame(checkCanvasReady);
      } else {
        console.log('[VRMViewer] Canvas timeout, using fallback size');
        setIsCanvasReady(true);
      }
    };

    checkCanvasReady();
  }, []);

  useEffect(() => {
    if (!isCanvasReady) return;

    console.log('[VRMViewer] useEffect triggered, modelData:', modelData ? `${modelData.byteLength} bytes` : 'none', 'modelPath:', JSON.stringify(modelPath));

    let cancelled = false;

    const loadModel = async () => {
      const canvas = canvasRef.current;
      if (!canvas) {
        console.log('[VRMViewer] No canvas ref');
        return;
      }

      let effectiveModelPath: string | null = null;
      let createdBlobUrl = false;

      if (modelData && modelData.byteLength > 0) {
        const blob = new Blob([modelData], { type: 'application/octet-stream' });
        effectiveModelPath = URL.createObjectURL(blob);
        createdBlobUrl = true;
        console.log('[VRMViewer] Created blob URL from modelData');
      } else if (modelPath && modelPath.length > 0) {
        effectiveModelPath = modelPath;
        console.log('[VRMViewer] Using modelPath');
      }

      if (!effectiveModelPath) {
        console.log('[VRMViewer] No valid path or data, showing MODEL_NOT_CONFIGURED');
        if (!cancelled) setLoadError('MODEL_NOT_CONFIGURED');
        if (!cancelled) setIsLoading(false);
        return;
      }

      console.log('[VRMViewer] Loading from:', createdBlobUrl ? 'Blob URL' : effectiveModelPath);

      if (blobUrlRef.current && blobUrlRef.current.startsWith('blob:')) {
        URL.revokeObjectURL(blobUrlRef.current);
      }
      if (createdBlobUrl) {
        blobUrlRef.current = effectiveModelPath;
      }

      if (cancelled) return;

      try {
        if (!cancelled) setIsLoading(true);
        if (!cancelled) setLoadError(null);

        if (rendererRef.current) {
          try {
            rendererRef.current.dispose();
          } catch (e) {
            console.warn('[VRMViewer] Error disposing old renderer:', e);
          }
          rendererRef.current = null;
        }

        const width = canvas.clientWidth || 300;
        const height = canvas.clientHeight || 400;
        console.log('[VRMViewer] Canvas size:', width, 'x', height);

        const scene = new THREE.Scene();
        sceneRef.current = scene;

        const camera = new THREE.PerspectiveCamera(30.0, width / height, 0.1, 20.0);
        camera.position.set(0.0, 1.0, 1.5);
        cameraRef.current = camera;

        console.log('[VRMViewer] Creating WebGLRenderer...');
        const renderer = new THREE.WebGLRenderer({
          canvas: canvas,
          alpha: true,
          antialias: true,
        });
        console.log('[VRMViewer] WebGLRenderer created successfully');

        renderer.setSize(width, height);
        renderer.setPixelRatio(window.devicePixelRatio);
        renderer.outputColorSpace = THREE.SRGBColorSpace;
        rendererRef.current = renderer;

        const light = new THREE.DirectionalLight(0xffffff, 1.0);
        light.position.set(1.0, 1.0, 1.0).normalize();
        scene.add(light);

        const ambientLight = new THREE.AmbientLight(0xffffff, 0.5);
        scene.add(ambientLight);

        console.log('[VRMViewer] Starting GLTF load...');
        const loader = new GLTFLoader();
        loader.register((parser) => new VRMLoaderPlugin(parser));

        const gltf = await loader.loadAsync(effectiveModelPath);
        
        if (cancelled) {
          console.log('[VRMViewer] Load cancelled after async');
          return;
        }

        console.log('[VRMViewer] GLTF loaded, userData:', Object.keys(gltf.userData));
        const vrm = gltf.userData.vrm as VRM;
        if (!vrm) {
          throw new Error('Loaded file is not a valid VRM model (no vrm in userData)');
        }
        vrmRef.current = vrm;
        console.log('[VRMViewer] VRM model loaded successfully');

        vrm.scene.scale.setScalar(propsRef.current.scale);
        vrm.scene.position.set(propsRef.current.position[0], propsRef.current.position[1], propsRef.current.position[2]);
        vrm.scene.rotation.y = Math.PI;
        scene.add(vrm.scene);

        const lipSync = new VRMAudioLipSync();
        lipSync.bindVRM(vrm);
        lipSyncRef.current = lipSync;

        if (!cancelled) setIsLoading(false);
        propsRef.current.onModelLoaded?.();

        const animate = () => {
          if (cancelled) return;
          
          const delta = clockRef.current.getDelta();

          if (vrmRef.current) {
            vrmRef.current.update(delta);
          }

          if (rendererRef.current && sceneRef.current && cameraRef.current) {
            rendererRef.current.render(sceneRef.current, cameraRef.current);
          }

          animationFrameRef.current = requestAnimationFrame(animate);
        };

        animate();
      } catch (error) {
        if (cancelled) return;
        console.error('VRM: Failed to load model:', error);
        const errorMessage = error instanceof Error ? error.message : '';
        if (errorMessage.includes('<!doctype') || errorMessage.includes('Unexpected token')) {
          setLoadError('MODEL_FILE_NOT_FOUND');
        } else {
          setLoadError('LOAD_FAILED');
        }
        setIsLoading(false);
        propsRef.current.onError?.(error instanceof Error ? error : new Error('Failed to load model'));
      }
    };

    loadModel();

    return () => {
      cancelled = true;
      if (animationFrameRef.current) {
        cancelAnimationFrame(animationFrameRef.current);
        animationFrameRef.current = null;
      }
      if (rendererRef.current) {
        try {
          rendererRef.current.dispose();
        } catch (e) {
          // ignore
        }
        rendererRef.current = null;
      }
      if (blobUrlRef.current && blobUrlRef.current.startsWith('blob:')) {
        URL.revokeObjectURL(blobUrlRef.current);
        blobUrlRef.current = null;
      }
    };
  }, [modelPath, modelData, isCanvasReady]);

  useEffect(() => {
    if (lipSyncEnabled && vrmRef.current && mouthOpenY !== undefined) {
      const expressionManager = vrmRef.current.expressionManager;
      if (expressionManager) {
        expressionManager.setValue(VRMExpressionPresetName.Aa, mouthOpenY * 0.8);
        expressionManager.setValue(VRMExpressionPresetName.Ou, mouthOpenY * 0.3);
        expressionManager.setValue(VRMExpressionPresetName.Ih, mouthOpenY * 0.2);
      }
    }
  }, [mouthOpenY, lipSyncEnabled]);

  useEffect(() => {
    if (!lookAtMouse || !vrmRef.current) return;

    const handleMouseMove = (event: MouseEvent) => {
      if (!vrmRef.current || !canvasRef.current) return;

      const rect = canvasRef.current.getBoundingClientRect();
      const x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      const y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

      const lookAt = vrmRef.current.lookAt;
      if (lookAt && lookAt.target) {
        lookAt.target.position.set(x * 2, y * 1.5 + 1.0, 1.5);
      }
    };

    window.addEventListener('mousemove', handleMouseMove);
    return () => window.removeEventListener('mousemove', handleMouseMove);
  }, [lookAtMouse]);

  useEffect(() => {
    const handleResize = () => {
      if (!canvasRef.current || !rendererRef.current || !cameraRef.current) return;

      const width = canvasRef.current.clientWidth;
      const height = canvasRef.current.clientHeight;

      rendererRef.current.setSize(width, height);
      cameraRef.current.aspect = width / height;
      cameraRef.current.updateProjectionMatrix();
    };

    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  useEffect(() => {
    if (vrmRef.current) {
      vrmRef.current.scene.scale.setScalar(scale);
    }
  }, [scale]);

  useEffect(() => {
    if (vrmRef.current) {
      vrmRef.current.scene.position.set(position[0], position[1], position[2]);
    }
  }, [position]);

  if (loadError) {
    const isNotConfigured = loadError === 'MODEL_NOT_CONFIGURED';
    const isFileNotFound = loadError === 'MODEL_FILE_NOT_FOUND';
    return (
      <div className="flex flex-col items-center justify-center h-full text-center p-4">
        <div className="text-[var(--color-text-tertiary)] mb-3">
          <svg className="w-16 h-16 mx-auto" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
          </svg>
        </div>
        <p className="text-sm text-[var(--color-text-secondary)]">
          {isNotConfigured ? '模型未配置' : isFileNotFound ? '模型文件不存在' : '模型加载失败'}
        </p>
        <p className="text-xs text-[var(--color-text-tertiary)] mt-1">
          {isNotConfigured || isFileNotFound ? '请上传模型或检查模型路径' : '请检查模型文件是否存在且格式正确'}
        </p>
      </div>
    );
  }

  return (
    <div className="relative w-full h-full">
      {isLoading && (
        <div className="absolute inset-0 flex items-center justify-center bg-[var(--color-bg-secondary)]">
          <div className="flex flex-col items-center">
            <div className="w-8 h-8 border-2 border-[var(--color-accent)] border-t-transparent rounded-full animate-spin" />
            <p className="text-sm text-[var(--color-text-secondary)] mt-2">加载 VRM 模型...</p>
          </div>
        </div>
      )}
      <canvas
        ref={canvasRef}
        className="w-full h-full"
        style={{ opacity: isLoading ? 0 : 1 }}
      />
    </div>
  );
}
