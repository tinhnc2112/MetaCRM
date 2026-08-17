import type { PaginationMeta } from "./messenger";
import type { CustomerProfileConversation } from "./customer";

export type CustomerSegmentField =
  | "TAG"
  | "CUSTOMER_STATUS"
  | "CONVERSATION_STATUS"
  | "LAST_ACTIVITY"
  | "ORDER_COUNT"
  | "TOTAL_SPENT";

export type CustomerSegmentOperator =
  | "equals"
  | "not_equals"
  | "contains"
  | "greater_than"
  | "less_than"
  | "greater_or_equal"
  | "less_or_equal"
  | "before"
  | "after";

export type CustomerSegmentRule = {
  id: number;
  field: CustomerSegmentField;
  operator: CustomerSegmentOperator;
  value: unknown;
  sort_order: number;
};

export type CustomerSegment = {
  id: number;
  name: string;
  description: string | null;
  active: boolean;
  created_by: number;
  created_at: string;
  updated_at: string;
  customer_count: number;
  rules: CustomerSegmentRule[];
};

export type CustomerSegmentListResponse = {
  items: CustomerSegment[];
};

export type CustomerSegmentCustomersResponse = {
  items: CustomerProfileConversation[];
  meta: PaginationMeta;
};

export type CustomerSegmentPreviewResponse = CustomerSegmentCustomersResponse;

export type CustomerSegmentRuleInput = {
  field: CustomerSegmentField;
  operator: CustomerSegmentOperator;
  value: unknown;
  sort_order?: number | null;
};

export type CustomerSegmentUpsertInput = {
  name: string;
  description: string | null;
  active: boolean;
  rules: CustomerSegmentRuleInput[];
};

export type CustomerSegmentDeleteResponse = {
  deleted: boolean;
  segment_id: number;
};
