import { contextBridge, ipcRenderer } from "electron";

const electronBridge = {
  platform: process.platform,
  getAppVersion: () => ipcRenderer.invoke("app:get-version") as Promise<string>
};

contextBridge.exposeInMainWorld("metacrm", electronBridge);

export type ElectronBridge = typeof electronBridge;
