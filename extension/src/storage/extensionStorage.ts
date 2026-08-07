import type { ConnectionStatus } from "../types/status";

const CONNECTION_STATUS_KEY = "connectionStatus";

export async function getStoredConnectionStatus(): Promise<ConnectionStatus> {
  const values = await chrome.storage.local.get(CONNECTION_STATUS_KEY);
  return values[CONNECTION_STATUS_KEY] === "CONNECTED" ? "CONNECTED" : "DISCONNECTED";
}

export async function setStoredConnectionStatus(status: ConnectionStatus): Promise<void> {
  await chrome.storage.local.set({ [CONNECTION_STATUS_KEY]: status });
}
