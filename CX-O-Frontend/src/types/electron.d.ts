export {};

declare global {
  interface Window {
    electronAPI?: {
      storeLoad: (name: string) => Promise<string | null>;
      storeSave: (name: string, data: string) => Promise<void>;
      openPetWindow: () => Promise<void>;
      closePetWindow: () => Promise<void>;
      togglePetWindow: () => Promise<void>;
      moveWindow: (x: number, y: number) => Promise<void>;
      setIgnoreMouseEvents: (ignore: boolean) => Promise<void>;
      getBackendUrl: () => Promise<string | null>;
      setBackendUrl: (url: string) => Promise<void>;
    };
  }
}
