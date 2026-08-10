/**
 * avatars 域客户端：VRM / Live2D 头像资源管理。
 * 端点面对齐 CX-O-Frontend clients/avatars.ts。
 */
import { getApiBaseUrl, getHttpClient, request } from '../base';
import type { AvatarInfo } from '../types';

export const avatarsApi = {
  listAvatars(type?: 'vrm' | 'live2d'): Promise<{ avatars: AvatarInfo[]; total: number }> {
    return request<{ avatars: AvatarInfo[]; total: number }>({
      url: '/api/avatars',
      params: type ? { type } : undefined,
    });
  },

  /** 上传头像文件（multipart，带上传进度回调） */
  async uploadAvatar(
    file: File,
    avatarType: 'vrm' | 'live2d',
    name?: string,
    onProgress?: (progress: number) => void,
  ): Promise<{ status: string; avatar: AvatarInfo }> {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('avatar_type', avatarType);
    if (name) formData.append('name', name);

    const response = await getHttpClient().post<{ status: string; avatar: AvatarInfo }>(
      '/api/avatars/upload',
      formData,
      {
        headers: { 'Content-Type': 'multipart/form-data' },
        onUploadProgress: onProgress
          ? (progressEvent) => {
              const total = progressEvent.total || file.size;
              onProgress(Math.round((progressEvent.loaded * 100) / total));
            }
          : undefined,
      },
    );
    return response.data;
  },

  getAvatarFileUrl(avatarId: string, avatarType: string): string {
    return `${getApiBaseUrl()}/api/avatars/${encodeURIComponent(avatarId)}/file?avatar_type=${encodeURIComponent(avatarType)}`;
  },

  async downloadAvatarFile(avatarId: string, avatarType: string): Promise<Blob> {
    const response = await getHttpClient().get<Blob>(
      `/api/avatars/${encodeURIComponent(avatarId)}/file`,
      { params: { avatar_type: avatarType }, responseType: 'blob' },
    );
    return response.data;
  },

  getAvatar(avatarId: string, avatarType: string): Promise<AvatarInfo> {
    return request<AvatarInfo>({
      url: `/api/avatars/${encodeURIComponent(avatarId)}`,
      params: { avatar_type: avatarType },
    });
  },

  updateAvatar(
    avatarId: string,
    avatarType: string,
    updates: { name?: string; metadata?: Record<string, unknown> },
  ): Promise<{ status: string; avatar: unknown }> {
    return request<{ status: string; avatar: unknown }>({
      url: `/api/avatars/${encodeURIComponent(avatarId)}?avatar_type=${encodeURIComponent(avatarType)}`,
      method: 'put',
      data: updates,
    });
  },

  deleteAvatar(avatarId: string, avatarType: string): Promise<{ status: string; message: string }> {
    return request<{ status: string; message: string }>({
      url: `/api/avatars/${encodeURIComponent(avatarId)}?avatar_type=${encodeURIComponent(avatarType)}`,
      method: 'delete',
    });
  },
};
