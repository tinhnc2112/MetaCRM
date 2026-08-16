export type PaginationMeta = {
  total: number;
  page: number;
  page_size: number;
  has_next: boolean;
  has_prev: boolean;
};

export type Conversation = {
  id: string;
  page_id: string;
  psid: string;
  customer_name: string | null;
  customer_avatar_url: string | null;
  last_message_at: string | null;
  last_message_preview: string | null;
  unread_count: number;
  created_at: string;
  updated_at: string;
};

export type ConversationListResponse = {
  items: Conversation[];
  meta: PaginationMeta;
};

export type Message = {
  id: string;
  conversation_id: string;
  sender_psid: string | null;
  recipient_page_id: string;
  mid: string;
  event_type: string;
  is_from_page: boolean;
  text: string | null;
  attachments: unknown[] | null;
  postback_payload: string | null;
  fb_timestamp_ms: number | null;
  sent_at: string | null;
  created_at: string;
};

export type MessageListResponse = {
  items: Message[];
  meta: PaginationMeta;
};

export type MarkConversationReadResponse = {
  conversation_id: string;
  last_read_at: string | null;
  unread_count: number;
  already_read: boolean;
};

export type SendMessageRequest = {
  text: string;
};
