import {
  DeleteOutlined,
  EditOutlined,
  EyeOutlined,
  FilterOutlined,
  PlusOutlined,
  PoweroffOutlined,
  SafetyOutlined
} from "@ant-design/icons";
import { App, Alert, Avatar, Button, Empty, Input, List, Modal, Select, Space, Spin, Switch, Tag, Typography } from "antd";
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getCurrentFacebookPage } from "../services/facebookService";
import { listCustomerTags } from "../services/customerTagService";
import {
  createCustomerSegment,
  deleteCustomerSegment,
  listCustomerSegments,
  previewCustomerSegment,
  previewCustomerSegmentDefinition,
  updateCustomerSegment
} from "../services/customerSegmentService";
import type {
  CustomerSegment,
  CustomerSegmentField,
  CustomerSegmentOperator,
  CustomerSegmentPreviewResponse,
  CustomerSegmentRuleInput,
  CustomerSegmentUpsertInput
} from "../types/segment";
import type { CustomerTag } from "../types/customer";

type SegmentDraftRule = {
  field: CustomerSegmentField;
  operator: CustomerSegmentOperator;
  value: string;
};

type SegmentDraft = {
  name: string;
  description: string;
  active: boolean;
  rules: SegmentDraftRule[];
};

const DEFAULT_FIELD: CustomerSegmentField = "TAG";

const FIELD_OPTIONS: Array<{ label: string; value: CustomerSegmentField }> = [
  { label: "Tag", value: "TAG" },
  { label: "Customer status", value: "CUSTOMER_STATUS" },
  { label: "Conversation status", value: "CONVERSATION_STATUS" },
  { label: "Last activity", value: "LAST_ACTIVITY" },
  { label: "Order count", value: "ORDER_COUNT" },
  { label: "Total spent", value: "TOTAL_SPENT" }
];

const STATUS_OPERATOR_OPTIONS: Array<{ label: string; value: CustomerSegmentOperator }> = [
  { label: "is", value: "equals" },
  { label: "is not", value: "not_equals" },
  { label: "contains", value: "contains" }
];

const DATE_OPERATOR_OPTIONS: Array<{ label: string; value: CustomerSegmentOperator }> = [
  { label: "is", value: "equals" },
  { label: "is not", value: "not_equals" },
  { label: "after", value: "after" },
  { label: "before", value: "before" },
  { label: "greater than", value: "greater_than" },
  { label: "greater or equal", value: "greater_or_equal" },
  { label: "less than", value: "less_than" },
  { label: "less or equal", value: "less_or_equal" }
];

const NUMERIC_OPERATOR_OPTIONS: Array<{ label: string; value: CustomerSegmentOperator }> = [
  { label: "is", value: "equals" },
  { label: "is not", value: "not_equals" },
  { label: "greater than", value: "greater_than" },
  { label: "greater or equal", value: "greater_or_equal" },
  { label: "less than", value: "less_than" },
  { label: "less or equal", value: "less_or_equal" }
];

const TAG_OPERATOR_OPTIONS: Array<{ label: string; value: CustomerSegmentOperator }> = STATUS_OPERATOR_OPTIONS;

const CUSTOMER_STATUS_OPTIONS = [
  { label: "New", value: "new" },
  { label: "Active", value: "active" },
  { label: "Inactive", value: "inactive" }
];

const CONVERSATION_STATUS_OPTIONS = [
  { label: "Open", value: "open" },
  { label: "Closed", value: "closed" }
];

