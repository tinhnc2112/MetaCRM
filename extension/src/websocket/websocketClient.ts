import { extensionConfig } from "../utils/config";
import type { ConnectionState } from "../types/status";

export type WebSocketMessage = unknown;

export type WebSocketClientOptions = {
  maxReconnectAttempts?: number;
  onOpen?: () => void;
  onClose?: () => void;
  onError?: () => void;
  onStatusChange?: (status: ConnectionState) => void;
  onReconnectAttempt?: (attempt: number, delayMs: number) => void;
};

type MessageHandler = (message: WebSocketMessage) => void;

export class MetaCrmWebSocketClient {
  private socket: WebSocket | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectAttempts = 0;
  private manuallyDisconnected = false;
  private status: ConnectionState = "DISCONNECTED";
  private readonly messageHandlers: MessageHandler[] = [];
  private readonly maxReconnectAttempts: number;

  constructor(private readonly options: WebSocketClientOptions = {}) {
    this.maxReconnectAttempts = options.maxReconnectAttempts ?? 5;
  }

  connect(): void {
    this.manuallyDisconnected = false;
    this.reconnectAttempts = 0;
    this.clearReconnectTimer();
    this.openSocket();
  }

  disconnect(): void {
    this.manuallyDisconnected = true;
    this.reconnectAttempts = 0;
    this.clearReconnectTimer();

    if (this.socket) {
      this.socket.close();
    }

    this.socket = null;
    this.setStatus("DISCONNECTED");
  }

  send(message: string | Record<string, unknown>): void {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
      throw new Error("WebSocket is not connected");
    }

    this.socket.send(typeof message === "string" ? message : JSON.stringify(message));
  }

  onMessage(handler: MessageHandler): () => void {
    this.messageHandlers.push(handler);

    return () => {
      const index = this.messageHandlers.indexOf(handler);
      if (index >= 0) {
        this.messageHandlers.splice(index, 1);
      }
    };
  }

  private openSocket(): void {
    if (this.socket && (this.socket.readyState === WebSocket.OPEN || this.socket.readyState === WebSocket.CONNECTING)) {
      return;
    }

    const url = new URL("/api/v1/ws", extensionConfig.backendUrl);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";

    this.setStatus("CONNECTING");
    const socket = new WebSocket(url.toString());
    this.socket = socket;

    socket.addEventListener("open", () => {
      this.reconnectAttempts = 0;
      this.setStatus("CONNECTED");
      this.options.onOpen?.();
    });

    socket.addEventListener("message", (event) => {
      const raw = event.data;

      if (typeof raw === "string") {
        try {
          this.dispatchMessage(JSON.parse(raw) as WebSocketMessage);
          return;
        } catch {
          this.dispatchMessage(raw);
          return;
        }
      }

      this.dispatchMessage(raw as WebSocketMessage);
    });

    socket.addEventListener("close", () => {
      this.socket = null;
      this.options.onClose?.();

      if (this.manuallyDisconnected) {
        this.setStatus("DISCONNECTED");
        return;
      }

      if (this.reconnectAttempts >= this.maxReconnectAttempts) {
        this.setStatus("ERROR");
        return;
      }

      this.scheduleReconnect();
    });

    socket.addEventListener("error", () => {
      this.options.onError?.();

      if (this.manuallyDisconnected) {
        this.setStatus("DISCONNECTED");
        return;
      }

      this.setStatus("ERROR");

      if (this.reconnectAttempts < this.maxReconnectAttempts) {
        this.scheduleReconnect();
      }
    });
  }

  private scheduleReconnect(): void {
    if (this.manuallyDisconnected) {
      return;
    }

    this.reconnectAttempts += 1;
    const delayMs = Math.min(1000 * 2 ** (this.reconnectAttempts - 1), 16000);
    this.setStatus("CONNECTING");
    this.options.onReconnectAttempt?.(this.reconnectAttempts, delayMs);

    this.clearReconnectTimer();
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.openSocket();
    }, delayMs);
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private dispatchMessage(message: WebSocketMessage): void {
    for (const handler of this.messageHandlers) {
      handler(message);
    }
  }

  private setStatus(status: ConnectionState): void {
    if (this.status === status) {
      return;
    }

    this.status = status;
    this.options.onStatusChange?.(status);
  }
}
