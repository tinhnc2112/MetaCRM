import { DeleteOutlined, EditOutlined, TeamOutlined } from "@ant-design/icons";
import { Avatar, Button, Empty, Input, List, Modal, Space, Spin, Tag, Typography } from "antd";
import { useEffect, useMemo, useState } from "react";

import type { CustomerProfileConversation, CustomerTag } from "../types/customer";

type CustomerTagManagerModalProps = {
  open: boolean;
  tags: CustomerTag[];
  selectedTagId: number | null;
  customers: CustomerProfileConversation[];
  customersLoading: boolean;
  onClose: () => void;
  onSelectTag: (tagId: number | null) => void;
  onCreateTag: (input: { name: string; description: string | null }) => Promise<void>;
  onUpdateTag: (tagId: number, input: { name: string; description: string | null }) => Promise<void>;
  onDeleteTag: (tagId: number) => Promise<void>;
  onSelectConversation?: (conversationId: string) => void;
};

export function CustomerTagManagerModal({
  open,
  tags,
  selectedTagId,
  customers,
  customersLoading,
  onClose,
  onSelectTag,
  onCreateTag,
  onUpdateTag,
  onDeleteTag,
  onSelectConversation
}: CustomerTagManagerModalProps) {
  const [createName, setCreateName] = useState("");
  const [createDescription, setCreateDescription] = useState("");
  const [editingTagId, setEditingTagId] = useState<number | null>(null);
  const [editName, setEditName] = useState("");
  const [editDescription, setEditDescription] = useState("");

  const selectedTag = useMemo(
    () => tags.find((tag) => tag.id === selectedTagId) ?? null,
    [selectedTagId, tags]
  );

  useEffect(() => {
    if (!open) {
      return;
    }
    if (editingTagId !== null && !tags.some((tag) => tag.id === editingTagId)) {
      setEditingTagId(null);
    }
  }, [editingTagId, open, tags]);

  useEffect(() => {
    if (!open) {
      setCreateName("");
      setCreateDescription("");
      setEditingTagId(null);
      setEditName("");
      setEditDescription("");
    }
  }, [open]);

  const startEdit = (tag: CustomerTag) => {
    setEditingTagId(tag.id);
    setEditName(tag.name);
    setEditDescription(tag.description ?? "");
  };

  const finishCreate = async () => {
    const name = createName.trim();
    if (!name) {
      return;
    }
    await onCreateTag({
      name,
      description: createDescription.trim() ? createDescription.trim() : null
    });
    setCreateName("");
    setCreateDescription("");
  };

  const finishUpdate = async () => {
    if (editingTagId === null) {
      return;
    }
    const name = editName.trim();
    if (!name) {
      return;
    }
    await onUpdateTag(editingTagId, {
      name,
      description: editDescription.trim() ? editDescription.trim() : null
    });
    setEditingTagId(null);
    setEditName("");
    setEditDescription("");
  };

  return (
    <Modal
      title="Manage customer tags"
      open={open}
      onCancel={onClose}
      footer={null}
      width={980}
      destroyOnClose
    >
      <div className="customer-tag-manager">
        <section className="customer-tag-manager-section">
          <Typography.Title level={5}>Create tag</Typography.Title>
          <Space direction="vertical" size={12} style={{ width: "100%" }}>
            <Input
              value={createName}
              onChange={(event) => setCreateName(event.target.value)}
              placeholder="Tag name"
            />
            <Input.TextArea
              value={createDescription}
              onChange={(event) => setCreateDescription(event.target.value)}
              placeholder="Optional description"
              autoSize={{ minRows: 2, maxRows: 4 }}
            />
            <Button type="primary" onClick={() => void finishCreate()} disabled={!createName.trim()}>
              Create tag
            </Button>
          </Space>
        </section>

        <section className="customer-tag-manager-section">
          <div className="customer-tag-manager-header">
            <Typography.Title level={5}>Available tags</Typography.Title>
            <Tag icon={<TeamOutlined />}>{tags.length} total</Tag>
          </div>
          {tags.length === 0 ? (
            <Empty description="No tags yet" />
          ) : (
            <List
              dataSource={tags}
              renderItem={(tag) => (
                <List.Item className="customer-tag-manager-item">
                  <div className="customer-tag-manager-tag">
                    <div>
                      <Typography.Text strong>{tag.name}</Typography.Text>
                      <div className="customer-tag-manager-slug">{tag.slug}</div>
                      {tag.description ? (
                        <Typography.Text type="secondary">{tag.description}</Typography.Text>
                      ) : null}
                    </div>
                    <Tag>{tag.customer_count} customers</Tag>
                  </div>
                  <Space wrap>
                    <Button size="small" onClick={() => onSelectTag(tag.id)}>
                      View customers
                    </Button>
                    <Button size="small" icon={<EditOutlined />} onClick={() => startEdit(tag)}>
                      Edit
                    </Button>
                    <Button size="small" danger icon={<DeleteOutlined />} onClick={() => void onDeleteTag(tag.id)}>
                      Delete
                    </Button>
                  </Space>
                </List.Item>
              )}
            />
          )}
        </section>

        {editingTagId !== null ? (
          <section className="customer-tag-manager-section">
            <Typography.Title level={5}>Edit tag</Typography.Title>
            <Space direction="vertical" size={12} style={{ width: "100%" }}>
              <Input value={editName} onChange={(event) => setEditName(event.target.value)} placeholder="Tag name" />
              <Input.TextArea
                value={editDescription}
                onChange={(event) => setEditDescription(event.target.value)}
                placeholder="Optional description"
                autoSize={{ minRows: 2, maxRows: 4 }}
              />
              <Space>
                <Button type="primary" onClick={() => void finishUpdate()} disabled={!editName.trim()}>
                  Save changes
                </Button>
                <Button
                  onClick={() => {
                    setEditingTagId(null);
                    setEditName("");
                    setEditDescription("");
                  }}
                >
                  Cancel
                </Button>
              </Space>
            </Space>
          </section>
        ) : null}

        <section className="customer-tag-manager-section customer-tag-manager-customers">
          <div className="customer-tag-manager-header">
            <div>
              <Typography.Title level={5}>Customers in tag</Typography.Title>
              <Typography.Text type="secondary">
                {selectedTag ? `Browsing "${selectedTag.name}"` : "Select a tag to browse its customers"}
              </Typography.Text>
            </div>
          </div>
          {!selectedTag ? (
            <Empty description="Pick a tag to see matching customers" />
          ) : customersLoading ? (
            <div className="messenger-loading">
              <Spin />
            </div>
          ) : customers.length === 0 ? (
            <Empty description="No customers in this tag" />
          ) : (
            <List
              dataSource={customers}
              renderItem={(customer) => {
                const displayName = customer.customer_name ?? customer.customer_psid;
                return (
                  <List.Item className="customer-tag-manager-customer">
                    <List.Item.Meta
                      avatar={
                        customer.customer_avatar_url ? (
                          <Avatar src={customer.customer_avatar_url} />
                        ) : (
                          <Avatar>{displayName.slice(0, 1).toUpperCase()}</Avatar>
                        )
                      }
                      title={displayName}
                      description={`PSID ${customer.customer_psid}`}
                    />
                    {onSelectConversation ? (
                      <Button size="small" onClick={() => onSelectConversation(customer.uuid)}>
                        Open
                      </Button>
                    ) : null}
                  </List.Item>
                );
              }}
            />
          )}
        </section>
      </div>
    </Modal>
  );
}
