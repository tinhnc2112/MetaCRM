import { checkBackendHealth } from "../api/backendClient";
import type { ConnectionSnapshot } from "../types/status";

type ConnectionServiceOptions = {
  onChange?: (snapshot: ConnectionSnapshot) => void;
};

/** The extension has no staff credentials or Page context: report public HTTP liveness only. */
export class ConnectionService {
  private snapshot: ConnectionSnapshot = { backend: "UNAVAILABLE" };

  constructor(private readonly options: ConnectionServiceOptions = {}) {}

  async refreshBackendHealth(): Promise<ConnectionSnapshot> {
    try {
      await checkBackendHealth();
      this.snapshot = { backend: "REACHABLE" };
    } catch {
      this.snapshot = { backend: "UNAVAILABLE" };
    }
    this.options.onChange?.(this.snapshot);
    return this.snapshot;
  }
}
