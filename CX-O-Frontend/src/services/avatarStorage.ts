import { api } from '../api/client';

export interface AvatarRecord {
  id: string;
  name: string;
  type: 'live2d' | 'vrm';
  data?: Blob;
  thumbnail?: string;
  createdAt: number;
  size: number;
  metadata?: {
    modelJsonPath?: string;
    vrmMeta?: {
      name?: string;
      author?: string;
      version?: string;
    };
  };
}

interface BackendAvatar {
  id: string;
  name: string;
  type: string;
  size: number;
  created_at: string;
  updated_at?: string;
  metadata?: Record<string, unknown>;
}

function backendToRecord(backend: BackendAvatar): AvatarRecord {
  return {
    id: backend.id,
    name: backend.name,
    type: backend.type as 'live2d' | 'vrm',
    size: backend.size,
    createdAt: new Date(backend.created_at).getTime(),
    metadata: backend.metadata as AvatarRecord['metadata'],
  };
}

export const saveAvatar = async (
  avatar: Omit<AvatarRecord, 'id' | 'createdAt'> & { file: File }
): Promise<AvatarRecord> => {
  const response = await api.uploadAvatar(
    avatar.file,
    avatar.type,
    avatar.name
  );

  return {
    id: response.avatar.id,
    name: response.avatar.name,
    type: response.avatar.type as 'live2d' | 'vrm',
    size: response.avatar.size,
    createdAt: new Date(response.avatar.created_at).getTime(),
  };
};

export const getAvatar = async (id: string): Promise<AvatarRecord | null> => {
  try {
    const list = await api.listAvatars();
    const backendAvatar = list.avatars.find((a) => a.id === id);
    if (!backendAvatar) return null;

    const record = backendToRecord(backendAvatar);

    // 下载文件内容
    const blob = await api.downloadAvatarFile(id, backendAvatar.type);
    record.data = blob;

    return record;
  } catch (error) {
    console.error('Failed to get avatar:', error);
    return null;
  }
};

export const listAvatars = async (): Promise<AvatarRecord[]> => {
  try {
    const response = await api.listAvatars();
    return response.avatars.map(backendToRecord);
  } catch (error) {
    console.error('Failed to list avatars:', error);
    return [];
  }
};

export const deleteAvatar = async (id: string): Promise<void> => {
  try {
    const list = await api.listAvatars();
    const backendAvatar = list.avatars.find((a) => a.id === id);
    if (!backendAvatar) {
      throw new Error('Avatar not found');
    }
    await api.deleteAvatar(id, backendAvatar.type);
  } catch (error) {
    console.error('Failed to delete avatar:', error);
    throw error;
  }
};

export const updateAvatar = async (
  id: string,
  updates: Partial<Pick<AvatarRecord, 'name' | 'metadata'>>
): Promise<void> => {
  try {
    const list = await api.listAvatars();
    const backendAvatar = list.avatars.find((a) => a.id === id);
    if (!backendAvatar) {
      throw new Error('Avatar not found');
    }
    await api.updateAvatar(id, backendAvatar.type, {
      name: updates.name,
      metadata: updates.metadata as Record<string, unknown>,
    });
  } catch (error) {
    console.error('Failed to update avatar:', error);
    throw error;
  }
};

export const generateThumbnail = async (
  _blob: Blob,
  _type: 'live2d' | 'vrm'
): Promise<string | undefined> => {
  return undefined;
};

export const createBlobUrl = (blob: Blob): string => {
  return URL.createObjectURL(blob);
};

export const revokeBlobUrl = (url: string): void => {
  if (url.startsWith('blob:')) {
    URL.revokeObjectURL(url);
  }
};
