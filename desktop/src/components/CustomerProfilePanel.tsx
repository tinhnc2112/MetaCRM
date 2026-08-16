import { DeleteOutlined, EditOutlined, FileTextOutlined, MessageOutlined, SaveOutlined } from "@ant-design/icons";
import { Avatar, Badge, Button, Empty, Input, List, Space, Spin, Tag, Typography } from "antd";
import { useEffect, useMemo, useState } from "react";

import type { CustomerProfileResponse, CustomerNoteSaveRequest } from "../types/customer";

type CustomerProfilePanelProps = {
  profile: CustomerProfileResponse | null;
  loading: boolean;
  error: boolean;
  savingNote: boolean;
  onSaveNote: (input: CustomerNoteSaveRequest) => Promise<void>;
  onDeleteNote: (noteId: string) => Promise<void>;
};

export function CustomerProfilePanel({
  profile,
  loading,
  error,
  savingNote,
  onSaveNote,
  onDeleteNote
}: CustomerProfilePanelProps) {
  const [noteId, setNoteId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  const conversation = profile?.conversation ?? null;
  const notes = profile?.notes ?? [];
  const timeline = profile?.timeline ?? [];

  useEffect(() => {
    setNoteId(null);
    setDraft("");
  }, [conversation?.uuid]);

  const headerName = useMemo(() => conversation?.customer_name ?? conversation?.customer_psid ?? "Customer", [conversation]);
  const initial = headerName.slice(0, 1).toUpperCase();

  const handleSave = async () => {
    const content = draft.trim();
    if (!content) {
      return;
    }
    await onSaveNote({ noteId, content });
    setNoteId(null);
    setDraft("");
  };

  if (!conversation && loading) {
    return (
      <section className="messenger-profile-panel">
        <div className="messenger-loading">
          <Spin />
        </div>
      </section>
    );
  }

  if (error) {
    return (
      <section className="messenger-profile-panel">
        <Empty description="Could not load customer profile" />
      </section>
    );
  }

  if (!conversation) {
    return (
      <section className="messenger-profile-panel">
        <Empty description="Select a conversation to view the customer profile" />
      </section>
    );
  }

  return (
    <section className="messenger-profile-panel">
      <header className="messenger-profile-header">
        <div className="messenger-profile-identity">
          {conversation.customer_avatar_url ? (
            <Avatar size={56} src={conversation.customer_avatar_url} />
          ) : (
            <Avatar size={56}>{initial}</Avatar>
          )}
          <div>
            <Typography.Title level={4}>{headerName}</Typography.Title>
            <Typography.Text type="secondary">{conversation.customer_psid}</Typography.Text>
          </div>
        </div>
        <Badge count={conversation.unread_count} overflowCount={99} />
      </header>

      <div className="messenger-profile-meta">
        <div>
          <span className="messenger-profile-label">Last interaction</span>
          <Typography.Text>{formatTimestamp(conversation.last_message_at)}</Typography.Text>
        </div>
        <div>
          <span className="messenger-profile-label">PSID</span>
          <Typography.Text copyable>{conversation.customer_psid}</Typography.Text>
        </div>
      </div>

      <section className="messenger-profile-section">
        <div className="messenger-profile-section-header">
          <Typography.Title level={5}>Internal Notes</Typography.Title>
        </div>
        <div className="messenger-note-editor">
          <Input.TextArea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Write an internal note..."
            autoSize={{ minRows: 4, maxRows: 8 }}
          />
          <Space className="messenger-note-editor-actions">
            <Button
              icon={<SaveOutlined />}
              type="primary"
              onClick={() => void handleSave()}
              loading={savingNote}
              disabled={!draft.trim()}
            >
              {noteId ? "Update note" : "Save note"}
            </Button>
            {noteId ? (
              <Button
                onClick={() => {
                  setNoteId(null);
                  setDraft("");
                }}
              >
                Cancel
              </Button>
            ) : null}
          </Space>
        </div>

        {notes.length === 0 ? (
          <Empty description="No internal notes yet" />
        ) : (
          <List
            dataSource={notes}
            renderItem={(note) => (
              <List.Item className="messenger-note-item">
                <div className="messenger-note-card">
                  <div className="messenger-note-content">{note.content}</div>
                  <div className="messenger-note-footer">
                    <Typography.Text type="secondary">{formatTimestamp(note.created_at)}</Typography.Text>
                    <Space size={8}>
                      <Button
                        icon={<EditOutlined />}
                        size="small"
                        onClick={() => {
                          setNoteId(note.id);
                          setDraft(note.content);
                        }}
                      >
                        Edit
                      </Button>
                      <Button
                        icon={<DeleteOutlined />}
                        size="small"
                        danger
                        onClick={() => void onDeleteNote(note.id)}
                      >
                        Delete
                      </Button>
                    </Space>
                  </div>
                </div>
              </List.Item>
            )}
          />
        )}
      </section>

      <section className="messenger-profile-section">
        <div className="messenger-profile-section-header">
          <Typography.Title level={5}>Timeline</Typography.Title>
        </div>
        {timeline.length === 0 ? (
          <Empty description="No timeline items yet" />
        ) : (
          <div className="messenger-timeline">
            {timeline.map((item) => {
              const isNote = item.type === "note";
              const label = isNote ? "Internal note added" : item.is_from_page ? "Agent replied" : "Customer sent message";
              const color = isNote ? "gold" : item.is_from_page ? "blue" : "green";
              return (
                <article key={`${item.type}-${item.timestamp}-${item.preview ?? item.content ?? ""}`} className="messenger-timeline-item">
                  <div className="messenger-timeline-header">
                    <Tag color={color} icon={isNote ? <FileTextOutlined /> : <MessageOutlined />}>
                      {label}
                    </Tag>
                    <Typography.Text type="secondary">{formatTimestamp(item.timestamp)}</Typography.Text>
                  </div>
                  <div className="messenger-timeline-body">{item.preview ?? item.content ?? "No content"}</div>
                </article>
              );
            })}
          </div>
        )}
      </section>
    </section>
  );
}

function formatTimestamp(value: string | null): string {
  if (!value) {
    return "Unknown time";
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}
