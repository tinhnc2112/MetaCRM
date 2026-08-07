import { sendRuntimeMessage } from "../utils/messages";

void sendRuntimeMessage({
  type: "CONTENT_SCRIPT_READY",
  source: "content",
  location: window.location.origin
});
