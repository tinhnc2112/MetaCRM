import {
  DatabaseOutlined,
  MinusOutlined,
  PlusOutlined,
  ReloadOutlined
} from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App as AntApp,
  Button,
  Descriptions,
  Empty,
  Input,
  Modal,
  Pagination,
  Radio,
  Space,
  Spin,
  Table,
  Tag,
  Typography
} from "antd";
import type { TableColumnsType } from "antd";
import { useEffect, useRef, useState } from "react";

import {
  adjustProductInventory,
  disableProductInventory,
  enableProductInventory,
  getProductInventory,
  listProductInventoryMovements
} from "../services/inventoryService";
import type {
  InventoryAdjustmentPayload,
  InventoryEnablePayload,
  StockMovement,
  StockMovementType
} from "../types/inventory";
import type { ProductListItem } from "../types/product";

const MOVEMENT_PAGE_SIZE = 20;
const MAX_NOTE_LENGTH = 5000;

type AdjustmentKind = "add" | "remove";

type InventoryMutationContext = {
  pageId: string;
  productUuid: string;
};

type EnableVariables = InventoryMutationContext & {
  payload: InventoryEnablePayload;
  reenable: boolean;
};

type AdjustmentVariables = InventoryMutationContext & {
  payload: InventoryAdjustmentPayload;
};

type AdjustmentOperation = {
  fingerprint: string;
  idempotencyKey: string;
};

type ProductInventoryModalProps = {
  product: ProductListItem | null;
  currentPageId: string | null;
  open: boolean;
  onClose: () => void;
};

