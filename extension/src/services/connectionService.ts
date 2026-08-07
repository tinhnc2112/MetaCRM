import { checkBackendConnection } from "../api/backendClient";
import { setStoredConnectionStatus } from "../storage/extensionStorage";
import type { ConnectionStatus } from "../types/status";

export async function refreshConnectionStatus(): Promise<ConnectionStatus> {
  const isConnected = await checkBackendConnection();
  const status: ConnectionStatus = isConnected ? "CONNECTED" : "DISCONNECTED";
  await setStoredConnectionStatus(status);
  return status;
}
