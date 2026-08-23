/**
 * physio 域客户端：CX-O-Dream 生理信号（手环心率 BLE + SleepSensor 融合）访问层。
 * 端点面对齐后端 server/api/routers/physio.py（挂载前缀 /api）：
 *   GET  /api/physio/status
 *   GET  /api/physio/sleep
 *   GET  /api/physio/devices
 *   POST /api/physio/devices/{fp}/forget
 *   GET/PUT /api/physio/config
 *   POST /api/physio/clear
 *
 * 降级口径（对齐 dream.ts / autonomy.ts）：
 * - 查询类（getStatus/getSleep/getDevices/getConfig）失败返回 null，供 UI 降级展示；
 *   其中 getStatus 对「未启用」不抛错（后端返回 {"status": "disabled"}，HTTP 200）。
 * - 变更类（forgetDevice/updateConfig/clear）抛归一化错误（normalizeError），
 *   供 UI 捕获提示。
 */
import { request, normalizeError } from '../base';
import type {
  PhysioClearResult,
  PhysioConfig,
  PhysioDevicesResult,
  PhysioForgetResult,
  PhysioSleepState,
  PhysioStatus,
} from '../types';

export const physioApi = {
  /**
   * 生理信号状态快照。未启用返回 {status: "disabled"}（HTTP 200）；后端离线/
   * 网络失败返回 null，供 UI 展示错误态。
   */
  async getStatus(): Promise<PhysioStatus | null> {
    try {
      return await request<PhysioStatus>({ url: '/api/physio/status' });
    } catch {
      return null;
    }
  },

  /** SleepSensor 融合状态 + 各信号 value/weight + confidence；后端离线返回 null */
  async getSleep(): Promise<PhysioSleepState | null> {
    try {
      return await request<PhysioSleepState>({ url: '/api/physio/sleep' });
    } catch {
      return null;
    }
  },

  /** 已配对设备列表（指纹已脱敏）；后端离线返回 null */
  async getDevices(): Promise<PhysioDevicesResult | null> {
    try {
      return await request<PhysioDevicesResult>({ url: '/api/physio/devices' });
    } catch {
      return null;
    }
  },

  /**
   * 解除配对；传入 GET /physio/devices 返回的 `id`（真实指纹，非脱敏 fingerprint——
   * 脱敏指纹 forget 必 404）。设备未配对（404）或后端失败抛归一化错误
   */
  async forgetDevice(id: string): Promise<PhysioForgetResult> {
    try {
      return await request<PhysioForgetResult>({
        url: `/api/physio/devices/${encodeURIComponent(id)}/forget`,
        method: 'post',
      });
    } catch (err) {
      throw normalizeError(err);
    }
  },

  /** 当前 physio 配置（独立配置模块，未启用也可读）；后端离线返回 null */
  async getConfig(): Promise<PhysioConfig | null> {
    try {
      return await request<PhysioConfig>({ url: '/api/physio/config' });
    } catch {
      return null;
    }
  },

  /** 局部更新 physio 配置并保存（后端深度合并 + model_validate，非法字段/store_raw_hr=true 422）；失败抛归一化错误 */
  async updateConfig(partial: Partial<PhysioConfig>): Promise<PhysioConfig> {
    try {
      return await request<PhysioConfig>({
        url: '/api/physio/config',
        method: 'put',
        data: partial,
      });
    } catch (err) {
      throw normalizeError(err);
    }
  },

  /** 一键清除生理基线（含 base_hr 与设备指纹）；失败抛归一化错误 */
  async clear(): Promise<PhysioClearResult> {
    try {
      return await request<PhysioClearResult>({ url: '/api/physio/clear', method: 'post' });
    } catch (err) {
      throw normalizeError(err);
    }
  },
};
