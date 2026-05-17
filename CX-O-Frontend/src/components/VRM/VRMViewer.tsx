import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { VRM, VRMLoaderPlugin, VRMExpressionPresetName } from '@pixiv/three-vrm';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMTweakConfig, DEFAULT_VRM_TWEAK, AnimationSettings, DEFAULT_ANIMATION_SETTINGS } from '../../store/settingsStore';
import { VRMLipSync } from './VRMLipSync';
import { VRMExpression } from './VRMExpression';
import { VRMAnimation } from './VRMAnimation';
import { VowelAnalyzer } from './VowelAnalyzer';

export type { VRMTweakConfig };
export { DEFAULT_VRM_TWEAK as DEFAULT_TWEAK_CONFIG };

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
  tweakConfig?: Partial<VRMTweakConfig>;
  animationConfig?: Partial<AnimationSettings>;
  renderScale?: number;
  devicePixelRatio?: number | 'auto';
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
  tweakConfig,
  animationConfig,
  renderScale = 1.0,
  devicePixelRatio = 'auto',
}: VRMViewerProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const sceneRef = useRef<THREE.Scene | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const vrmRef = useRef<VRM | null>(null);
  const clockRef = useRef(new THREE.Timer());
  const lipSyncRef = useRef<VRMLipSync | null>(null);
  const expressionRef = useRef<VRMExpression | null>(null);
  const animationRef = useRef<VRMAnimation | null>(null);
  const vowelAnalyzerRef = useRef<VowelAnalyzer | null>(null);
  const animationFrameRef = useRef<number | null>(null);

  const dirLightRef = useRef<THREE.DirectionalLight | null>(null);
  const ambLightRef = useRef<THREE.AmbientLight | null>(null);
  const pntLightRef = useRef<THREE.PointLight | null>(null);

  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [modelSize, setModelSize] = useState<{ height: number; width: number }>({ height: 1.6, width: 0.8 });

  const propsRef = useRef({ scale, position, onModelLoaded, onError, renderScale, devicePixelRatio });
  const lastVersionRef = useRef(-1);
  const renderIdRef = useRef(0);

  const effectiveTweak = useRef<Partial<VRMTweakConfig>>(tweakConfig || {});
  if (tweakConfig) effectiveTweak.current = tweakConfig;
  const tc: VRMTweakConfig = { ...DEFAULT_VRM_TWEAK, ...effectiveTweak.current };

  const effectiveAnim = useRef<Partial<AnimationSettings>>(animationConfig || {});
  if (animationConfig) effectiveAnim.current = animationConfig;
  const ac: AnimationSettings = { ...DEFAULT_ANIMATION_SETTINGS, ...effectiveAnim.current };

  useEffect(() => {
    if (dataVersion === lastVersionRef.current) return;
    lastVersionRef.current = dataVersion;
    const myRenderId = ++renderIdRef.current;

    console.log(`[VRMViewer] Load #${dataVersion} (r=${myRenderId})`);

    const loadModel = async () => {
      const data = modelDataRef?.current;
      console.log(`[VRMViewer] r=${myRenderId} modelData:`, data ? `${data.byteLength} bytes` : 'null');
      const useBuf = data && data.byteLength > 0;
      const usePath = !useBuf && modelPath?.length;

      if (!useBuf && !usePath) { setLoadError('MODEL_NOT_CONFIGURED'); setIsLoading(false); return; }

      let url: string | null = null;
      if (useBuf) url = URL.createObjectURL(new Blob([data], { type: 'application/octet-stream' }));
      else url = modelPath;
      if (!url) return;

      try {
        setIsLoading(true); setLoadError(null);
        if (rendererRef.current) { try { rendererRef.current.dispose(); } catch(e){/*ignore*/} rendererRef.current = null; }

        console.log(`[VRMViewer] r=${myRenderId} Waiting for canvas...`);
        const canvas = await waitForCanvas();
        console.log(`[VRMViewer] r=${myRenderId} Canvas obtained:`, canvas.clientWidth, 'x', canvas.clientHeight);

        const w = canvas.clientWidth || 300, h = canvas.clientHeight || 400;
        const scene = new THREE.Scene(); sceneRef.current = scene;
        const cam = new THREE.PerspectiveCamera(30, w / h, 0.1, 20); cameraRef.current = cam;

        console.log(`[VRMViewer] r=${myRenderId} Creating WebGLRenderer...`);
        const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
        console.log(`[VRMViewer] r=${myRenderId} WebGLRenderer OK`);
        const dpr = devicePixelRatio === 'auto' ? window.devicePixelRatio : devicePixelRatio;
        renderer.setPixelRatio(dpr * renderScale);
        renderer.setSize(w * renderScale, h * renderScale, false); renderer.outputColorSpace = THREE.SRGBColorSpace; rendererRef.current = renderer;

        const dl = new THREE.DirectionalLight(0xffffff, tc.light.directionalIntensity); dl.position.set(1,1.5,1); dirLightRef.current=dl; scene.add(dl);
        const al = new THREE.AmbientLight(0xffffff, tc.light.ambientIntensity); ambLightRef.current=al; scene.add(al);
        const pl = new THREE.PointLight(0xffffff, tc.light.pointIntensity,10); pl.position.set(-1,1,1); pntLightRef.current=pl; scene.add(pl);

        console.log(`[VRMViewer] r=${myRenderId} Starting GLTF load...`);
        const loader = new GLTFLoader(); loader.register((p) => new VRMLoaderPlugin(p));
        const gltf = await loader.loadAsync(url);
        console.log(`[VRMViewer] r=${myRenderId} GLTF loaded`);

        if (renderIdRef.current !== myRenderId) { console.log(`[VRMViewer] r=${myRenderId} Superseded`); return; }

        const vrm = gltf.userData.vrm as VRM;
        if (!vrm) throw new Error('Not a VRM model');

        vrmRef.current = vrm;
        vrm.scene.scale.setScalar(propsRef.current.scale);
        vrm.scene.rotation.x = tc.modelRotationX; vrm.scene.rotation.y = tc.modelRotationY; vrm.scene.rotation.z = tc.modelRotationZ;

        // Apply natural idle pose
        const humanoid = vrm.humanoid;
        if (humanoid) {
          const setRot = (name: string, x: number, y: number, z: number) => {
            const bone = humanoid.getNormalizedBoneNode(name as any);
            if (bone) bone.rotation.set(x, y, z);
          };
          setRot('leftUpperArm', 0, 0, 0.3);
          setRot('rightUpperArm', 0, 0, -0.3);
          setRot('leftLowerArm', 0, 0, 0.1);
          setRot('rightLowerArm', 0, 0, -0.1);
          setRot('leftUpperLeg', 0.1, 0, 0);
          setRot('rightUpperLeg', -0.1, 0, 0);
          setRot('leftLowerLeg', 0.05, 0, 0);
          setRot('rightLowerLeg', -0.05, 0, 0);
          setRot('spine', 0, 0, 0);
          setRot('chest', 0, 0, 0);
        }

        const box = new THREE.Box3().setFromObject(vrm.scene);
        const size = box.getSize(new THREE.Vector3());
        const height = Math.max(size.y, 0.1), width = Math.max(size.x, 0.1);
        setModelSize({ height, width });
        vrm.scene.position.set(0, -box.min.y * propsRef.current.scale, 0);
        vrm.scene.position.x += propsRef.current.position[0]; vrm.scene.position.y += propsRef.current.position[1]; vrm.scene.position.z += propsRef.current.position[2];
        cam.position.set(tc.camera.offsetX, height * 0.7 + tc.camera.offsetY, Math.max(width * 2.5, tc.camera.offsetZ));
        cam.lookAt(0, height * tc.camera.lookAtY, 0);
        scene.add(vrm.scene);

        // Initialize new systems
        lipSyncRef.current = new VRMLipSync();
        lipSyncRef.current.bindVRM(vrm);
        lipSyncRef.current.setSmoothing(ac.lipSyncSmoothing);

        expressionRef.current = new VRMExpression();
        expressionRef.current.bindVRM(vrm);
        expressionRef.current.setConfig({
          intensity: ac.emotionIntensity,
          duration: ac.emotionDuration,
          recoverSpeed: ac.emotionRecoverSpeed,
        });

        animationRef.current = new VRMAnimation();
        animationRef.current.bindVRM(vrm);
        animationRef.current.setConfig({
          breathFrequency: ac.breathFrequency,
          breathAmplitude: ac.breathAmplitude,
          blinkInterval: ac.blinkInterval,
          blinkDuration: ac.blinkDuration,
          headFollowSpeed: ac.headFollowSpeed,
          bodyFollowDelay: ac.bodyFollowDelay,
        });

        setIsLoading(false);
        propsRef.current.onModelLoaded?.();

        const animate = () => {
          if (renderIdRef.current !== myRenderId) return;
          const dt = clockRef.current.getDelta();

          if (vrmRef.current) vrmRef.current.update(dt);
          if (lipSyncRef.current) lipSyncRef.current.update(dt);
          if (expressionRef.current) expressionRef.current.update(dt);
          if (animationRef.current) animationRef.current.update(dt);

          if (rendererRef.current && sceneRef.current && cameraRef.current) rendererRef.current.render(sceneRef.current, cameraRef.current);
          animationFrameRef.current = requestAnimationFrame(animate);
        };
        animate();
      } catch (err) {
        if (renderIdRef.current !== myRenderId) return;
        console.error(`[VRMViewer] r=${myRenderId} Failed:`, err);
        const msg = err instanceof Error ? err.message : '';
        if (msg.includes('<!doctype') || msg.includes('Unexpected token')) setLoadError('MODEL_FILE_NOT_FOUND');
        else setLoadError('LOAD_FAILED');
        setIsLoading(false);
        propsRef.current.onError?.(err instanceof Error ? err : new Error(String(err)));
      } finally { if (url.startsWith('blob:')) URL.revokeObjectURL(url); }
    };

    const waitForCanvas = (): Promise<HTMLCanvasElement> =>
      new Promise((resolve) => {
        let n = 0;
        const check = () => {
          const c = canvasRef.current;
          if (c && c.clientWidth > 0 && c.clientHeight > 0) resolve(c);
          else if (++n >= 200) resolve(c || document.createElement('canvas'));
          else requestAnimationFrame(check);
        };
        check();
      });

    loadModel();

    return () => {
      if (animationFrameRef.current) cancelAnimationFrame(animationFrameRef.current);
      if (rendererRef.current) { try { rendererRef.current.dispose(); } catch(e){/*ignore*/} rendererRef.current = null; }
      if (vowelAnalyzerRef.current) { vowelAnalyzerRef.current.stop(); vowelAnalyzerRef.current = null; }
    };
  }, [dataVersion, modelPath]);

  // Update animation config
  useEffect(() => {
    if (animationRef.current) {
      animationRef.current.setConfig({
        breathFrequency: ac.breathFrequency,
        breathAmplitude: ac.breathAmplitude,
        blinkInterval: ac.blinkInterval,
        blinkDuration: ac.blinkDuration,
        headFollowSpeed: ac.headFollowSpeed,
        bodyFollowDelay: ac.bodyFollowDelay,
      });
    }
    if (expressionRef.current) {
      expressionRef.current.setConfig({
        intensity: ac.emotionIntensity,
        duration: ac.emotionDuration,
        recoverSpeed: ac.emotionRecoverSpeed,
      });
    }
    if (lipSyncRef.current) {
      lipSyncRef.current.setSmoothing(ac.lipSyncSmoothing);
    }
  }, [ac.breathFrequency, ac.breathAmplitude, ac.blinkInterval, ac.blinkDuration,
      ac.headFollowSpeed, ac.bodyFollowDelay, ac.emotionIntensity, ac.emotionDuration,
      ac.emotionRecoverSpeed, ac.lipSyncSmoothing]);

  useEffect(() => {
    if (dirLightRef.current) dirLightRef.current.intensity = tc.light.directionalIntensity;
    if (ambLightRef.current) ambLightRef.current.intensity = tc.light.ambientIntensity;
    if (pntLightRef.current) pntLightRef.current.intensity = tc.light.pointIntensity;
  }, [tc.light.directionalIntensity, tc.light.ambientIntensity, tc.light.pointIntensity]);

  useEffect(() => {
    if (vrmRef.current) {
      vrmRef.current.scene.rotation.x = tc.modelRotationX;
      vrmRef.current.scene.rotation.y = tc.modelRotationY;
      vrmRef.current.scene.rotation.z = tc.modelRotationZ;
    }
  }, [tc.modelRotationX, tc.modelRotationY, tc.modelRotationZ]);

  useEffect(() => {
    const cam = cameraRef.current;
    if (!cam) return;
    const { height } = modelSize;
    cam.position.set(tc.camera.offsetX, height * 0.7 + tc.camera.offsetY, Math.max(modelSize.width * 2.5, tc.camera.offsetZ));
    cam.lookAt(0, height * tc.camera.lookAtY, 0);
  }, [tc.camera.offsetX, tc.camera.offsetY, tc.camera.offsetZ, tc.camera.lookAtY, modelSize]);

  // New vowel-based lip sync
  useEffect(() => {
    if (!lipSyncEnabled || !vrmRef.current) return;

    // For now, use the simple mouthOpenY as fallback
    // In a full implementation, this would connect to the audio analyzer
    const em = vrmRef.current.expressionManager;
    if (em) {
      em.setValue(VRMExpressionPresetName.Aa, mouthOpenY * 0.8 * ac.vowelWeightA);
      em.setValue(VRMExpressionPresetName.Ih, mouthOpenY * 0.2 * ac.vowelWeightI);
      em.setValue(VRMExpressionPresetName.Ou, mouthOpenY * 0.3 * ac.vowelWeightU);
      em.setValue(VRMExpressionPresetName.Ee, mouthOpenY * 0.15 * ac.vowelWeightE);
      em.setValue(VRMExpressionPresetName.Oh, mouthOpenY * 0.25 * ac.vowelWeightO);
    }
  }, [mouthOpenY, lipSyncEnabled, ac.vowelWeightA, ac.vowelWeightI, ac.vowelWeightU, ac.vowelWeightE, ac.vowelWeightO]);

  useEffect(() => {
    if (!lookAtMouse || !vrmRef.current) return;
    const h = (e: MouseEvent) => {
      if (!vrmRef.current || !canvasRef.current) return;
      const r = canvasRef.current.getBoundingClientRect();
      const x = ((e.clientX - r.left) / r.width) * 2 - 1;
      const y = -((e.clientY - r.top) / r.height) * 2 + 1;
      const la = vrmRef.current.lookAt;
      if (la?.target) la.target.position.set(x * 2, y * 1.5 + 1, 1.5);

      // Update animation head target
      if (animationRef.current) {
        animationRef.current.setHeadTarget(x * 2, y * 1.5 + 1, 1.5);
      }
    };
    window.addEventListener('mousemove', h);
    return () => window.removeEventListener('mousemove', h);
  }, [lookAtMouse]);

  useEffect(() => {
    const h = () => {
      if (!canvasRef.current || !rendererRef.current || !cameraRef.current) return;
      const w = canvasRef.current.clientWidth, h2 = canvasRef.current.clientHeight;
      const dpr = propsRef.current.devicePixelRatio === 'auto' ? window.devicePixelRatio : propsRef.current.devicePixelRatio;
      rendererRef.current.setPixelRatio(dpr * propsRef.current.renderScale);
      rendererRef.current.setSize(w * propsRef.current.renderScale, h2 * propsRef.current.renderScale, false);
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
      <canvas ref={canvasRef} className="w-full h-full block" style={{ opacity: isLoading ? 0 : 1, minWidth: '100%', minHeight: '100%' }} />
    </div>
  );
}
