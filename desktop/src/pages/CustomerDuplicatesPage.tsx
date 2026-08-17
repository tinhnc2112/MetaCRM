import {
  ExclamationCircleOutlined,
  FileTextOutlined,
  SwapOutlined,
  TagOutlined,
} from "@ant-design/icons";
import { Alert, App, Avatar, Button, Card, Empty, List, Modal, Space, Spin, Tag, Typography } from "antd";
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getCurrentFacebookPage } from "../services/facebookService";
import { getCustomerProfile } from "../services/customerService";
import { listCustomerDuplicates, mergeCustomers } from "../services/customerDuplicateService";
import type { CustomerProfileResponse } from "../types/customer";

type DuplicatePairSelection = {
  primaryCustomerId: string;
  secondaryCustomerId: string;
};

export function CustomerDuplicatesPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [selection, setSelection] = useState<DuplicatePairSelection | null>(null);
  const [mergeModalOpen, setMergeModalOpen] = useState(false);

  const currentPageQuery = useQuery({
    queryKey: ["facebook-current-page"],
    queryFn: getCurrentFacebookPage
  });

  const currentPageId = currentPageQuery.data?.item?.page_id ?? null;

  const duplicatesQuery = useQuery({
    queryKey: ["customer-duplicates", currentPageId],
    queryFn: () => listCustomerDuplicates(1, 50),
    enabled: Boolean(currentPageId)
  });

  const candidates = duplicatesQuery.data?.items ?? [];
  const selectedCandidate = candidates[selectedIndex] ?? null;

  useEffect(() => {
    if (!selectedCandidate) {
      setSelection(null);
      return;
    }
    setSelection({
      primaryCustomerId: selectedCandidate.primary_customer.uuid,
      secondaryCustomerId: selectedCandidate.duplicate_customer.uuid
    });
  }, [selectedCandidate]);

  useEffect(() => {
    if (selectedIndex >= candidates.length) {
      setSelectedIndex(0);
    }
  }, [candidates.length, selectedIndex]);

  const primaryProfileQuery = useQuery({
    queryKey: ["customer-profile", currentPageId, selection?.primaryCustomerId],
    queryFn: () => getCustomerProfile(selection?.primaryCustomerId ?? ""),
    enabled: Boolean(currentPageId && selection?.primaryCustomerId)
  });

  const secondaryProfileQuery = useQuery({
    queryKey: ["customer-profile", currentPageId, selection?.secondaryCustomerId],
    queryFn: () => getCustomerProfile(selection?.secondaryCustomerId ?? ""),
    enabled: Boolean(currentPageId && selection?.secondaryCustomerId)
  });

  const mergeMutation = useMutation({
    mutationFn: ({
      primaryCustomerId,
      secondaryCustomerId
    }: {
      primaryCustomerId: string;
      secondaryCustomerId: string;
    }) => mergeCustomers(primaryCustomerId, { secondary_customer_id: secondaryCustomerId }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["customer-list", currentPageId] }),
        queryClient.invalidateQueries({ queryKey: ["customer-duplicates", currentPageId] }),
        queryClient.invalidateQueries({ queryKey: ["messenger-conversations", currentPageId] }),
        queryClient.invalidateQueries({ queryKey: ["customer-profile", currentPageId, selection?.primaryCustomerId] }),
        queryClient.invalidateQueries({ queryKey: ["customer-profile", currentPageId, selection?.secondaryCustomerId] })
      ]);
      setMergeModalOpen(false);
      void message.success("Customers merged.");
    },
    onError: (error) => {
      void message.error(error instanceof Error ? error.message : "Customers could not be merged.");
    }
  });

  const swapSelection = () => {
    if (!selection) {
      return;
    }
    setSelection({
      primaryCustomerId: selection.secondaryCustomerId,
      secondaryCustomerId: selection.primaryCustomerId
    });
  };

  const selectedTitle = useMemo(() => {
    if (!selection) {
      return null;
    }
    const primary =
      primaryProfileQuery.data?.customer?.name ??
      primaryProfileQuery.data?.conversation.customer_name ??
      primaryProfileQuery.data?.conversation.customer_psid;
    const secondary =
      secondaryProfileQuery.data?.customer?.name ??
      secondaryProfileQuery.data?.conversation.customer_name ??
      secondaryProfileQuery.data?.conversation.customer_psid;
    return {
      primary:
        primary ??
        selectedCandidate?.primary_customer.customer_name ??
        selectedCandidate?.primary_customer.customer_psid ??
        "Unknown customer",
      secondary:
        secondary ??
        selectedCandidate?.duplicate_customer.customer_name ??
        selectedCandidate?.duplicate_customer.customer_psid ??
        "Unknown customer"
    };
  }, [primaryProfileQuery.data?.conversation.customer_name, primaryProfileQuery.data?.conversation.customer_psid, secondaryProfileQuery.data?.conversation.customer_name, secondaryProfileQuery.data?.conversation.customer_psid, selection, selectedCandidate]);

  if (!currentPageId) {
    return (
      <Alert
        type="info"
        showIcon
        message="No Facebook Page selected"
        description="Open Facebook settings and select a page before reviewing duplicates."
      />
    );
  }

  return (
    <div className="customer-duplicates-page">
      <div className="customer-duplicates-header">
        <div>
          <Typography.Title level={2}>Customer Duplicates</Typography.Title>
          <Typography.Text type="secondary">
            Review conservative duplicate candidates and merge the secondary customer into the primary customer.
          </Typography.Text>
        </div>
        <Tag color="gold" icon={<ExclamationCircleOutlined />}>
          {candidates.length} candidates
        </Tag>
      </div>

      <div className="customer-duplicates-layout">
        <section className="customer-duplicates-list-panel">
          {duplicatesQuery.isLoading ? (
            <div className="customer-duplicates-loading">
              <Spin />
            </div>
          ) : duplicatesQuery.isError ? (
            <Alert type="error" showIcon message="Could not load duplicate candidates." />
          ) : candidates.length === 0 ? (
            <Empty description="No duplicate candidates found" />
          ) : (
            <List
              dataSource={candidates}
              renderItem={(candidate, index) => (
                <List.Item
                  className={index === selectedIndex ? "customer-duplicate-item selected" : "customer-duplicate-item"}
                  onClick={() => setSelectedIndex(index)}
                >
                  <div className="customer-duplicate-item-body">
                    <div className="customer-duplicate-item-header">
                      <div className="customer-duplicate-item-people">
                        <div className="customer-duplicate-item-person">
                          {candidate.primary_customer.customer_avatar_url ? (
                            <Avatar size={32} src={candidate.primary_customer.customer_avatar_url} />
                          ) : (
                            <Avatar size={32}>{getDuplicateInitial(candidate.primary_customer)}</Avatar>
                          )}
                          <div className="customer-duplicate-item-person-text">
                            <Typography.Text strong>
                              {candidate.primary_customer.customer_name ?? candidate.primary_customer.customer_psid}
                            </Typography.Text>
                            <Typography.Text type="secondary">
                              {formatTimestamp(candidate.primary_customer.last_message_at)}
                            </Typography.Text>
                          </div>
                        </div>
                        <SwapOutlined className="customer-duplicate-item-vs" />
                        <div className="customer-duplicate-item-person">
                          {candidate.duplicate_customer.customer_avatar_url ? (
                            <Avatar size={32} src={candidate.duplicate_customer.customer_avatar_url} />
                          ) : (
                            <Avatar size={32}>{getDuplicateInitial(candidate.duplicate_customer)}</Avatar>
                          )}
                          <div className="customer-duplicate-item-person-text">
                            <Typography.Text strong>
                              {candidate.duplicate_customer.customer_name ?? candidate.duplicate_customer.customer_psid}
                            </Typography.Text>
                            <Typography.Text type="secondary">
                              {formatTimestamp(candidate.duplicate_customer.last_message_at)}
                            </Typography.Text>
                          </div>
                        </div>
                      </div>
                      <Tag color={confidenceColor(candidate.confidence)}>{Math.round(candidate.confidence * 100)}%</Tag>
                    </div>
                    <Typography.Paragraph type="secondary" className="customer-duplicate-reason">
                      {candidate.reason}
                    </Typography.Paragraph>
                    <Space wrap>
                      {candidate.matching_fields.map((field) => (
                        <Tag key={field}>{formatField(field)}</Tag>
                      ))}
                    </Space>
                    <div className="customer-duplicate-signals">
                      {candidate.matching_signals.map((signal) => (
                        <Tag key={signal} color="blue">
                          {signal}
                        </Tag>
                      ))}
                    </div>
                  </div>
                </List.Item>
              )}
            />
          )}
        </section>

        <section className="customer-duplicates-comparison-panel">
          {!selectedCandidate || !selection ? (
            <Empty description="Select a duplicate candidate to compare customers" />
          ) : (
            <>
              <div className="customer-duplicates-comparison-header">
                <div>
                  <Typography.Title level={4}>Side-by-side comparison</Typography.Title>
                  <Typography.Text type="secondary">
                    Verify which profile should remain the primary customer before consolidating history.
                  </Typography.Text>
                </div>
                <Space wrap>
                  <Button icon={<SwapOutlined />} onClick={swapSelection}>
                    Swap primary / secondary
                  </Button>
                  <Button type="primary" danger onClick={() => setMergeModalOpen(true)}>
                    Merge customers
                  </Button>
                </Space>
              </div>

              <Alert
                type="warning"
                showIcon
                message="The secondary customer's history, notes, tags, and timeline will be consolidated into the primary customer."
              />

              <div className="customer-duplicates-columns">
                <CustomerDuplicateProfileCard
                  title="PRIMARY CUSTOMER"
                  profile={primaryProfileQuery.data ?? null}
                  loading={primaryProfileQuery.isLoading}
                  error={primaryProfileQuery.isError}
                  accent="blue"
                />
                <CustomerDuplicateProfileCard
                  title="SECONDARY CUSTOMER"
                  profile={secondaryProfileQuery.data ?? null}
                  loading={secondaryProfileQuery.isLoading}
                  error={secondaryProfileQuery.isError}
                  accent="volcano"
                />
              </div>
            </>
          )}
        </section>
      </div>

      <Modal
        title="Confirm customer merge"
        open={mergeModalOpen}
        onCancel={() => setMergeModalOpen(false)}
        onOk={() => {
          if (!selection) {
            return;
          }
          void mergeMutation.mutateAsync(selection);
        }}
        okText="Merge customers"
        okButtonProps={{ danger: true, loading: mergeMutation.isPending }}
        cancelText="Cancel"
      >
        <Space direction="vertical" size={12} style={{ width: "100%" }}>
          <Alert
            type="warning"
            showIcon
            message="This action consolidates the secondary customer's messages, notes, tags, and tag history into the primary customer."
          />
          <div className="customer-merge-summary">
            <div>
              <Typography.Text type="secondary">PRIMARY CUSTOMER</Typography.Text>
              <Typography.Title level={5}>{selectedTitle?.primary ?? "Unknown customer"}</Typography.Title>
            </div>
            <div>
              <Typography.Text type="secondary">SECONDARY CUSTOMER</Typography.Text>
              <Typography.Title level={5}>{selectedTitle?.secondary ?? "Unknown customer"}</Typography.Title>
            </div>
          </div>
          <div className="customer-merge-preview">
            <Typography.Text type="secondary">After merge, the primary customer keeps:</Typography.Text>
            <div className="customer-merge-preview-list">
              <Tag color="blue">Timeline</Tag>
              <Tag color="blue">Notes</Tag>
              <Tag color="blue">Tags</Tag>
              <Tag color="blue">Conversations</Tag>
              <Tag color="blue">Messages</Tag>
            </div>
            <Typography.Text type="secondary">
              The secondary customer will no longer appear as an independent profile.
            </Typography.Text>
          </div>
        </Space>
      </Modal>
    </div>
  );
}

