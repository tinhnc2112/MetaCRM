import { getConnectionClass, getConnectionLabel, isConnectionSnapshot } from "../utils/connectionUi";
import { sendRuntimeMessage } from "../utils/messages";
import "../sidepanel/styles.css";

const backendDot = document.querySelector<HTMLSpanElement>("#backend-dot");
const backendText = document.querySelector<HTMLSpanElement>("#backend-text");
const refreshButton = document.querySelector<HTMLButtonElement>("#reconnect-button");

function renderConnection(snapshot: { backend: "REACHABLE" | "UNAVAILABLE" }): void {
  backendText?.replaceChildren(getConnectionLabel(snapshot.backend));
  backendDot?.classList.remove("connected", "connecting", "disconnected", "error");
  backendDot?.classList.add(getConnectionClass(snapshot.backend));
}

async function loadStatus(): Promise<void> {
  const response = await sendRuntimeMessage({
    type: "GET_CONNECTION_STATUS",
    source: "sidepanel"
  });

  if (response.ok && response.type === "CONNECTION_STATUS") {
    renderConnection(response.connection);
    return;
  }

  renderConnection({
    backend: "UNAVAILABLE"
  });
}

async function refresh(): Promise<void> {
  const response = await sendRuntimeMessage({
    type: "REFRESH_BACKEND_HEALTH",
    source: "sidepanel"
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

refreshButton?.addEventListener("click", () => {
  void refresh();
});

void loadStatus();