export function CustomerSegmentsPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingSegment, setEditingSegment] = useState<CustomerSegment | null>(null);
  const [draft, setDraft] = useState<SegmentDraft>(createEmptyDraft());
  const [previewResult, setPreviewResult] = useState<CustomerSegmentPreviewResponse | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);

  const currentPageQuery = useQuery({
    queryKey: ["facebook-current-page"],
    queryFn: getCurrentFacebookPage
  });

  const currentPageId = currentPageQuery.data?.item?.page_id ?? null;

  const segmentsQuery = useQuery({
    queryKey: ["customer-segments", currentPageId],
    queryFn: listCustomerSegments,
    enabled: Boolean(currentPageId)
  });

  const tagsQuery = useQuery({
    queryKey: ["customer-tags", currentPageId],
    queryFn: listCustomerTags,
    enabled: Boolean(currentPageId)
  });

  const createMutation = useMutation({
    mutationFn: createCustomerSegment,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["customer-segments", currentPageId] });
      setEditorOpen(false);
      setEditingSegment(null);
      setPreviewResult(null);
      void message.success("Segment created.");
    },
    onError: () => {
      void message.error("Segment could not be created.");
    }
  });

  const updateMutation = useMutation({
    mutationFn: ({ segmentId, input }: { segmentId: number; input: CustomerSegmentUpsertInput }) =>
      updateCustomerSegment(segmentId, input),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["customer-segments", currentPageId] });
      setEditorOpen(false);
      setEditingSegment(null);
      setPreviewResult(null);
      void message.success("Segment updated.");
    },
    onError: () => {
      void message.error("Segment could not be updated.");
    }
  });

  const deleteMutation = useMutation({
    mutationFn: deleteCustomerSegment,
    onSuccess: async (_, segmentId) => {
      await queryClient.invalidateQueries({ queryKey: ["customer-segments", currentPageId] });
      if (editingSegment?.id === segmentId) {
        setEditorOpen(false);
        setEditingSegment(null);
        setPreviewResult(null);
      }
      void message.success("Segment deleted.");
    },
    onError: () => {
      void message.error("Segment could not be deleted.");
    }
  });

  const previewMutation = useMutation({
    mutationFn: (input: CustomerSegmentUpsertInput) => previewCustomerSegmentDefinition(input),
    onSuccess: (result) => {
      setPreviewResult(result);
      setPreviewError(null);
    },
    onError: () => {
      setPreviewError("Preview could not be loaded.");
    }
  });

  const previewSavedMutation = useMutation({
    mutationFn: (segmentId: number) => previewCustomerSegment(segmentId),
    onSuccess: (result) => {
      setPreviewResult(result);
      setPreviewError(null);
      setEditorOpen(true);
    },
    onError: () => {
      setPreviewError("Preview could not be loaded.");
    }
  });

  const toggleMutation = useMutation({
    mutationFn: ({ segment, active }: { segment: CustomerSegment; active: boolean }) =>
      updateCustomerSegment(segment.id, buildUpsertInput(fromSegment(segment, tagsQuery.data?.items ?? []), { active })),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["customer-segments", currentPageId] });
    },
    onError: () => {
      void message.error("Segment status could not be updated.");
    }
  });

  const segments = segmentsQuery.data?.items ?? [];
  const tags = tagsQuery.data?.items ?? [];
  const tagOptions = useMemo(
    () =>
      tags.map((tag: CustomerTag) => ({
        value: tag.name,
        label: `${tag.name} (${tag.slug})`
      })),
    [tags]
  );

  const openCreate = () => {
    setEditingSegment(null);
    setDraft(createEmptyDraft());
    setPreviewResult(null);
    setPreviewError(null);
    setEditorOpen(true);
  };

  const openEdit = (segment: CustomerSegment) => {
    setEditingSegment(segment);
    setDraft(fromSegment(segment, tags));
    setPreviewResult(null);
    setPreviewError(null);
    setEditorOpen(true);
  };

  const openSavedPreview = async (segment: CustomerSegment) => {
    setEditingSegment(segment);
    setDraft(fromSegment(segment, tags));
    await previewSavedMutation.mutateAsync(segment.id);
  };

  const handleSave = async () => {
    try {
      const input = buildUpsertInput(draft);
      if (editingSegment) {
        await updateMutation.mutateAsync({ segmentId: editingSegment.id, input });
        return;
      }
      await createMutation.mutateAsync(input);
    } catch (error) {
      void message.error(error instanceof Error ? error.message : "Segment could not be saved.");
    }
  };

  const handlePreview = async () => {
    try {
      const input = buildUpsertInput(draft);
      await previewMutation.mutateAsync(input);
    } catch (error) {
      setPreviewError(error instanceof Error ? error.message : "Preview could not be loaded.");
    }
  };

  const handleDelete = (segment: CustomerSegment) => {
    Modal.confirm({
      title: `Delete ${segment.name}?`,
      content: "This will remove the segment and its rules.",
      okText: "Delete",
      okButtonProps: { danger: true },
      onOk: () => deleteMutation.mutateAsync(segment.id)
    });
  };

  const handleToggle = (segment: CustomerSegment, active: boolean) => {
    void toggleMutation.mutateAsync({ segment, active });
  };

  if (!currentPageId) {
    return (
      <Alert
        type="info"
        showIcon
        message="No Facebook Page selected"
        description="Open Facebook settings and select a page before managing segments."
      />
    );
  }

  return (
    <div className="customer-segments-page">
      <div className="customer-segments-header">
        <div>
          <Typography.Title level={2}>Customer Segments</Typography.Title>
          <Typography.Text type="secondary">
            Build reusable filters on top of your customer tags and conversation activity.
          </Typography.Text>
        </div>
        <Space>
          <Tag color="blue" icon={<FilterOutlined />}>
            {segments.length} segments
          </Tag>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            Create Segment
          </Button>
        </Space>
      </div>

      <section className="customer-segments-section">
        {segmentsQuery.isLoading ? (
          <div className="customer-segments-loading">
            <Spin />
          </div>
        ) : segmentsQuery.isError ? (
          <Alert type="error" showIcon message="Could not load segments." />
        ) : segments.length === 0 ? (
          <Empty description="No segments yet" />
        ) : (
          <List
            dataSource={segments}
            renderItem={(segment) => (
              <List.Item className="customer-segment-item">
                <div className="customer-segment-card">
                  <div className="customer-segment-card-header">
                    <div className="customer-segment-card-title">
                      <Typography.Title level={4}>{segment.name}</Typography.Title>
                      <Space wrap>
                        <Tag color={segment.active ? "success" : "default"}>
                          {segment.active ? "Active" : "Inactive"}
                        </Tag>
                        <Tag icon={<SafetyOutlined />}>{segment.customer_count} customers</Tag>
                      </Space>
                    </div>
                    <Switch checked={segment.active} onChange={(checked) => handleToggle(segment, checked)} />
                  </div>
                  {segment.description ? (
                    <Typography.Paragraph type="secondary" className="customer-segment-description">
                      {segment.description}
                    </Typography.Paragraph>
                  ) : null}
                  <div className="customer-segment-rule-summary">
                    {segment.rules.length === 0 ? (
                      <Tag>No rules</Tag>
                    ) : (
                      segment.rules.map((rule) => (
                        <Tag key={rule.id}>{formatRule(rule.field, rule.operator, rule.value)}</Tag>
                      ))
                    )}
                  </div>
                  <div className="customer-segment-card-actions">
                    <Space wrap>
                      <Button icon={<EyeOutlined />} onClick={() => void openSavedPreview(segment)}>
                        Preview
                      </Button>
                      <Button icon={<EditOutlined />} onClick={() => openEdit(segment)}>
                        Edit
                      </Button>
                      <Button danger icon={<DeleteOutlined />} onClick={() => handleDelete(segment)}>
                        Delete
                      </Button>
                    </Space>
                    <Typography.Text type="secondary">
                      Created {formatTimestamp(segment.created_at)}
                    </Typography.Text>
                  </div>
                </div>
              </List.Item>
            )}
          />
        )}
      </section>

      <Modal
        title={editingSegment ? `Edit Segment` : "Create Segment"}
        open={editorOpen}
        onCancel={() => {
          setEditorOpen(false);
          setEditingSegment(null);
          setPreviewResult(null);
          setPreviewError(null);
        }}
        width={1120}
        footer={null}
        destroyOnClose
      >
        <div className="customer-segment-editor">
          <section className="customer-segment-editor-panel">
            <Typography.Title level={5}>Segment details</Typography.Title>
            <Space direction="vertical" size={12} style={{ width: "100%" }}>
              <Input
                value={draft.name}
                onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))}
                placeholder="Segment name"
              />
              <Input.TextArea
                value={draft.description}
                onChange={(event) => setDraft((current) => ({ ...current, description: event.target.value }))}
                placeholder="Optional description"
                autoSize={{ minRows: 2, maxRows: 4 }}
              />
              <Space align="center">
                <Switch
                  checked={draft.active}
                  onChange={(checked) => setDraft((current) => ({ ...current, active: checked }))}
                />
                <Typography.Text>{draft.active ? "Active" : "Inactive"}</Typography.Text>
              </Space>
            </Space>

            <div className="customer-segment-rule-editor-header">
              <Typography.Title level={5}>Conditions</Typography.Title>
              <Button
                icon={<PlusOutlined />}
                onClick={() =>
                  setDraft((current) => ({
                    ...current,
                    rules: [...current.rules, { field: DEFAULT_FIELD, operator: "equals", value: "" }]
                  }))
                }
              >
                Add rule
              </Button>
            </div>

            <div className="customer-segment-rules">
              {draft.rules.map((rule, index) => (
                <SegmentRuleRow
                  key={`${index}-${rule.field}-${rule.operator}`}
                  rule={rule}
                  tagOptions={tagOptions}
                  onChange={(next) =>
                    setDraft((current) => ({
                      ...current,
                      rules: current.rules.map((item, itemIndex) => (itemIndex === index ? next : item))
                    }))
                  }
                  onRemove={() =>
                    setDraft((current) => ({
                      ...current,
                      rules: current.rules.filter((_, itemIndex) => itemIndex !== index)
                    }))
                  }
                />
              ))}
            </div>

            <Space className="customer-segment-editor-actions" wrap>
              <Button type="primary" onClick={() => void handleSave()} loading={createMutation.isPending || updateMutation.isPending}>
                Save
              </Button>
              <Button icon={<EyeOutlined />} onClick={() => void handlePreview()} loading={previewMutation.isPending}>
                Preview
              </Button>
              <Button
                onClick={() => {
                  setEditorOpen(false);
                  setEditingSegment(null);
                  setPreviewResult(null);
                  setPreviewError(null);
                }}
              >
                Cancel
              </Button>
            </Space>
          </section>

          <section className="customer-segment-editor-panel customer-segment-preview-panel">
            <div className="customer-segment-preview-header">
              <div>
                <Typography.Title level={5}>Preview</Typography.Title>
                <Typography.Text type="secondary">
                  Preview the current rules before saving them.
                </Typography.Text>
              </div>
              {previewResult ? <Tag color="blue">{previewResult.meta.total} customers</Tag> : null}
            </div>

            {previewError ? <Alert type="error" showIcon message={previewError} /> : null}

            {previewResult ? (
              previewResult.items.length === 0 ? (
                <Empty description="No customers match the current rules" />
              ) : (
                <List
                  dataSource={previewResult.items}
                  renderItem={(customer) => {
                    const displayName = customer.customer_name ?? customer.customer_psid;
                    return (
                      <List.Item className="customer-segment-preview-item">
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
                        <Tag icon={<PoweroffOutlined />}>{formatTimestamp(customer.last_message_at)}</Tag>
                      </List.Item>
                    );
                  }}
                />
              )
            ) : (
              <Empty description="Run a preview to see matching customers" />
            )}
          </section>
        </div>
      </Modal>
    </div>
  );
}

