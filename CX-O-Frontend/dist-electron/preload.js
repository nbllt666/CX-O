import { contextBridge, ipcRenderer } from "electron";
contextBridge.exposeInMainWorld("electronAPI", {
  // Store
  storeLoad: (name) => ipcRenderer.invoke("store:load", name),
  storeSave: (name, data) => ipcRenderer.invoke("store:save", name, data),
  // Window control
  openPetWindow: () => ipcRenderer.invoke("window:open-pet"),
  closePetWindow: () => ipcRenderer.invoke("window:close-pet"),
  togglePetWindow: () => ipcRenderer.invoke("window:toggle-pet"),
  moveWindow: (x, y) => ipcRenderer.invoke("window:move", x, y),
  setIgnoreMouseEvents: (ignore) => ipcRenderer.invoke("window:set-ignore-mouse-events", ignore),
  // Config
  getBackendUrl: () => ipcRenderer.invoke("config:get-backend-url"),
  setBackendUrl: (url) => ipcRenderer.invoke("config:set-backend-url", url)
});
