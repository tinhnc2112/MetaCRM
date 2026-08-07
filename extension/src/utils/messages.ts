import type { ExtensionMessage, ExtensionResponse } from "../types/messages";

const messageTypes = new Set([
  "PING",
  "GET_CONNECTION_STATUS",
  "CONNECT_BACKEND",
  "DISCONNECT_BACKEND",
  "CONTENT_SCRIPT_READY",
]);

const sources = new Set(["content", "popup", "sidepanel", "background"]);

export function isExtensionMessage(value: unknown): value is ExtensionMessage {
  if (!value || typeof value !== "object") {
    return false;
  }

  const candidate = value as Record<string, unknown>;
  return typeof candidate.type === "string" && messageTypes.has(candidate.type) && typeof candidate.source === "string" && sources.has(candidate.source);
}

export function sendRuntimeMessage(message: ExtensionMessage): Promise<ExtensionResponse> {
  return chrome.runtime.sendMessage(message) as Promise<ExtensionResponse>;
}