function SegmentRuleRow({
  rule,
  tagOptions,
  onChange,
  onRemove
}: {
  rule: SegmentDraftRule;
  tagOptions: Array<{ label: string; value: string }>;
  onChange: (rule: SegmentDraftRule) => void;
  onRemove: () => void;
}) {
  const operatorOptions = getOperatorOptions(rule.field);
  return (
    <div className="customer-segment-rule-row">
      <Select
        value={rule.field}
        options={FIELD_OPTIONS}
        onChange={(field) =>
          onChange({
            field,
            operator: getDefaultOperator(field),
            value: getDefaultValue(field)
          })
        }
      />
      <Select
        value={rule.operator}
        options={operatorOptions}
        onChange={(operator) => onChange({ ...rule, operator })}
      />
      {renderRuleValueControl(rule, tagOptions, onChange)}
      <Button danger onClick={onRemove}>
        Remove
      </Button>
    </div>
  );
}

function renderRuleValueControl(
  rule: SegmentDraftRule,
  tagOptions: Array<{ label: string; value: string }>,
  onChange: (rule: SegmentDraftRule) => void
) {
  if (rule.field === "TAG") {
    return (
      <Select
        showSearch
        placeholder="Select a tag"
        optionFilterProp="label"
        value={rule.value || undefined}
        options={tagOptions}
        onChange={(value) => onChange({ ...rule, value })}
      />
    );
  }

  if (rule.field === "CUSTOMER_STATUS") {
    return (
      <Select
        value={rule.value || undefined}
        options={CUSTOMER_STATUS_OPTIONS}
        onChange={(value) => onChange({ ...rule, value })}
      />
    );
  }

  if (rule.field === "CONVERSATION_STATUS") {
    return (
      <Select
        value={rule.value || undefined}
        options={CONVERSATION_STATUS_OPTIONS}
        onChange={(value) => onChange({ ...rule, value })}
      />
    );
  }

  if (rule.field === "LAST_ACTIVITY") {
    return (
      <Input
        type="datetime-local"
        value={rule.value}
        onChange={(event) => onChange({ ...rule, value: event.target.value })}
      />
    );
  }

  return (
    <Input
      inputMode="decimal"
      placeholder="Enter a number"
      value={rule.value}
      onChange={(event) => onChange({ ...rule, value: event.target.value })}
    />
  );
}

