import { contextBridge, ipcRenderer } from "electron";

const electronBridge = {
  platform: process.platform,
  getAppVersion: () => ipcRenderer.invoke("app:get-version") as Promise<string>,
  onDeepLink: (callback: (target: string) => void) =>
    ipcRenderer.on("deep-link", (_event, target: string) => callback(target))
};

contextBridge.exposeInMainWorld("metacrm", electronBridge);

export type ElectronBridge = typeof electronBridge;
