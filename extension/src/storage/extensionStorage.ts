import type { ConnectionSnapshot } from "../types/status";

const CONNECTION_SNAPSHOT_KEY = "connectionSnapshot";

const defaultSnapshot: ConnectionSnapshot = {
  backend: "DISCONNECTED",
  websocket: "DISCONNECTED",
  connection: "DISCONNECTED"
};

export async function getStoredConnectionSnapshot(): Promise<ConnectionSnapshot> {
  const values = await chrome.storage.local.get(CONNECTION_SNAPSHOT_KEY);
  return (values[CONNECTION_SNAPSHOT_KEY] as ConnectionSnapshot | undefined) ?? defaultSnapshot;
}

export async function setStoredConnectionSnapshot(snapshot: ConnectionSnapshot): Promise<void> {
  await chrome.storage.local.set({ [CONNECTION_SNAPSHOT_KEY]: snapshot });
}
