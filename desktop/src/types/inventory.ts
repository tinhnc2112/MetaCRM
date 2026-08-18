import type { PaginationMeta } from "./messenger";

export type InventoryState = {
  product_uuid: string;
  track_inventory: boolean;
  inventory_exists: boolean;
  quantity_on_hand: number | null;
  tracking_started_at: string | null;
  updated_at: string | null;
};

export type InventoryEnablePayload = {
  opening_quantity: number;
  note?: string | null;
};

export type InventoryAdjustmentPayload = {
  quantity_delta: number;
  note: string;
  idempotency_key: string;
};

export type StockMovementType =
  | "OPENING"
  | "ADJUSTMENT"
  | "ORDER_OUT"
  | "ORDER_CANCEL_RESTORE";

export type StockMovement = {
  uuid: string;
  movement_type: StockMovementType;
  quantity_delta: number;
  quantity_before: number;
  quantity_after: number;
  note: string | null;
  created_at: string;
};

export type StockMovementListParams = {
  page?: number;
  pageSize?: number;
  movementType?: StockMovementType;
};

export type StockMovementListResponse = {
  items: StockMovement[];
  meta: PaginationMeta;
};
