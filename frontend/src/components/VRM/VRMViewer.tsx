import { useEffect, useRef, useCallback, useState } from 'react';
import * as THREE from 'three';
import { VRM, VRMLoaderPlugin, VRMExpressionPresetName } from '@pixiv/three-vrm';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMAudioLipSync } from './AudioLipSync';

interface VRMViewerProps {
  modelPath: string;
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
  const clockRef = useRef<THREE.Clock>(new THREE.Clock());
  const lipSyncRef = useRef<VRMAudioLipSync | null>(null);
  const animationFrameRef = useRef<number | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const loadModel = useCallback(async () => {
    if (!canvasRef.current) return;

    try {
      setIsLoading(true);
      setLoadError(null);

      if (rendererRef.current) {
        rendererRef.current.dispose();
        rendererRef.current = null;
      }

      const width = canvasRef.current.clientWidth;
      const height = canvasRef.current.clientHeight;

      const scene = new THREE.Scene();
      sceneRef.current = scene;

      const camera = new THREE.PerspectiveCamera(30.0, width / height, 0.1, 20.0);
      camera.position.set(0.0, 1.0, 1.5);
      cameraRef.current = camera;

      const renderer = new THREE.WebGLRenderer({
        canvas: canvasRef.current,
        alpha: true,
        antialias: true,
      });
      renderer.setSize(width, height);
      renderer.setPixelRatio(window.devicePixelRatio);
      renderer.outputColorSpace = THREE.SRGBColorSpace;
      rendererRef.current = renderer;

      const light = new THREE.DirectionalLight(0xffffff, 1.0);
      light.position.set(1.0, 1.0, 1.0).normalize();
      scene.add(light);

      const ambientLight = new THREE.AmbientLight(0xffffff, 0.5);
      scene.add(ambientLight);

      const loader = new GLTFLoader();
      loader.register((parser) => new VRMLoaderPlugin(parser));

      const gltf = await loader.loadAsync(modelPath);
      const vrm = gltf.userData.vrm as VRM;
      vrmRef.current = vrm;

      vrm.scene.scale.setScalar(scale);
      vrm.scene.position.set(position[0], position[1], position[2]);
      scene.add(vrm.scene);

      const lipSync = new VRMAudioLipSync();
      lipSync.bindVRM(vrm);
      lipSyncRef.current = lipSync;

      setIsLoading(false);
      onModelLoaded?.();

      const animate = () => {
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
      console.error('VRM: Failed to load model:', error);
      const errorMessage = error instanceof Error ? error.message : 'Unknown error';
      setLoadError(errorMessage);
      setIsLoading(false);
      onError?.(error instanceof Error ? error : new Error(errorMessage));
    }
  }, [modelPath, scale, position, onModelLoaded, onError]);

  useEffect(() => {
    loadModel();

    return () => {
      if (animationFrameRef.current) {
        cancelAnimationFrame(animationFrameRef.current);
      }
      if (rendererRef.current) {
        rendererRef.current.dispose();
      }
    };
  }, [loadModel]);

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
    return (
      <div className="flex flex-col items-center justify-center h-full text-center p-4">
        <div className="text-red-500 mb-2">
          <svg className="w-12 h-12 mx-auto" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
        </div>
        <p className="text-sm text-[var(--color-text-secondary)]">VRM 模型加载失败</p>
        <p className="text-xs text-[var(--color-text-tertiary)] mt-1">{loadError}</p>
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
