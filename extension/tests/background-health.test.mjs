import assert from "node:assert/strict";
import { test } from "node:test";

// Exercise the built MV3 service worker with only the public health API.
test("extension reports reachable/unavailable/recovered without opening a socket", async () => {
  let messageHandler;
  let startupHandler;
  const broadcasts = [];
  const requests = [];
  let available = true;

  globalThis.chrome = {
    runtime: {
      onInstalled: { addListener() {} },
      onStartup: { addListener(handler) { startupHandler = handler; } },
      onMessage: { addListener(handler) { messageHandler = handler; } },
      sendMessage(message) { broadcasts.push(message); return Promise.resolve(); }
    },
    get storage() { throw new Error("health status must not be persisted"); }
  };
  globalThis.WebSocket = class {
    constructor() { throw new Error("extension cannot authenticate WebSocket"); }
  };
  globalThis.fetch = async (url, options) => {
    requests.push({ url, options });
    if (!available) throw new Error("temporary outage");
    return { ok: true, json: async () => ({ status: "ok", service: "metacrm-api" }) };
  };

  await import(new URL("../dist/background.js", import.meta.url).href);
  assert.equal(typeof startupHandler, "function");
  assert.equal(typeof messageHandler, "function");

  const status = (type) => new Promise((resolve) => {
    const asynchronous = messageHandler({ type, source: "popup" }, {}, resolve);
    assert.equal(asynchronous, true);
  });

  startupHandler();
  assert.deepEqual((await status("GET_CONNECTION_STATUS")).connection, { backend: "REACHABLE" });
  available = false;
  assert.deepEqual((await status("REFRESH_BACKEND_HEALTH")).connection, { backend: "UNAVAILABLE" });
  available = true;
  assert.deepEqual((await status("REFRESH_BACKEND_HEALTH")).connection, { backend: "REACHABLE" });
  assert.ok(requests.every(({ url, options }) =>
    url === "http://127.0.0.1:8000/api/v1/system/health" && options.method === "GET"));
  assert.ok(broadcasts.every(({ connection }) => !Object.hasOwn(connection, "websocket")));
});
