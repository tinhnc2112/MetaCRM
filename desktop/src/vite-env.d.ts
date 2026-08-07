/// <reference types="vite/client" />

declare global {
  interface Window {
    metacrm?: {
      platform: string;
      getAppVersion: () => Promise<string>;
    };
  }
}

export {};
