import { apiClient } from "./apiClient";
import type {
  ConversationListResponse,
  MarkConversationReadResponse,
  MessageListResponse,
  Message,
  SendMessageRequest
} from "../types/messenger";

export async function listConversations(pageId?: string): Promise<ConversationListResponse> {
  const response = await apiClient.get<ConversationListResponse>("/api/v1/facebook/conversations", {
    params: pageId ? { page_id: pageId } : undefined
  });
  return response.data;
}

export async function listMessages(
  conversationId: string,
  page?: number,
  pageSize?: number,
  oldestFirst?: boolean
): Promise<MessageListResponse> {
  const response = await apiClient.get<MessageListResponse>(
    `/api/v1/facebook/conversations/${encodeURIComponent(conversationId)}/messages`,
    {
      params: {
        page,
        page_size: pageSize,
        oldest_first: oldestFirst
      }
    }
  );
  return response.data;
}

export async function markConversationRead(conversationId: string): Promise<MarkConversationReadResponse> {
  const response = await apiClient.post<MarkConversationReadResponse>(
    `/api/v1/facebook/conversations/${encodeURIComponent(conversationId)}/read`
  );
  return response.data;
}

export async function sendMessage(
  conversationId: string,
  text: string
): Promise<Message> {
  const payload: SendMessageRequest = { text };
  const response = await apiClient.post<Message>(
    `/api/v1/facebook/conversations/${encodeURIComponent(conversationId)}/messages`,
    payload
  );
  return response.data;
}
