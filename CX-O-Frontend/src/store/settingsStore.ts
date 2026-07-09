import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { createStorage } from '../lib/createStorage';
import { api } from '../api/client';
import type { FrontendLimits } from '../api/client';

export interface Live2DSettings {
  enabled: boolean;
  modelId?: string;
  modelPath: string;
  width: number;
  minWidth: number;
  maxWidth: number;
  position: 'left' | 'right';
  lipSync: boolean;
  idleMotion: boolean;
  scale: number;
  xOffset: number;
  yOffset: number;
  expressionMixEnabled: boolean;
  animation?: AnimationSettings;
}

export interface VRMCameraTweak {
  offsetX: number;
  offsetY: number;
  offsetZ: number;
  lookAtY: number;
}

export interface VRMLightTweak {
  directionalIntensity: number;
  ambientIntensity: number;
  pointIntensity: number;
}

export interface VRMTweakConfig {
  camera: VRMCameraTweak;
  light: VRMLightTweak;
  modelRotationX: number;
  modelRotationY: number;
  modelRotationZ: number;
}

export const DEFAULT_VRM_TWEAK: VRMTweakConfig = {
  camera: { offsetX: 0, offsetY: 1.2, offsetZ: 2.5, lookAtY: 0.45 },
  light: { directionalIntensity: 2, ambientIntensity: 1.2, pointIntensity: 0.8 },
  modelRotationX: 0,
  modelRotationY: Math.PI,
  modelRotationZ: 0,
};

export interface AnimationSettings {
  lipSyncSensitivity: number;
  lipSyncSmoothing: number;
  vowelWeightA: number;
  vowelWeightI: number;
  vowelWeightU: number;
  vowelWeightE: number;
  vowelWeightO: number;
  emotionIntensity: number;
  emotionDuration: number;
  emotionRecoverSpeed: number;
  idleExpressionIntensity: number;
  breathFrequency: number;
  breathAmplitude: number;
  breathIrregularity: number;
  blinkInterval: number;
  blinkDuration: number;
  swayAmplitude: number;
  swayFrequency: number;
  swayIrregularity: number;
  headFollowSpeed: number;
  bodyFollowDelay: number;
  headIdleRange: number;
  headTrackingLimit: number;
  eyeTrackingEnabled: boolean;
  motionTriggerProbability: number;
  speechMotionInterval: number;
  focusSpeed: number;
}

export const DEFAULT_ANIMATION_SETTINGS: AnimationSettings = {
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
  idleExpressionIntensity: 0.1,
  breathFrequency: 0.3,
  breathAmplitude: 0.02,
  breathIrregularity: 0.2,
  blinkInterval: 3.0,
  blinkDuration: 0.15,
  swayAmplitude: 0.02,
  swayFrequency: 0.3,
  swayIrregularity: 0.3,
  headFollowSpeed: 2.0,
  bodyFollowDelay: 0.3,
  headIdleRange: 0.03,
  headTrackingLimit: 0.5,
  eyeTrackingEnabled: true,
  motionTriggerProbability: 0.5,
  speechMotionInterval: 1.5,
  focusSpeed: 3.0,
};

export interface VRMWindConfig {
  direction: number;
  strength: number;
  gustStrength: number;
  gustFrequency: number;
  gustDuration: number | string;
}

export interface VRMSettings {
  enabled: boolean;
  modelId?: string;
  modelPath: string;
  width: number;
  minWidth: number;
  maxWidth: number;
  position: 'left' | 'right';
  lipSync: boolean;
  idleAnimation: boolean;
  lookAtMouse: boolean;
  scale: number;
  position3d: [number, number, number];
  tweak?: VRMTweakConfig;
  expressionMixEnabled: boolean;
  motionTriggerEnabled: boolean;
  animation?: AnimationSettings;
  renderScale: number;
  devicePixelRatio: number | 'auto';
  wind: VRMWindConfig;
  windAffectedGroups: Array<{ boneNames: string[]; enabled: boolean }>;
}

export interface LayoutSettings {
  chatCollapsed: boolean;
  live2dCollapsed: boolean;
  live2dWidth: number;
  vrmCollapsed: boolean;
  vrmWidth: number;
}

export type AvatarType = 'live2d' | 'vrm' | 'none';

interface SettingsState {
  avatarType: AvatarType;
  live2d: Live2DSettings;
  vrm: VRMSettings;
  layout: LayoutSettings;
  autoSave: boolean;
  limits: FrontendLimits | null;
  setAvatarType: (type: AvatarType) => void;
  setAutoSave: (v: boolean) => void;
  setLive2DSettings: (settings: Partial<Live2DSettings>) => void;
  setVRMSettings: (settings: Partial<VRMSettings>) => void;
  setLive2DModelId: (modelId: string | undefined) => void;
  setVRMModelId: (modelId: string | undefined) => void;
  setLayoutSettings: (settings: Partial<LayoutSettings>) => void;
  toggleLive2D: () => void;
  toggleVRM: () => void;
  toggleChatCollapsed: () => void;
  toggleLive2DCollapsed: () => void;
  toggleVRMCollapsed: () => void;
  setLive2DWidth: (width: number) => void;
  setVRMWidth: (width: number) => void;
  fetchLimits: () => Promise<void>;
}

const defaultLive2DSettings: Live2DSettings = {
  enabled: false,
  modelPath: '/models/shizuku/shizuku.model.json',
  width: 300,
  minWidth: 100,
  maxWidth: 1200,
  position: 'left',
  lipSync: true,
  idleMotion: true,
  scale: 0.3,
  xOffset: 0,
  yOffset: 0,
  expressionMixEnabled: true,
  animation: DEFAULT_ANIMATION_SETTINGS,
};

