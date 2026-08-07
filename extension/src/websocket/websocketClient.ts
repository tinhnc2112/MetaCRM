import { extensionConfig } from "../utils/config";

export type WebSocketClientOptions = {
  onOpen?: () => void;
  onClose?: () => void;
  onError?: () => void;
};

export class MetaCrmWebSocketClient {
  private socket: WebSocket | null = null;

  constructor(private readonly options: WebSocketClientOptions = {}) {}

  connect(path = "/ws"): void {
    if (this.socket && this.socket.readyState <= WebSocket.OPEN) {
      return;
    }

    const url = new URL(path, extensionConfig.backendUrl);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";

    this.socket = new WebSocket(url);
    this.socket.addEventListener("open", () => this.options.onOpen?.());
    this.socket.addEventListener("close", () => this.options.onClose?.());
    this.socket.addEventListener("error", () => this.options.onError?.());
  }

  disconnect(): void {
    this.socket?.close();
    this.socket = null;
  }
}
