import { getConnectionClass, getConnectionLabel, isConnectionSnapshot } from "../utils/connectionUi";
import { sendRuntimeMessage } from "../utils/messages";
import "../popup/styles.css";

const backendDot = document.querySelector<HTMLSpanElement>("#backend-dot");
const backendText = document.querySelector<HTMLSpanElement>("#backend-text");
const websocketDot = document.querySelector<HTMLSpanElement>("#websocket-dot");
const websocketText = document.querySelector<HTMLSpanElement>("#websocket-text");
const reconnectButton = document.querySelector<HTMLButtonElement>("#reconnect-button");

function renderConnection(snapshot: { backend: "CONNECTED" | "DISCONNECTED"; websocket: "CONNECTED" | "CONNECTING" | "DISCONNECTED" | "ERROR" }): void {
  backendText?.replaceChildren(getConnectionLabel(snapshot.backend));
  backendDot?.classList.remove("connected", "connecting", "disconnected", "error");
  backendDot?.classList.add(getConnectionClass(snapshot.backend));

  websocketText?.replaceChildren(getConnectionLabel(snapshot.websocket));
  websocketDot?.classList.remove("connected", "connecting", "disconnected", "error");
  websocketDot?.classList.add(getConnectionClass(snapshot.websocket));
}

async function loadStatus(): Promise<void> {
  const response = await sendRuntimeMessage({
    type: "GET_CONNECTION_STATUS",
    source: "popup"
  });

  if (response.ok && response.type === "CONNECTION_STATUS") {
    renderConnection(response.connection);
    return;
  }

  renderConnection({
    backend: "DISCONNECTED",
    websocket: "DISCONNECTED"
  });
}

async function reconnect(): Promise<void> {
  const response = await sendRuntimeMessage({
    type: "CONNECT_BACKEND",
    source: "popup"
  });

  if (response.ok && response.type === "CONNECTION_STATUS") {
    renderConnection(response.connection);
  }
}

chrome.runtime.onMessage.addListener((message: unknown) => {
  if (!message || typeof message !== "object") {
    return;
  }

  const candidate = message as {
    ok?: boolean;
    type?: string;
    connection?: unknown;
  };

  if (candidate.ok === true && candidate.type === "CONNECTION_STATUS" && isConnectionSnapshot(candidate.connection)) {
    renderConnection(candidate.connection);
  }
});

reconnectButton?.addEventListener("click", () => {
  void reconnect();
});

void loadStatus();
