export type CustomerProfileConversation = {
  uuid: string;
  customer_psid: string;
  customer_name: string | null;
  customer_avatar_url: string | null;
  last_message_at: string | null;
  unread_count: number;
};

export type CustomerTimelineItem = {
  type: "message" | "note";
  timestamp: string;
  preview?: string | null;
  content?: string | null;
  is_from_page?: boolean | null;
};

export type CustomerNote = {
  id: string;
  content: string;
  created_at: string;
  updated_at: string;
};

export type CustomerProfileResponse = {
  conversation: CustomerProfileConversation;
  timeline: CustomerTimelineItem[];
  notes: CustomerNote[];
};

export type CustomerNoteSaveRequest = {
  noteId: string | null;
  content: string;
};

export type CustomerNoteDeleteResponse = {
  deleted: boolean;
  note_id: string;
};
