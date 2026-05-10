export interface AvatarRecord {
  id: string;
  name: string;
  type: 'live2d' | 'vrm';
  data: Blob;
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

let db: IDBDatabase | null = null;

export const initDB = (): Promise<IDBDatabase> => {
  return new Promise((resolve, reject) => {
    if (db) {
      resolve(db);
      return;
    }

    const request = indexedDB.open('cxhms-avatars', 1);

    request.onerror = () => reject(new Error('Failed to open IndexedDB'));

    request.onsuccess = () => {
      db = request.result;
      resolve(db);
    };

    request.onupgradeneeded = (event) => {
      const database = (event.target as IDBOpenDBRequest).result;
      if (!database.objectStoreNames.contains('avatars')) {
        const store = database.createObjectStore('avatars', { keyPath: 'id' });
        store.createIndex('name', 'name', { unique: false });
        store.createIndex('type', 'type', { unique: false });
        store.createIndex('createdAt', 'createdAt', { unique: false });
      }
    };
  });
};

export const saveAvatar = async (avatar: AvatarRecord): Promise<void> => {
  const database = await initDB();
  return new Promise((resolve, reject) => {
    const transaction = database.transaction(['avatars'], 'readwrite');
    const store = transaction.objectStore('avatars');
    store.put(avatar);
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(new Error('Failed to save avatar'));
  });
};

export const getAvatar = async (id: string): Promise<AvatarRecord | null> => {
  const database = await initDB();
  return new Promise((resolve, reject) => {
    const transaction = database.transaction(['avatars'], 'readonly');
    const store = transaction.objectStore('avatars');
    const request = store.get(id);
    request.onsuccess = () => resolve(request.result || null);
    request.onerror = () => reject(new Error('Failed to get avatar'));
  });
};

export const listAvatars = async (): Promise<AvatarRecord[]> => {
  const database = await initDB();
  return new Promise((resolve, reject) => {
    const transaction = database.transaction(['avatars'], 'readonly');
    const store = transaction.objectStore('avatars');
    const request = store.getAll();
    request.onsuccess = () => resolve(request.result || []);
    request.onerror = () => reject(new Error('Failed to list avatars'));
  });
};

export const deleteAvatar = async (id: string): Promise<void> => {
  const database = await initDB();
  return new Promise((resolve, reject) => {
    const transaction = database.transaction(['avatars'], 'readwrite');
    const store = transaction.objectStore('avatars');
    store.delete(id);
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(new Error('Failed to delete avatar'));
  });
};

export const generateThumbnail = async (_blob: Blob, _type: 'live2d' | 'vrm'): Promise<string | undefined> => {
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