const defaultVRMSettings: VRMSettings = {
  enabled: false,
  modelPath: '/models/avatar.vrm',
  width: 300,
  minWidth: 200,
  maxWidth: 400,
  position: 'left',
  lipSync: true,
  idleAnimation: true,
  lookAtMouse: true,
  scale: 1.0,
  position3d: [0, 0, 0],
  tweak: DEFAULT_VRM_TWEAK,
  expressionMixEnabled: true,
  motionTriggerEnabled: true,
  animation: DEFAULT_ANIMATION_SETTINGS,
  renderScale: 1.0,
  devicePixelRatio: 'auto',
  wind: {
    direction: 0,
    strength: 0,
    gustStrength: 0,
    gustFrequency: 0,
    gustDuration: 0,
  },
  windAffectedGroups: [],
};

const defaultLayoutSettings: LayoutSettings = {
  chatCollapsed: false,
  live2dCollapsed: false,
  live2dWidth: 300,
  vrmCollapsed: false,
  vrmWidth: 300,
};

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set) => ({
      avatarType: 'none',
      live2d: defaultLive2DSettings,
      vrm: defaultVRMSettings,
      layout: defaultLayoutSettings,
      autoSave: true,
      limits: null,

      setAvatarType: (type) =>
        set((state) => ({
          avatarType: type,
          live2d: { ...state.live2d, enabled: type === 'live2d' },
          vrm: { ...state.vrm, enabled: type === 'vrm' },
        })),

      setAutoSave: (v) => set({ autoSave: v }),

      setLive2DSettings: (settings) =>
        set((state) => ({
          live2d: { ...state.live2d, ...settings },
        })),

      setVRMSettings: (settings) =>
        set((state) => ({
          vrm: { ...state.vrm, ...settings },
        })),

      setLive2DModelId: (modelId) =>
        set((state) => ({
          live2d: { ...state.live2d, modelId },
        })),

      setVRMModelId: (modelId) =>
        set((state) => ({
          vrm: { ...state.vrm, modelId },
        })),

      setLayoutSettings: (settings) =>
        set((state) => ({
          layout: { ...state.layout, ...settings },
        })),

      toggleLive2D: () =>
        set((state) => {
          const newEnabled = !state.live2d.enabled;
          return {
            avatarType: newEnabled ? 'live2d' : (state.vrm.enabled ? 'vrm' : 'none'),
            live2d: { ...state.live2d, enabled: newEnabled },
            vrm: { ...state.vrm, enabled: false },
          };
        }),

      toggleVRM: () =>
        set((state) => {
          const newEnabled = !state.vrm.enabled;
          return {
            avatarType: newEnabled ? 'vrm' : (state.live2d.enabled ? 'live2d' : 'none'),
            vrm: { ...state.vrm, enabled: newEnabled },
            live2d: { ...state.live2d, enabled: false },
          };
        }),

      toggleChatCollapsed: () =>
        set((state) => ({
          layout: { ...state.layout, chatCollapsed: !state.layout.chatCollapsed },
        })),

      toggleLive2DCollapsed: () =>
        set((state) => ({
          layout: { ...state.layout, live2dCollapsed: !state.layout.live2dCollapsed },
        })),

      toggleVRMCollapsed: () =>
        set((state) => ({
          layout: { ...state.layout, vrmCollapsed: !state.layout.vrmCollapsed },
        })),

      setLive2DWidth: (width) =>
        set((state) => {
          const minW = state.limits?.avatar_min_width ?? state.live2d.minWidth;
          const maxW = state.limits?.avatar_max_width ?? state.live2d.maxWidth;
          return {
            layout: {
              ...state.layout,
              live2dWidth: Math.max(minW, Math.min(maxW, width)),
            },
          };
        }),

      setVRMWidth: (width) =>
        set((state) => {
          const minW = state.limits?.avatar_min_width ?? state.vrm.minWidth;
          const maxW = state.limits?.avatar_max_width ?? state.vrm.maxWidth;
          return {
            layout: {
              ...state.layout,
              vrmWidth: Math.max(minW, Math.min(maxW, width)),
            },
          };
        }),

      fetchLimits: async () => {
        try {
          const limits = await api.getLimits();
          set({ limits });
        } catch {
          // fallback to defaults (already null)
        }
      },
    }),
    {
      name: 'cxhms-settings',
      storage: createStorage(),
      partialize: (state) => ({
        avatarType: state.avatarType,
        live2d: state.live2d,
        vrm: state.vrm,
        layout: state.layout,
        autoSave: state.autoSave,
      }),
      merge: (persisted, current) => {
        const p = (persisted as Partial<SettingsState>) || {};
        const pv = p.vrm;
        return {
          ...current,
          ...p,
          autoSave: typeof p.autoSave === 'boolean' ? p.autoSave : current.autoSave,
          vrm: {
            ...current.vrm,
            ...(pv || {}),
            animation: {
              ...current.vrm.animation,
              ...(pv?.animation || {}),
            } as AnimationSettings,
            wind: {
              ...current.vrm.wind,
              ...(pv?.wind || {}),
            } as VRMWindConfig,
          },
          live2d: {
            ...current.live2d,
            ...(p.live2d || {}),
            animation: {
              ...current.live2d.animation,
              ...((p.live2d as Live2DSettings | undefined)?.animation || {}),
            } as AnimationSettings,
          },
          layout: {
            ...current.layout,
            ...(p.layout || {}),
          },
        } as SettingsState;
      },
    }
  )
);

export const getLive2DSettings = () => useSettingsStore.getState().live2d;
export const getVRMSettings = () => useSettingsStore.getState().vrm;
export const getLayoutSettings = () => useSettingsStore.getState().layout;
