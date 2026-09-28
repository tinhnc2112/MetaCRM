import type { ConnectionSnapshot } from "./status";

export type MessageSource = "content" | "popup" | "sidepanel" | "background";

export type PingMessage = {
  type: "PING";
  source: MessageSource;
};

export type GetConnectionStatusMessage = {
  type: "GET_CONNECTION_STATUS";
  source: "popup" | "sidepanel";
};

export type RefreshBackendHealthMessage = {
  type: "REFRESH_BACKEND_HEALTH";
  source: "popup" | "sidepanel";
};

export type ContentScriptReadyMessage = {
  type: "CONTENT_SCRIPT_READY";
  source: "content";
  location: string;
};

export type ExtensionMessage =
  | PingMessage
  | GetConnectionStatusMessage
  | RefreshBackendHealthMessage
  | ContentScriptReadyMessage;

export type PongResponse = {
  ok: true;
  type: "PONG";
};

export type ConnectionStatusResponse = {
  ok: true;
  type: "CONNECTION_STATUS";
  source: "background";
  connection: ConnectionSnapshot;
};

export type ErrorResponse = {
  ok: false;
  error: string;
};

export type ExtensionResponse = PongResponse | ConnectionStatusResponse | ErrorResponse;
