import type { ConnectionState, ConnectionSnapshot } from "../types/status";

export function getConnectionLabel(status: ConnectionState): string {
  if (status === "CONNECTED") {
    return "Connected";
  }

  if (status === "CONNECTING") {
    return "Connecting";
  }

  if (status === "ERROR") {
    return "Error";
  }

  return "Disconnected";
}

export function getConnectionClass(status: ConnectionState): string {
  return status.toLowerCase();
}

export function isConnectionSnapshot(value: unknown): value is ConnectionSnapshot {
  if (!value || typeof value !== "object") {
    return false;
  }

  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.backend === "string" &&
    typeof candidate.websocket === "string" &&
    typeof candidate.connection === "string"
  );
}