function getOperatorOptions(field: CustomerSegmentField): Array<{ label: string; value: CustomerSegmentOperator }> {
  if (field === "TAG") {
    return TAG_OPERATOR_OPTIONS;
  }
  if (field === "CUSTOMER_STATUS" || field === "CONVERSATION_STATUS") {
    return STATUS_OPERATOR_OPTIONS;
  }
  if (field === "LAST_ACTIVITY") {
    return DATE_OPERATOR_OPTIONS;
  }
  return NUMERIC_OPERATOR_OPTIONS;
}

function getDefaultOperator(field: CustomerSegmentField): CustomerSegmentOperator {
  return getOperatorOptions(field)[0]?.value ?? "equals";
}

function getDefaultValue(field: CustomerSegmentField): string {
  if (field === "CUSTOMER_STATUS") {
    return "active";
  }
  if (field === "CONVERSATION_STATUS") {
    return "open";
  }
  return "";
}

function createEmptyDraft(): SegmentDraft {
  return {
    name: "",
    description: "",
    active: true,
    rules: [{ field: DEFAULT_FIELD, operator: "equals", value: "" }]
  };
}

function fromSegment(segment: CustomerSegment, tags: CustomerTag[]): SegmentDraft {
  return {
    name: segment.name,
    description: segment.description ?? "",
    active: segment.active,
    rules:
      segment.rules.length === 0
        ? [{ field: DEFAULT_FIELD, operator: "equals", value: "" }]
        : segment.rules.map((rule) => ({
            field: rule.field,
            operator: rule.operator,
            value: stringifyRuleValue(rule.field, rule.value, tags)
          }))
  };
}