export function ProductInventoryModal({
  product,
  currentPageId,
  open,
  onClose
}: ProductInventoryModalProps) {
  const { message, modal } = AntApp.useApp();
  const queryClient = useQueryClient();
  const [openingQuantity, setOpeningQuantity] = useState("0");
  const [openingNote, setOpeningNote] = useState("");
  const [adjustmentKind, setAdjustmentKind] = useState<AdjustmentKind>("add");
  const [adjustmentQuantity, setAdjustmentQuantity] = useState("");
  const [adjustmentNote, setAdjustmentNote] = useState("");
  const [movementPage, setMovementPage] = useState(1);
  const [actionError, setActionError] = useState<string | null>(null);
  const operationRef = useRef<AdjustmentOperation | null>(null);
  const disableConfirmationRef = useRef<{ destroy: () => void } | null>(null);
  const enableSubmittingRef = useRef(false);
  const disableSubmittingRef = useRef(false);
  const adjustmentSubmittingRef = useRef(false);
  const currentPageIdRef = useRef(currentPageId);
  const productUuidRef = useRef(product?.uuid ?? null);
  const openRef = useRef(open);

  currentPageIdRef.current = currentPageId;
  productUuidRef.current = product?.uuid ?? null;
  openRef.current = open;

  const productUuid = product?.uuid ?? "";
  const inventoryQuery = useQuery({
    queryKey: ["inventory", currentPageId, productUuid],
    queryFn: () => getProductInventory(productUuid),
    enabled: Boolean(open && currentPageId && productUuid),
    refetchOnMount: "always"
  });

  const movementsQuery = useQuery({
    queryKey: [
      "inventory-movements",
      currentPageId,
      productUuid,
      { page: movementPage, pageSize: MOVEMENT_PAGE_SIZE, movementType: undefined }
    ],
    queryFn: () =>
      listProductInventoryMovements(productUuid, {
        page: movementPage,
        pageSize: MOVEMENT_PAGE_SIZE
      }),
    enabled: Boolean(
      open && currentPageId && productUuid && inventoryQuery.data?.inventory_exists
    ),
    refetchOnMount: "always"
  });

  useEffect(() => {
    resetForms();
  }, [currentPageId, productUuid, open]);

  const invalidateInventory = async ({ pageId, productUuid: originUuid }: InventoryMutationContext) => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["inventory", pageId, originUuid] }),
      queryClient.invalidateQueries({
        queryKey: ["inventory-movements", pageId, originUuid]
      })
    ]);
  };

  const isActiveContext = ({ pageId, productUuid: originUuid }: InventoryMutationContext) =>
    openRef.current &&
    currentPageIdRef.current === pageId &&
    productUuidRef.current === originUuid;

  const enableMutation = useMutation({
    mutationFn: ({ productUuid: originUuid, payload }: EnableVariables) =>
      enableProductInventory(originUuid, payload),
    retry: false,
    onSuccess: async (_, variables) => {
      await Promise.all([
        invalidateInventory(variables),
        queryClient.invalidateQueries({ queryKey: ["products", variables.pageId] })
      ]);
      if (!isActiveContext(variables)) {
        return;
      }
      setOpeningQuantity("0");
      setOpeningNote("");
      setActionError(null);
      void message.success(
        variables.reenable ? "Inventory tracking re-enabled." : "Inventory enabled."
      );
    },
    onError: (error, variables) => {
      if (isActiveContext(variables)) {
        setActionError(getReadableInventoryError(error, "Could not enable inventory."));
      }
    }
  });

  const disableMutation = useMutation({
    mutationFn: ({ productUuid: originUuid }: InventoryMutationContext) =>
      disableProductInventory(originUuid),
    retry: false,
    onSuccess: async (_, variables) => {
      await Promise.all([
        invalidateInventory(variables),
        queryClient.invalidateQueries({ queryKey: ["products", variables.pageId] })
      ]);
      if (!isActiveContext(variables)) {
        return;
      }
      setActionError(null);
      void message.success("Inventory tracking disabled.");
    },
    onError: (error, variables) => {
      if (isActiveContext(variables)) {
        setActionError(getReadableInventoryError(error, "Could not disable inventory tracking."));
      }
    }
  });

  const adjustmentMutation = useMutation({
    mutationFn: ({ productUuid: originUuid, payload }: AdjustmentVariables) =>
      adjustProductInventory(originUuid, payload),
    retry: false,
    onSuccess: async (_, variables) => {
      await invalidateInventory(variables);
      if (!isActiveContext(variables)) {
        return;
      }
      setAdjustmentQuantity("");
      setAdjustmentNote("");
      operationRef.current = null;
      setActionError(null);
      setMovementPage(1);
      void message.success("Stock adjusted.");
    },
    onError: async (error, variables) => {
      if (getHttpStatus(error) === 409) {
        await queryClient.invalidateQueries({
          queryKey: ["inventory", variables.pageId, variables.productUuid]
        });
      }
      if (isActiveContext(variables)) {
        setActionError(getReadableInventoryError(error, "Could not adjust stock."));
      }
    }
  });

  const pending =
    enableMutation.isPending || disableMutation.isPending || adjustmentMutation.isPending;
  const inventory = inventoryQuery.data;
  const quantityOnHand = inventory?.quantity_on_hand ?? null;
  const balanceOutsideSafeRange =
    quantityOnHand !== null && !Number.isSafeInteger(quantityOnHand);

  const updateAdjustmentKind = (value: AdjustmentKind) => {
    setAdjustmentKind(value);
    operationRef.current = null;
    setActionError(null);
  };

  const updateAdjustmentQuantity = (value: string) => {
    setAdjustmentQuantity(value);
    operationRef.current = null;
    setActionError(null);
  };

  const updateAdjustmentNote = (value: string) => {
    setAdjustmentNote(value);
    operationRef.current = null;
    setActionError(null);
  };

  const submitEnable = async (reenable: boolean) => {
    if (!currentPageId || !product || enableSubmittingRef.current || enableMutation.isPending) {
      return;
    }

    let opening = 0;
    let note: string | null = null;
    if (!reenable) {
      const validation = validateOpeningBalance(openingQuantity, openingNote);
      if (validation.error) {
        setActionError(validation.error);
        return;
      }
      opening = validation.quantity;
      note = validation.note;
    }

    const variables: EnableVariables = {
      pageId: currentPageId,
      productUuid: product.uuid,
      payload: { opening_quantity: opening, note },
      reenable
    };
    setActionError(null);
    enableSubmittingRef.current = true;
    try {
      await enableMutation.mutateAsync(variables);
    } catch {
      // The mutation callback renders the error for the still-active Product context.
    } finally {
      enableSubmittingRef.current = false;
    }
  };

  const confirmDisable = () => {
    if (!currentPageId || !product || disableSubmittingRef.current || disableMutation.isPending) {
      return;
    }
    const variables: InventoryMutationContext = {
      pageId: currentPageId,
      productUuid: product.uuid
    };
    disableConfirmationRef.current = modal.confirm({
      title: "Disable inventory tracking?",
      content:
        "Current stock and movement history will be retained. New order confirmations will not consume stock while tracking is disabled.",
      okText: "Disable tracking",
      cancelText: "Keep enabled",
      okButtonProps: { danger: true },
      afterClose: () => {
        disableConfirmationRef.current = null;
      },
      onOk: async () => {
        if (disableSubmittingRef.current) {
          return;
        }
        disableSubmittingRef.current = true;
        setActionError(null);
        try {
          await disableMutation.mutateAsync(variables);
        } catch {
          // The mutation callback renders the error for the still-active Product context.
        } finally {
          disableSubmittingRef.current = false;
        }
      }
    });
  };

  const submitAdjustment = async () => {
    if (
      !currentPageId ||
      !product ||
      adjustmentSubmittingRef.current ||
      adjustmentMutation.isPending
    ) {
      return;
    }
    const validation = validateAdjustment(
      adjustmentKind,
      adjustmentQuantity,
      adjustmentNote
    );
    if (validation.error) {
      setActionError(validation.error);
      return;
    }

    const fingerprint = JSON.stringify({
      quantityDelta: validation.quantityDelta,
      note: validation.note
    });
    if (!operationRef.current || operationRef.current.fingerprint !== fingerprint) {
      operationRef.current = {
        fingerprint,
        idempotencyKey: crypto.randomUUID()
      };
    }

    const variables: AdjustmentVariables = {
      pageId: currentPageId,
      productUuid: product.uuid,
      payload: {
        quantity_delta: validation.quantityDelta,
        note: validation.note,
        idempotency_key: operationRef.current.idempotencyKey
      }
    };
    setActionError(null);
    adjustmentSubmittingRef.current = true;
    try {
      await adjustmentMutation.mutateAsync(variables);
    } catch {
      // Keep the exact operation UUID and form values for an explicit retry.
    } finally {
      adjustmentSubmittingRef.current = false;
    }
  };

  const movementColumns: TableColumnsType<StockMovement> = [
    {
      title: "Time",
      dataIndex: "created_at",
      key: "created_at",
      width: 180,
      render: (createdAt: string) => formatTimestamp(createdAt)
    },
    {
      title: "Type",
      dataIndex: "movement_type",
      key: "movement_type",
      width: 180,
      render: (movementType: StockMovementType) => movementTypeLabel(movementType)
    },
    {
      title: "Delta",
      dataIndex: "quantity_delta",
      key: "quantity_delta",
      width: 100,
      render: (delta: number) => (
        <Typography.Text type={delta < 0 ? "danger" : "success"} strong>
          {formatDelta(delta)}
        </Typography.Text>
      )
    },
    {
      title: "Before → After",
      key: "balance",
      width: 170,
      render: (_, movement) =>
        `${formatQuantity(movement.quantity_before)} → ${formatQuantity(movement.quantity_after)}`
    },
    {
      title: "Note",
      dataIndex: "note",
      key: "note",
      render: (note: string | null) => note ?? <Typography.Text type="secondary">—</Typography.Text>
    }
  ];

  return (
    <Modal
      title={
        <Space>
          <DatabaseOutlined />
          <span>Inventory · {product?.name ?? "Product"}</span>
        </Space>
      }
      open={open && product !== null}
      width={960}
      footer={null}
      closable={!pending}
      maskClosable={!pending}
      keyboard={!pending}
      onCancel={() => {
        if (!pending) {
          onClose();
        }
      }}
      destroyOnClose
    >
      <div className="product-inventory-modal">
        <Typography.Text type="secondary">
          {product?.sku ? `SKU ${product.sku}` : "No SKU"}
        </Typography.Text>

        {inventoryQuery.isLoading ? (
          <div className="inventory-loading">
            <Spin />
          </div>
        ) : inventoryQuery.isError ? (
          <Alert
            type="error"
            showIcon
            message="Could not load inventory."
            description={getReadableInventoryError(
              inventoryQuery.error,
              "Check your connection and try again."
            )}
            action={
              <Button icon={<ReloadOutlined />} onClick={() => void inventoryQuery.refetch()}>
                Retry
              </Button>
            }
          />
        ) : inventory ? (
          <>
            <Descriptions className="inventory-summary" bordered size="small" column={2}>
              <Descriptions.Item label="Tracking">
                <Tag color={inventory.track_inventory ? "success" : inventory.inventory_exists ? "warning" : "default"}>
                  {inventory.track_inventory
                    ? "Enabled"
                    : inventory.inventory_exists
                      ? "Disabled"
                      : "Never enabled"}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label={inventory.track_inventory ? "On hand" : "Retained balance"}>
                {inventory.quantity_on_hand === null
                  ? "Not available"
                  : formatQuantity(inventory.quantity_on_hand)}
              </Descriptions.Item>
              <Descriptions.Item label="Tracking started">
                {formatOptionalTimestamp(inventory.tracking_started_at)}
              </Descriptions.Item>
              <Descriptions.Item label="Last updated">
                {formatOptionalTimestamp(inventory.updated_at)}
              </Descriptions.Item>
            </Descriptions>

            {actionError ? <Alert type="error" showIcon message={actionError} /> : null}

            {balanceOutsideSafeRange ? (
              <Alert
                type="error"
                showIcon
                message="This balance is outside JavaScript's safe integer range."
                description="The desktop UI cannot display or adjust it reliably. Use a backend-safe reconciliation workflow."
              />
            ) : null}

            {!inventory.inventory_exists ? (
              <section className="inventory-action-card" aria-labelledby="enable-inventory-heading">
                <div>
                  <Typography.Title level={5} id="enable-inventory-heading">
                    Enable inventory
                  </Typography.Title>
                  <Typography.Text type="secondary">
                    Set the opening stock. Zero is valid.
                  </Typography.Text>
                </div>
                <div className="inventory-form-grid">
                  <label className="product-form-field">
                    <span>Opening quantity *</span>
                    <Input
                      value={openingQuantity}
                      inputMode="numeric"
                      maxLength={16}
                      disabled={enableMutation.isPending}
                      onChange={(event) => {
                        setOpeningQuantity(event.target.value);
                        setActionError(null);
                      }}
                      placeholder="0"
                    />
                  </label>
                  <label className="product-form-field inventory-note-field">
                    <span>Note</span>
                    <Input
                      value={openingNote}
                      maxLength={MAX_NOTE_LENGTH}
                      disabled={enableMutation.isPending}
                      onChange={(event) => {
                        setOpeningNote(event.target.value);
                        setActionError(null);
                      }}
                      placeholder="Optional opening balance note"
                    />
                  </label>
                </div>
                <Button
                  type="primary"
                  icon={<DatabaseOutlined />}
                  loading={enableMutation.isPending}
                  disabled={pending}
                  onClick={() => void submitEnable(false)}
                >
                  Enable inventory
                </Button>
              </section>
            ) : (
              <>
                {!inventory.track_inventory ? (
                  <Alert
                    type="warning"
                    showIcon
                    message="Inventory tracking is disabled"
                    description="The retained balance and movement history remain available. Adjustments reconcile the balance without enabling order tracking."
                    action={
                      <Button
                        type="primary"
                        loading={enableMutation.isPending}
                        disabled={pending}
                        onClick={() => void submitEnable(true)}
                      >
                        Re-enable with retained balance
                      </Button>
                    }
                  />
                ) : null}

                <section className="inventory-action-card" aria-labelledby="adjust-inventory-heading">
                  <div className="inventory-action-heading">
                    <div>
                      <Typography.Title level={5} id="adjust-inventory-heading">
                        {inventory.track_inventory ? "Adjust stock" : "Adjust / reconcile balance"}
                      </Typography.Title>
                      <Typography.Text type="secondary">
                        The backend validates and records every adjustment as an immutable movement.
                      </Typography.Text>
                    </div>
                    {inventory.track_inventory ? (
                      <Button danger disabled={pending} onClick={confirmDisable}>
                        Disable tracking
                      </Button>
                    ) : null}
                  </div>

                  <Radio.Group
                    value={adjustmentKind}
                    disabled={adjustmentMutation.isPending}
                    onChange={(event) => updateAdjustmentKind(event.target.value as AdjustmentKind)}
                  >
                    <Radio.Button value="add">
                      <PlusOutlined /> Add stock
                    </Radio.Button>
                    <Radio.Button value="remove">
                      <MinusOutlined /> Remove stock
                    </Radio.Button>
                  </Radio.Group>

                  <div className="inventory-form-grid">
                    <label className="product-form-field">
                      <span>Quantity *</span>
                      <Input
                        value={adjustmentQuantity}
                        inputMode="numeric"
                        maxLength={16}
                        disabled={adjustmentMutation.isPending}
                        onChange={(event) => updateAdjustmentQuantity(event.target.value)}
                        placeholder="Whole number greater than 0"
                      />
                    </label>
                    <label className="product-form-field inventory-note-field">
                      <span>Note *</span>
                      <Input
                        value={adjustmentNote}
                        maxLength={MAX_NOTE_LENGTH}
                        disabled={adjustmentMutation.isPending}
                        onChange={(event) => updateAdjustmentNote(event.target.value)}
                        placeholder="Reason for this adjustment"
                      />
                    </label>
                  </div>

                  <AdjustmentPreview
                    quantityOnHand={quantityOnHand}
                    kind={adjustmentKind}
                    quantityText={adjustmentQuantity}
                  />

                  <Button
                    type="primary"
                    loading={adjustmentMutation.isPending}
                    disabled={pending || balanceOutsideSafeRange}
                    onClick={() => void submitAdjustment()}
                  >
                    Apply adjustment
                  </Button>
                </section>
              </>
            )}

            <section className="inventory-history" aria-labelledby="inventory-history-heading">
              <div className="inventory-action-heading">
                <div>
                  <Typography.Title level={5} id="inventory-history-heading">
                    Movement history
                  </Typography.Title>
                  <Typography.Text type="secondary">
                    Includes manual changes and automatic Order movements. Entries cannot be edited or deleted.
                  </Typography.Text>
                </div>
                {inventory.inventory_exists ? (
                  <Button
                    icon={<ReloadOutlined />}
                    loading={movementsQuery.isFetching}
                    onClick={() => void movementsQuery.refetch()}
                  >
                    Refresh
                  </Button>
                ) : null}
              </div>

              {!inventory.inventory_exists ? (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No movement history. Enable inventory to create an opening movement." />
              ) : movementsQuery.isLoading ? (
                <div className="inventory-loading">
                  <Spin />
                </div>
              ) : movementsQuery.isError ? (
                <Alert
                  type="error"
                  showIcon
                  message="Could not load movement history."
                  description={getReadableInventoryError(
                    movementsQuery.error,
                    "Check your connection and try again."
                  )}
                  action={<Button onClick={() => void movementsQuery.refetch()}>Retry</Button>}
                />
              ) : (movementsQuery.data?.items.length ?? 0) === 0 ? (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No inventory movements found." />
              ) : (
                <>
                  <Table<StockMovement>
                    rowKey="uuid"
                    columns={movementColumns}
                    dataSource={movementsQuery.data?.items ?? []}
                    pagination={false}
                    size="small"
                    scroll={{ x: 780 }}
                  />
                  {movementsQuery.data?.meta ? (
                    <div className="inventory-history-pagination">
                      <Typography.Text type="secondary">
                        Page {movementsQuery.data.meta.page} · {movementsQuery.data.meta.total} movements
                      </Typography.Text>
                      <Pagination
                        current={movementsQuery.data.meta.page}
                        pageSize={movementsQuery.data.meta.page_size}
                        total={movementsQuery.data.meta.total}
                        showSizeChanger={false}
                        onChange={setMovementPage}
                      />
                    </div>
                  ) : null}
                </>
              )}
            </section>
          </>
        ) : null}
      </div>
    </Modal>
  );

  function resetForms() {
    setOpeningQuantity("0");
    setOpeningNote("");
    setAdjustmentKind("add");
    setAdjustmentQuantity("");
    setAdjustmentNote("");
    setMovementPage(1);
    setActionError(null);
    operationRef.current = null;
    disableConfirmationRef.current?.destroy();
    disableConfirmationRef.current = null;
    enableSubmittingRef.current = false;
    disableSubmittingRef.current = false;
    adjustmentSubmittingRef.current = false;
  }
}