function CustomerDuplicateProfileCard({
  title,
  profile,
  loading,
  error,
  accent
}: {
  title: string;
  profile: CustomerProfileResponse | null;
  loading: boolean;
  error: boolean;
  accent: "blue" | "volcano";
}) {
  if (loading && !profile) {
    return (
      <Card className="customer-duplicate-profile-card">
        <div className="customer-duplicates-loading">
          <Spin />
        </div>
      </Card>
    );
  }

  if (error) {
    return (
      <Card className="customer-duplicate-profile-card">
        <Alert type="error" showIcon message="Could not load customer profile." />
      </Card>
    );
  }

  if (!profile) {
    return (
      <Card className="customer-duplicate-profile-card">
        <Empty description="No customer profile loaded" />
      </Card>
    );
  }

  const conversation = profile.conversation;
  const customer = profile.customer;
  const displayName = customer?.name ?? conversation.customer_name ?? conversation.customer_psid;
  const initial = displayName.slice(0, 1).toUpperCase();
  const customerPhone = customer?.phone ?? null;
  const customerEmail = customer?.email ?? null;
  const customerConversationCount = customer?.conversation_count ?? profile.conversations.length;
  const latestActivity = customer?.last_message_at ?? conversation.last_message_at;
  const notesCount = profile.notes.length;

  return (
    <Card className="customer-duplicate-profile-card" title={<Tag color={accent}>{title}</Tag>}>
      <div className="customer-duplicate-profile-header">
        {conversation.customer_avatar_url ? (
          <Avatar size={56} src={conversation.customer_avatar_url} />
        ) : (
          <Avatar size={56}>{initial}</Avatar>
        )}
        <div>
          <Typography.Title level={4}>{displayName}</Typography.Title>
          <Typography.Text type="secondary">{conversation.customer_psid}</Typography.Text>
        </div>
      </div>

      <div className="customer-duplicate-meta">
        <div>
          <span className="customer-duplicate-label">Phone</span>
          <Typography.Text copyable={customerPhone ? { text: customerPhone } : undefined} className="customer-duplicate-value">
            {customerPhone ?? "Unavailable"}
          </Typography.Text>
        </div>
        <div>
          <span className="customer-duplicate-label">Email</span>
          <Typography.Text copyable={customerEmail ? { text: customerEmail } : undefined} className="customer-duplicate-value">
            {customerEmail ?? "Unavailable"}
          </Typography.Text>
        </div>
        <div>
          <span className="customer-duplicate-label">Conversations</span>
          <Typography.Text>{customerConversationCount}</Typography.Text>
        </div>
        <div>
          <span className="customer-duplicate-label">Notes</span>
          <Typography.Text>{notesCount}</Typography.Text>
        </div>
        <div>
          <span className="customer-duplicate-label">Latest activity</span>
          <Typography.Text>{formatTimestamp(latestActivity)}</Typography.Text>
        </div>
      </div>

      <section className="customer-duplicate-section">
        <div className="customer-duplicate-section-header">
          <Typography.Title level={5}>Tags</Typography.Title>
        </div>
        {profile.tags.length === 0 ? (
          <Empty description="No tags assigned" />
        ) : (
          <div className="customer-duplicate-tag-list">
            {profile.tags.map((tag) => (
              <Tag key={tag.id} icon={<TagOutlined />}>
                {tag.name}
              </Tag>
            ))}
          </div>
        )}
      </section>

      <section className="customer-duplicate-section">
        <div className="customer-duplicate-section-header">
          <Typography.Title level={5}>Notes</Typography.Title>
        </div>
        {profile.notes.length === 0 ? (
          <Empty description="No notes on this customer" />
        ) : (
          <List
            size="small"
            dataSource={profile.notes.slice(0, 3)}
            renderItem={(note) => (
              <List.Item>
                <List.Item.Meta
                  avatar={<Avatar icon={<FileTextOutlined />} />}
                  title={note.content}
                  description={formatTimestamp(note.created_at)}
                />
              </List.Item>
            )}
          />
        )}
      </section>

      <section className="customer-duplicate-section">
        <div className="customer-duplicate-section-header">
          <Typography.Title level={5}>Timeline preview</Typography.Title>
        </div>
        {profile.timeline.length === 0 ? (
          <Empty description="No timeline items" />
        ) : (
          <div className="customer-duplicate-timeline">
            {profile.timeline.slice(0, 4).map((item) => {
              const label =
                item.type === "message"
                  ? item.is_from_page
                    ? "Agent replied"
                    : "Customer message"
                  : item.type === "note"
                    ? "Internal note"
                    : item.action === "removed"
                      ? "Tag removed"
                      : "Tag added";
              return (
                <article key={`${item.type}-${item.timestamp}-${item.preview ?? item.content ?? ""}`} className="customer-duplicate-timeline-item">
                  <div className="customer-duplicate-timeline-header">
                    <Tag color={item.type === "message" ? "blue" : item.type === "note" ? "gold" : "purple"}>
                      {label}
                    </Tag>
                    <Typography.Text type="secondary">{formatTimestamp(item.timestamp)}</Typography.Text>
                  </div>
                  <div className="customer-duplicate-timeline-body">
                    {item.preview ?? item.content ?? item.tag_name ?? "No content"}
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </section>
    </Card>
  );
}

function confidenceColor(confidence: number): "green" | "gold" | "orange" | "red" {
  if (confidence >= 0.95) {
    return "green";
  }
  if (confidence >= 0.9) {
    return "gold";
  }
  if (confidence >= 0.75) {
    return "orange";
  }
  return "red";
}

function formatField(field: string): string {
  const lookup: Record<string, string> = {
    psid: "PSID",
    customer_name: "Customer name",
    customer_avatar_url: "Avatar URL"
  };
  return lookup[field] ?? field;
}

function formatTimestamp(value: string | null): string {
  if (!value) {
    return "Unknown time";
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function getDuplicateInitial(conversation: CustomerProfileResponse["conversation"]): string {
  const value = conversation.customer_name ?? conversation.customer_psid;
  return value.slice(0, 1).toUpperCase();
}