function stringifyRuleValue(field: CustomerSegmentField, value: unknown, tags: CustomerTag[]): string {
  if (field === "TAG" && typeof value === "string") {
    const matchingTag = tags.find((tag) => tag.name === value || tag.slug === value);
    return matchingTag?.name ?? value;
  }
  if (typeof value === "number") {
    return String(value);
  }
  if (typeof value === "string") {
    return value;
  }
  return "";
}

function buildUpsertInput(
  draft: SegmentDraft,
  overrides: Partial<Pick<CustomerSegmentUpsertInput, "active">> = {}
): CustomerSegmentUpsertInput {
  const name = draft.name.trim();
  const description = draft.description.trim();
  if (!name) {
    throw new Error("Segment name is required.");
  }
  if (draft.rules.length === 0) {
    throw new Error("At least one rule is required.");
  }

  const rules: CustomerSegmentRuleInput[] = draft.rules.map((rule, index) => ({
    field: rule.field,
    operator: rule.operator,
    sort_order: index,
    value: normalizeRuleValue(rule)
  }));

  return {
    name,
    description: description ? description : null,
    active: overrides.active ?? draft.active,
    rules
  };
}

function normalizeRuleValue(rule: SegmentDraftRule): unknown {
  const value = rule.value.trim();
  if (rule.field === "TAG" || rule.field === "CUSTOMER_STATUS" || rule.field === "CONVERSATION_STATUS") {
    if (!value) {
      throw new Error("Rule value is required.");
    }
    return rule.field === "TAG" ? value : value.toLowerCase();
  }
  if (rule.field === "LAST_ACTIVITY") {
    if (!value) {
      throw new Error("Rule value is required.");
    }
    return value;
  }
  if (!value) {
    throw new Error("Rule value is required.");
  }
  const parsed = Number(value);
  if (Number.isNaN(parsed)) {
    throw new Error("Numeric rules must use a number.");
  }
  return parsed;
}

function formatRule(field: CustomerSegmentField, operator: CustomerSegmentOperator, value: unknown): string {
  const label = FIELD_OPTIONS.find((item) => item.value === field)?.label ?? field;
  const operatorLabel =
    [...STATUS_OPERATOR_OPTIONS, ...DATE_OPERATOR_OPTIONS, ...NUMERIC_OPERATOR_OPTIONS].find(
      (item) => item.value === operator
    )?.label ?? operator;
  return `${label} ${operatorLabel} ${String(value)}`;
}

function formatTimestamp(value: string | null): string {
  if (!value) {
    return "Unknown time";
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}