function AdjustmentPreview({
  quantityOnHand,
  kind,
  quantityText
}: {
  quantityOnHand: number | null;
  kind: AdjustmentKind;
  quantityText: string;
}) {
  const parsed = parseSafeWholeNumber(quantityText, false);
  if (quantityOnHand === null || parsed === null || !Number.isSafeInteger(quantityOnHand)) {
    return null;
  }
  const projected = quantityOnHand + (kind === "add" ? parsed : -parsed);
  if (!Number.isSafeInteger(projected)) {
    return null;
  }
  return (
    <Typography.Text type={projected < 0 ? "danger" : "secondary"}>
      Current {formatQuantity(quantityOnHand)} · Projected {formatQuantity(projected)}
      {projected < 0 ? " — the backend will reject negative stock." : ""}
    </Typography.Text>
  );
}

function validateOpeningBalance(
  quantityText: string,
  noteText: string
): { error: string | null; quantity: number; note: string | null } {
  const quantity = parseSafeWholeNumber(quantityText, true);
  if (quantity === null) {
    return {
      error: "Opening quantity must be a whole number from 0 to JavaScript's safe integer limit.",
      quantity: 0,
      note: null
    };
  }
  const note = noteText.trim();
  if (note.length > MAX_NOTE_LENGTH) {
    return { error: "Note must be 5,000 characters or fewer.", quantity, note: null };
  }
  return { error: null, quantity, note: note || null };
}

