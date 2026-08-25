/**
 * 桌宠多开面板状态：记录哪些 agent 已开启桌宠窗（持久化记忆）。
 * 仅用于管理界面展示/记忆，实际开/关窗口经 window:open-pet / window:close-pet IPC。
 */
import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { createStorage } from '../lib/createStorage';

interface PetPanelState {
  /** 已开启桌宠窗的 agentId 列表（持久化记忆） */
  openAgentIds: string[];
  /** 打开/关闭某 agent 桌宠（open=true 开启并记入；false 关闭并移除） */
  setOpen: (agentId: string, open: boolean) => void;
  /** 是否已开启 */
  isOpen: (agentId: string) => boolean;
}

export const usePetPanelStore = create<PetPanelState>()(
  persist(
    (set, get) => ({
      openAgentIds: [],
      setOpen: (agentId, open) =>
        set((s) => ({
          openAgentIds: open
            ? s.openAgentIds.includes(agentId)
              ? s.openAgentIds
              : [...s.openAgentIds, agentId]
            : s.openAgentIds.filter((id) => id !== agentId),
        })),
      isOpen: (agentId) => get().openAgentIds.includes(agentId),
    }),
    {
      name: 'cxo-pet-panel',
      storage: createStorage(),
      partialize: (s) => ({ openAgentIds: s.openAgentIds }),
    },
  ),
);