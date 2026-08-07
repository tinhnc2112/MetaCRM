import { extensionConfig } from "../utils/config";

export type BackendHealthResponse = {
  status: "ok";
  service: "metacrm-api";
};

export async function checkBackendHealth(): Promise<BackendHealthResponse> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 4000);

  try {
    const response = await fetch(`${extensionConfig.backendUrl}/api/v1/system/health`, {
      method: "GET",
      signal: controller.signal
    });

    if (!response.ok) {
      throw new Error(`Backend health check failed with status ${response.status}`);
    }

    const payload = (await response.json()) as BackendHealthResponse;
    if (payload.status !== "ok" || payload.service !== "metacrm-api") {
      throw new Error("Unexpected backend health payload");
    }

    return payload;
  } finally {
    clearTimeout(timeoutId);
  }
}
