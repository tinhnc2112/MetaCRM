import {
  DeleteOutlined,
  EditOutlined,
  FileTextOutlined,
  MessageOutlined,
  SaveOutlined,
  TagOutlined
} from "@ant-design/icons";
import { Avatar, Badge, Button, Empty, Input, List, Select, Space, Spin, Tag, Typography } from "antd";
import { useEffect, useMemo, useState } from "react";

import type {
  CustomerProfileResponse,
  CustomerNoteSaveRequest,
  CustomerTag
} from "../types/customer";

type CustomerProfilePanelProps = {
  profile: CustomerProfileResponse | null;
  pageTags: CustomerTag[];
  loading: boolean;
  error: boolean;
  savingNote: boolean;
  savingTag: boolean;
  onSaveNote: (input: CustomerNoteSaveRequest) => Promise<void>;
  onDeleteNote: (noteId: string) => Promise<void>;
  onAssignTag: (tagId: number) => Promise<void>;
  onRemoveTag: (tagId: number) => Promise<void>;
  onManageTags: () => void;
};

export function CustomerProfilePanel({
  profile,
  pageTags,
  loading,
  error,
  savingNote,
  savingTag,
  onSaveNote,
  onDeleteNote,
  onAssignTag,
  onRemoveTag,
  onManageTags
}: CustomerProfilePanelProps) {
  const [noteId, setNoteId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [selectedTagId, setSelectedTagId] = useState<number | null>(null);

  const conversation = profile?.conversation ?? null;
  const notes = profile?.notes ?? [];
  const timeline = profile?.timeline ?? [];
  const assignedTags = profile?.tags ?? [];

  useEffect(() => {
    setNoteId(null);
    setDraft("");
    setSelectedTagId(null);
  }, [conversation?.uuid]);

  useEffect(() => {
    const assignedTagIds = new Set(assignedTags.map((tag) => tag.id));
    const availableTags = pageTags.filter((tag) => !assignedTagIds.has(tag.id));
    if (availableTags.length === 0) {
      setSelectedTagId(null);
      return;
    }
    if (selectedTagId === null || !availableTags.some((tag) => tag.id === selectedTagId)) {
      setSelectedTagId(availableTags[0].id);
    }
  }, [assignedTags, pageTags, selectedTagId]);

  const headerName = useMemo(() => conversation?.customer_name ?? conversation?.customer_psid ?? "Customer", [conversation]);
  const initial = headerName.slice(0, 1).toUpperCase();

  const availableTags = useMemo(() => {
    const assignedTagIds = new Set(assignedTags.map((tag) => tag.id));
    return pageTags.filter((tag) => !assignedTagIds.has(tag.id));
  }, [assignedTags, pageTags]);

  const handleSave = async () => {
    const content = draft.trim();
    if (!content) {
      return;
    }
    await onSaveNote({ noteId, content });
    setNoteId(null);
    setDraft("");
  };

  const handleAssignTag = async () => {
    if (selectedTagId === null) {
      return;
    }
    await onAssignTag(selectedTagId);
    setSelectedTagId(null);
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
          <Typography.Title level={5}>Tags</Typography.Title>
          <Button size="small" onClick={onManageTags}>
            Manage tags
          </Button>
        </div>
        {assignedTags.length === 0 ? (
          <Empty description="No tags assigned yet" />
        ) : (
          <div className="messenger-tag-list">
            {assignedTags.map((tag) => (
              <Tag
                key={tag.id}
                closable
                onClose={(event) => {
                  event.preventDefault();
                  void onRemoveTag(tag.id);
                }}
              >
                {tag.name}
              </Tag>
            ))}
          </div>
        )}
        <div className="messenger-tag-assigner">
          <Select
            showSearch
            placeholder={availableTags.length === 0 ? "No more tags available" : "Select a tag to assign"}
            optionFilterProp="label"
            value={selectedTagId ?? undefined}
            onChange={(value) => setSelectedTagId(value)}
            options={availableTags.map((tag) => ({
              value: tag.id,
              label: tag.name
            }))}
            disabled={availableTags.length === 0}
          />
          <Button type="primary" onClick={() => void handleAssignTag()} loading={savingTag} disabled={selectedTagId === null}>
            Assign tag
          </Button>
        </div>
      </section>

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
              const isTag = item.type === "tag";
              const label = isTag
                ? item.action === "removed"
                  ? `Tag removed${item.tag_name ? `: ${item.tag_name}` : ""}`
                  : `Tag added${item.tag_name ? `: ${item.tag_name}` : ""}`
                : isNote
                  ? "Internal note added"
                  : item.is_from_page
                    ? "Agent replied"
                    : "Customer sent message";
              const color = isTag ? (item.action === "removed" ? "volcano" : "purple") : isNote ? "gold" : item.is_from_page ? "blue" : "green";
              const icon = isTag ? <TagOutlined /> : isNote ? <FileTextOutlined /> : <MessageOutlined />;
              return (
                <article key={`${item.type}-${item.timestamp}-${item.preview ?? item.content ?? ""}`} className="messenger-timeline-item">
                  <div className="messenger-timeline-header">
                    <Tag color={color} icon={icon}>
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