function validateAdjustment(
  kind: AdjustmentKind,
  quantityText: string,
  noteText: string
): { error: string | null; quantityDelta: number; note: string } {
  const quantity = parseSafeWholeNumber(quantityText, false);
  if (quantity === null) {
    return {
      error: "Adjustment quantity must be a whole number greater than 0 and within JavaScript's safe integer limit.",
      quantityDelta: 0,
      note: ""
    };
  }
  const note = noteText.trim();
  if (!note) {
    return { error: "Adjustment note is required.", quantityDelta: 0, note: "" };
  }
  if (note.length > MAX_NOTE_LENGTH) {
    return { error: "Adjustment note must be 5,000 characters or fewer.", quantityDelta: 0, note: "" };
  }
  return {
    error: null,
    quantityDelta: kind === "add" ? quantity : -quantity,
    note
  };
}

function parseSafeWholeNumber(value: string, allowZero: boolean): number | null {
  const normalized = value.trim();
  if (!/^\d+$/.test(normalized)) {
    return null;
  }
  const parsed = Number(normalized);
  if (!Number.isSafeInteger(parsed) || parsed < 0 || (!allowZero && parsed === 0)) {
    return null;
  }
  return parsed;
}

function getHttpStatus(error: unknown): number | undefined {
  if (typeof error !== "object" || error === null || !("response" in error)) {
    return undefined;
  }
  return (error as { response?: { status?: number } }).response?.status;
}

