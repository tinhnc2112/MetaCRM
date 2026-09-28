import type { ConnectionSnapshot } from "../types/status";

export function getConnectionLabel(status: ConnectionSnapshot["backend"]): string {
  return status === "REACHABLE" ? "Reachable" : "Unavailable";
}

export function getConnectionClass(status: ConnectionSnapshot["backend"]): string {
  return status === "REACHABLE" ? "connected" : "disconnected";
}

export function isConnectionSnapshot(value: unknown): value is ConnectionSnapshot {
  return value !== null && typeof value === "object" &&
    ((value as Record<string, unknown>).backend === "REACHABLE" ||
      (value as Record<string, unknown>).backend === "UNAVAILABLE");
}
