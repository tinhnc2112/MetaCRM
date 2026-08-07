import type { ConnectionStatus } from "./status";

export type MessageSource = "content" | "popup" | "sidepanel" | "background";

export type PingMessage = {
  type: "PING";
  source: MessageSource;
};

export type GetConnectionStatusMessage = {
  type: "GET_CONNECTION_STATUS";
  source: MessageSource;
};

export type ContentScriptReadyMessage = {
  type: "CONTENT_SCRIPT_READY";
  source: "content";
  location: string;
};

export type SubscribeConnectionStatusMessage = {
  type: "SUBSCRIBE_CONNECTION_STATUS";
  source: "popup" | "sidepanel";
};

export type ExtensionMessage =
  | PingMessage
  | GetConnectionStatusMessage
  | ContentScriptReadyMessage
  | SubscribeConnectionStatusMessage;

export type PongResponse = {
  ok: true;
  type: "PONG";
};

export type ConnectionStatusResponse = {
  ok: true;
  type: "CONNECTION_STATUS";
  status: ConnectionStatus;
};

export type ErrorResponse = {
  ok: false;
  error: string;
};

export type ExtensionResponse = PongResponse | ConnectionStatusResponse | ErrorResponse;
