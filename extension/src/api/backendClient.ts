import { extensionConfig } from "../utils/config";

export type BackendHealthResponse = {
  status: "ok";
  service: "metacrm-api";
};

export type FacebookPage = {
  id: string;
  page_id: string;
  name: string;
  username: string | null;
  picture_url: string | null;
  is_active: boolean;
};

export type FacebookPageListResponse = {
  items: FacebookPage[];
};

export type CurrentFacebookPageResponse = {
  item: FacebookPage | null;
};

function authHeaders(accessToken?: string): HeadersInit {
  return accessToken ? { Authorization: `Bearer ${accessToken}` } : {};
}

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

export async function getFacebookPages(accessToken?: string): Promise<FacebookPageListResponse> {
  const response = await fetch(`${extensionConfig.backendUrl}/api/v1/facebook/pages`, {
    method: "GET",
    headers: authHeaders(accessToken)
  });

  if (!response.ok) {
    throw new Error(`Facebook pages request failed with status ${response.status}`);
  }

  return (await response.json()) as FacebookPageListResponse;
}

export async function getCurrentFacebookPage(accessToken?: string): Promise<CurrentFacebookPageResponse> {
  const response = await fetch(`${extensionConfig.backendUrl}/api/v1/facebook/pages/current`, {
    method: "GET",
    headers: authHeaders(accessToken)
  });

  if (!response.ok) {
    throw new Error(`Current Facebook page request failed with status ${response.status}`);
  }

  return (await response.json()) as CurrentFacebookPageResponse;
}

export async function selectFacebookPage(pageId: string, accessToken?: string): Promise<CurrentFacebookPageResponse> {
  const response = await fetch(`${extensionConfig.backendUrl}/api/v1/facebook/pages/${encodeURIComponent(pageId)}/select`, {
    method: "POST",
    headers: authHeaders(accessToken)
  });

  if (!response.ok) {
    throw new Error(`Facebook page selection failed with status ${response.status}`);
  }

  return (await response.json()) as CurrentFacebookPageResponse;
}