function getReadableInventoryError(error: unknown, fallback: string): string {
  if (typeof error === "object" && error !== null && "response" in error) {
    const response = (error as {
      response?: { status?: number; data?: { detail?: unknown } };
    }).response;
    const detail = response?.data?.detail;
    if (response?.status === 401) {
      return "Your session has expired. Sign in and try again.";
    }
    if (response?.status === 404) {
      return "This Product is unavailable, archived, or does not belong to the current Facebook Page.";
    }
    if (response?.status === 409) {
      if (typeof detail === "string" && detail.toLowerCase().includes("negative")) {
        return "Not enough stock. Inventory may have changed; refresh and try again.";
      }
      if (typeof detail === "string" && detail.toLowerCase().includes("idempotency")) {
        return "This adjustment operation conflicts with an earlier request. Review the form before starting a new adjustment.";
      }
      return typeof detail === "string"
        ? detail
        : "Inventory changed or conflicts with this request. Refresh and try again.";
    }
    if (response?.status === 422) {
      return "Some inventory fields are invalid. Review the form and try again.";
    }
    if (typeof detail === "string") {
      return detail;
    }
  }
  return fallback;
}

function movementTypeLabel(type: StockMovementType): string {
  const labels: Record<StockMovementType, string> = {
    OPENING: "Opening balance",
    ADJUSTMENT: "Manual adjustment",
    ORDER_OUT: "Order confirmed",
    ORDER_CANCEL_RESTORE: "Order cancellation restore"
  };
  return labels[type] ?? type;
}

function formatQuantity(value: number): string {
  if (!Number.isSafeInteger(value)) {
    return "Outside safe integer range";
  }
  return value.toLocaleString(undefined, { maximumFractionDigits: 0 });
}

function formatDelta(value: number): string {
  const quantity = formatQuantity(value);
  return value > 0 ? `+${quantity}` : quantity;
}

function formatTimestamp(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function formatOptionalTimestamp(value: string | null): string {
  return value ? formatTimestamp(value) : "Not available";
}
