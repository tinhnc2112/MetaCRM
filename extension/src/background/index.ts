import { ConnectionService } from "../services/connectionService";
import type { ExtensionResponse } from "../types/messages";
import { isExtensionMessage } from "../utils/messages";

const connectionService = new ConnectionService({
  onChange: (snapshot) => {
    void chrome.runtime.sendMessage({
      ok: true,
      type: "CONNECTION_STATUS",
      source: "background",
      connection: snapshot
    } satisfies ExtensionResponse).catch(() => undefined);
  }
});

chrome.runtime.onInstalled.addListener(() => {
  void connectionService.connectBackend();
});

chrome.runtime.onStartup.addListener(() => {
  void connectionService.connectBackend();
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

  if (message.type === "GET_CONNECTION_STATUS") {
    void connectionService.refreshBackendHealth().then((snapshot) => {
      sendResponse({ ok: true, type: "CONNECTION_STATUS", source: "background", connection: snapshot } satisfies ExtensionResponse);
    });
    return true;
  }

  if (message.type === "CONNECT_BACKEND") {
    void connectionService.connectBackend().then((snapshot) => {
      sendResponse({ ok: true, type: "CONNECTION_STATUS", source: "background", connection: snapshot } satisfies ExtensionResponse);
    });
    return true;
  }

  if (message.type === "DISCONNECT_BACKEND") {
    void connectionService.disconnectBackend().then((snapshot) => {
      sendResponse({ ok: true, type: "CONNECTION_STATUS", source: "background", connection: snapshot } satisfies ExtensionResponse);
    });
    return true;
  }

  sendResponse({ ok: false, error: "Unsupported message type" } satisfies ExtensionResponse);
  return false;
});
