import { refreshConnectionStatus } from "../services/connectionService";
import { getStoredConnectionStatus } from "../storage/extensionStorage";
import type { ExtensionResponse } from "../types/messages";
import { isExtensionMessage } from "../utils/messages";

chrome.runtime.onInstalled.addListener(() => {
  void refreshConnectionStatus();
});

chrome.runtime.onStartup.addListener(() => {
  void refreshConnectionStatus();
});

chrome.runtime.onMessage.addListener((message: unknown, _sender, sendResponse) => {
  if (!isExtensionMessage(message)) {
    sendResponse({ ok: false, error: "Invalid extension message" } satisfies ExtensionResponse);
    return false;
  }

  if (message.type === "PING") {
    sendResponse({ ok: true, type: "PONG" } satisfies ExtensionResponse);
    return false;
  }

  if (message.type === "CONTENT_SCRIPT_READY") {
    sendResponse({ ok: true, type: "PONG" } satisfies ExtensionResponse);
    return false;
  }

  if (message.type === "GET_CONNECTION_STATUS" || message.type === "SUBSCRIBE_CONNECTION_STATUS") {
    void refreshConnectionStatus()
      .catch(() => getStoredConnectionStatus())
      .then((status) => {
        sendResponse({ ok: true, type: "CONNECTION_STATUS", status } satisfies ExtensionResponse);
      });
    return true;
  }

  sendResponse({ ok: false, error: "Unsupported message type" } satisfies ExtensionResponse);
  return false;
});
