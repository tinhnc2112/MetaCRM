export type ConnectionState = "CONNECTED" | "CONNECTING" | "DISCONNECTED" | "ERROR";

export type BackendHealthState = "CONNECTED" | "DISCONNECTED";

export type ConnectionSnapshot = {
  backend: BackendHealthState;
  websocket: ConnectionState;
  connection: ConnectionState;
};
