import type { PaginationMeta } from "./messenger";

export type CustomerProfileConversation = {
  uuid: string;
  customer_psid: string;
  customer_name: string | null;
  customer_avatar_url: string | null;
  last_message_at: string | null;
  unread_count: number;
};

export type CustomerTagSummary = {
  id: number;
  name: string;
  slug: string;
  description: string | null;
};

export type CustomerTag = CustomerTagSummary & {
  customer_count: number;
};

export type CustomerTimelineItem = {
  type: "message" | "note" | "tag";
  timestamp: string;
  preview?: string | null;
  content?: string | null;
  is_from_page?: boolean | null;
  action?: "added" | "removed" | null;
  tag_name?: string | null;
  tag_slug?: string | null;
};

export type CustomerNote = {
  id: string;
  content: string;
  created_at: string;
  updated_at: string;
};

export type CustomerProfileResponse = {
  conversation: CustomerProfileConversation;
  tags: CustomerTagSummary[];
  timeline: CustomerTimelineItem[];
  notes: CustomerNote[];
};

export type CustomerDuplicateCandidate = {
  primary_customer: CustomerProfileConversation;
  duplicate_customer: CustomerProfileConversation;
  confidence: number;
  reason: string;
  matching_fields: string[];
  matching_signals: string[];
};

export type CustomerDuplicateListResponse = {
  items: CustomerDuplicateCandidate[];
  meta: PaginationMeta;
};

export type CustomerMergeRequest = {
  secondary_customer_id: string;
};

export type CustomerMergeResponse = {
  merge_id: number;
  primary_customer: CustomerProfileConversation;
  secondary_customer: CustomerProfileConversation;
  merged_by_user_id: number | null;
  merged_at: string;
  duplicate_confidence: number;
  duplicate_reason: string;
  matching_fields: string[];
  matching_signals: string[];
};

export type CustomerTagAssignmentResponse = {
  customer_id: string;
  tag: CustomerTagSummary;
  attached: boolean;
};

export type CustomerTagListResponse = {
  items: CustomerTag[];
};

export type CustomerTagCustomersResponse = {
  items: CustomerProfileConversation[];
  meta: PaginationMeta;
};

export type CustomerNoteSaveRequest = {
  noteId: string | null;
  content: string;
};

export type CustomerNoteDeleteResponse = {
  deleted: boolean;
  note_id: string;
};
