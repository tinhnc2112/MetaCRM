import { sendRuntimeMessage } from "../utils/messages";
import "../sidepanel/styles.css";

const statusText = document.querySelector<HTMLElement>("#status-text");

function renderStatus(status: "CONNECTED" | "DISCONNECTED"): void {
  if (!statusText) {
    return;
  }

  statusText.textContent = status === "CONNECTED" ? "Connected" : "Disconnected";
  statusText.dataset.status = status;
}

async function loadStatus(): Promise<void> {
  const response = await sendRuntimeMessage({
    type: "GET_CONNECTION_STATUS",
    source: "sidepanel"
  });

  if (response.ok && response.type === "CONNECTION_STATUS") {
    renderStatus(response.status);
  } else {
    renderStatus("DISCONNECTED");
  }
}

void sendRuntimeMessage({ type: "PING", source: "sidepanel" });
void loadStatus();
