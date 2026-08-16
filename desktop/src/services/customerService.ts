import { apiClient } from "./apiClient";
import type {
  CustomerNoteDeleteResponse,
  CustomerProfileResponse,
} from "../types/customer";

export async function getCustomerProfile(conversationId: string): Promise<CustomerProfileResponse> {
  const response = await apiClient.get<CustomerProfileResponse>(
    `/api/v1/facebook/customers/${encodeURIComponent(conversationId)}`
  );
  return response.data;
}

export async function createCustomerNote(
  conversationId: string,
  content: string
): Promise<CustomerProfileResponse["notes"][number]> {
  const response = await apiClient.post<CustomerProfileResponse["notes"][number]>(
    `/api/v1/facebook/customers/${encodeURIComponent(conversationId)}/notes`,
    { content }
  );
  return response.data;
}

export async function updateCustomerNote(
  noteId: string,
  content: string
): Promise<CustomerProfileResponse["notes"][number]> {
  const response = await apiClient.patch<CustomerProfileResponse["notes"][number]>(
    `/api/v1/facebook/customers/notes/${encodeURIComponent(noteId)}`,
    { content }
  );
  return response.data;
}

export async function deleteCustomerNote(noteId: string): Promise<CustomerNoteDeleteResponse> {
  const response = await apiClient.delete<CustomerNoteDeleteResponse>(
    `/api/v1/facebook/customers/notes/${encodeURIComponent(noteId)}`
  );
  return response.data;
}
