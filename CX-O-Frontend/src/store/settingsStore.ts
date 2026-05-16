import { create } from 'zustand';
import { persist } from 'zustand/middleware';

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
  setAvatarType: (type: AvatarType) => void;
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
}

const defaultLive2DSettings: Live2DSettings = {
  enabled: false,
  modelPath: '/models/shizuku/shizuku.model.json',
  width: 300,
  minWidth: 200,
  maxWidth: 400,
  position: 'left',
  lipSync: true,
  idleMotion: true,
  scale: 0.3,
  xOffset: 0,
  yOffset: 0,
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

      setAvatarType: (type) =>
        set((state) => ({
          avatarType: type,
          live2d: { ...state.live2d, enabled: type === 'live2d' },
          vrm: { ...state.vrm, enabled: type === 'vrm' },
        })),

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
        set((state) => ({
          layout: {
            ...state.layout,
            live2dWidth: Math.max(state.live2d.minWidth, Math.min(state.live2d.maxWidth, width)),
          },
        })),

      setVRMWidth: (width) =>
        set((state) => ({
          layout: {
            ...state.layout,
            vrmWidth: Math.max(state.vrm.minWidth, Math.min(state.vrm.maxWidth, width)),
          },
        })),
    }),
    {
      name: 'cxhms-settings',
      partialize: (state) => ({
        avatarType: state.avatarType,
        live2d: state.live2d,
        vrm: state.vrm,
        layout: state.layout,
      }),
    }
  )
);

export const getLive2DSettings = () => useSettingsStore.getState().live2d;
export const getVRMSettings = () => useSettingsStore.getState().vrm;
export const getLayoutSettings = () => useSettingsStore.getState().layout;
