import { checkBackendHealth } from "../api/backendClient";
import { setStoredConnectionSnapshot } from "../storage/extensionStorage";
import type { ConnectionSnapshot, ConnectionState } from "../types/status";
import { MetaCrmWebSocketClient } from "../websocket/websocketClient";

const defaultSnapshot: ConnectionSnapshot = {
  backend: "DISCONNECTED",
  websocket: "DISCONNECTED",
  connection: "DISCONNECTED"
};

type ConnectionServiceOptions = {
  onChange?: (snapshot: ConnectionSnapshot) => void;
};

export class ConnectionService {
  private snapshot: ConnectionSnapshot = defaultSnapshot;
  private readonly socket: MetaCrmWebSocketClient;

  constructor(private readonly options: ConnectionServiceOptions = {}) {
    this.socket = new MetaCrmWebSocketClient({
      onOpen: () => {
        this.updateSnapshot({
          backend: "CONNECTED",
          websocket: "CONNECTED"
        });

        try {
          this.socket.send({ type: "ping" });
        } catch {
          // The socket may close immediately if the backend is unavailable.
        }
      },
      onClose: () => {
        this.updateSnapshot({
          websocket: this.snapshot.websocket === "ERROR" ? "ERROR" : "DISCONNECTED"
        });
      },
      onError: () => {
        this.updateSnapshot({
          websocket: "ERROR"
        });
      },
      onStatusChange: (status) => {
        if (status === "CONNECTING") {
          this.updateSnapshot({
            websocket: "CONNECTING"
          });
          return;
        }

        if (status === "CONNECTED") {
          this.updateSnapshot({
            websocket: "CONNECTED"
          });
          return;
        }

        if (status === "DISCONNECTED") {
          this.updateSnapshot({
            websocket: "DISCONNECTED"
          });
          return;
        }

        this.updateSnapshot({
          websocket: "ERROR"
        });
      },
      onReconnectAttempt: (attempt, delayMs) => {
        this.updateSnapshot({
          websocket: "CONNECTING"
        });
        void attempt;
        void delayMs;
      }
    });

    this.socket.onMessage((message) => {
      if (typeof message === "object" && message !== null) {
        const payload = message as Record<string, unknown>;
        if (payload.type === "connection") {
          this.updateSnapshot({
            backend: "CONNECTED",
            websocket: "CONNECTED"
          });
        }
      }
    });
  }

  async getSnapshot(): Promise<ConnectionSnapshot> {
    return this.snapshot;
  }

  async refreshBackendHealth(): Promise<ConnectionSnapshot> {
    try {
      await checkBackendHealth();
      return await this.updateSnapshot({ backend: "CONNECTED" });
    } catch {
      return await this.updateSnapshot({
        backend: "DISCONNECTED",
        websocket: "DISCONNECTED"
      });
    }
  }

  async connectBackend(): Promise<ConnectionSnapshot> {
    const snapshot = await this.refreshBackendHealth();
    if (snapshot.backend === "CONNECTED") {
      this.socket.connect();
      return this.snapshot;
    }

    this.socket.disconnect();
    return this.snapshot;
  }

  async disconnectBackend(): Promise<ConnectionSnapshot> {
    this.socket.disconnect();
    return this.updateSnapshot({
      backend: "DISCONNECTED",
      websocket: "DISCONNECTED"
    });
  }

  private deriveConnectionState(snapshot: ConnectionSnapshot): ConnectionState {
    if (snapshot.websocket === "ERROR") {
      return "ERROR";
    }

    if (snapshot.websocket === "CONNECTING") {
      return "CONNECTING";
    }

    if (snapshot.backend !== "CONNECTED") {
      return "DISCONNECTED";
    }

    if (snapshot.websocket === "CONNECTED") {
      return "CONNECTED";
    }

    return "DISCONNECTED";
  }

  private async updateSnapshot(partial: Partial<ConnectionSnapshot>): Promise<ConnectionSnapshot> {
    this.snapshot = {
      ...this.snapshot,
      ...partial
    };
    this.snapshot.connection = this.deriveConnectionState(this.snapshot);
    await setStoredConnectionSnapshot(this.snapshot);
    this.options.onChange?.(this.snapshot);
    return this.snapshot;
  }
}
