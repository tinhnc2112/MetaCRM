import { sendRuntimeMessage } from "../utils/messages";
import "../popup/styles.css";

const statusDot = document.querySelector<HTMLSpanElement>("#status-dot");
const statusText = document.querySelector<HTMLSpanElement>("#status-text");

function renderStatus(status: "CONNECTED" | "DISCONNECTED"): void {
  statusText?.replaceChildren(status === "CONNECTED" ? "Connected" : "Disconnected");
  statusDot?.classList.toggle("connected", status === "CONNECTED");
  statusDot?.classList.toggle("disconnected", status === "DISCONNECTED");
}

async function loadStatus(): Promise<void> {
  const response = await sendRuntimeMessage({
    type: "GET_CONNECTION_STATUS",
    source: "popup"
  });

  if (response.ok && response.type === "CONNECTION_STATUS") {
    renderStatus(response.status);
  } else {
    renderStatus("DISCONNECTED");
  }
}

void sendRuntimeMessage({ type: "PING", source: "popup" });
void loadStatus();
