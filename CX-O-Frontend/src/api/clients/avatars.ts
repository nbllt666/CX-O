/**
 * ApiClient mixin: Avatars domain operations.
 * Extracted from client.ts as part of M16 split.
 */
import type { _ApiClientBase } from './_common';
import { getApiBaseUrl } from './_common';

// Declaration merging: let TypeScript know _AvatarsClientMixin can access _ApiClientBase's methods
export interface _AvatarsClientMixin extends _ApiClientBase {}

export class _AvatarsClientMixin {
  async listAvatars(type?: 'vrm' | 'live2d'): Promise<{ avatars: Array<{
    id: string;
    name: string;
    type: string;
    size: number;
    created_at: string;
    updated_at?: string;
    metadata?: Record<string, unknown>;
  }>; total: number }> {
    return this.request({
      url: '/api/avatars',
      params: type ? { type } : undefined,
    });
  }

  async uploadAvatar(
    file: File,
    avatarType: 'vrm' | 'live2d',
    name?: string,
    onProgress?: (progress: number) => void
  ): Promise<{ status: string; avatar: {
    id: string;
    name: string;
    type: string;
    size: number;
    created_at: string;
  } }> {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('avatar_type', avatarType);
    if (name) formData.append('name', name);

    const axiosInstance = this.client;

    const response = await axiosInstance.post('/api/avatars/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: onProgress
        ? (progressEvent) => {
            const total = progressEvent.total || file.size;
            const progress = Math.round((progressEvent.loaded * 100) / total);
            onProgress(progress);
          }
        : undefined,
    });
    return response.data;
  }

  getAvatarFileUrl(avatarId: string, avatarType: string): string {
    return `${getApiBaseUrl()}/api/avatars/${avatarId}/file?avatar_type=${avatarType}`;
  }

  async downloadAvatarFile(avatarId: string, avatarType: string): Promise<Blob> {
    const axiosInstance = this.client;

    const response = await axiosInstance.get(`/api/avatars/${avatarId}/file`, {
      params: { avatar_type: avatarType },
      responseType: 'blob',
    });
    return response.data;
  }

  async getAvatar(avatarId: string, avatarType: string): Promise<{
    id: string;
    name: string;
    type: string;
    size: number;
    created_at: string;
    updated_at?: string;
    metadata?: Record<string, unknown>;
  }> {
    return this.request({
      url: `/api/avatars/${avatarId}`,
      params: { avatar_type: avatarType },
    });
  }

  async updateAvatar(
    avatarId: string,
    avatarType: string,
    updates: { name?: string; metadata?: Record<string, unknown> }
  ): Promise<{ status: string; avatar: unknown }> {
    return this.request({
      url: `/api/avatars/${avatarId}?avatar_type=${avatarType}`,
      method: 'put',
      data: updates,
    });
  }

  async deleteAvatar(avatarId: string, avatarType: string): Promise<{ status: string; message: string }> {
    return this.request({
      url: `/api/avatars/${avatarId}?avatar_type=${avatarType}`,
      method: 'delete',
    });
  }
}