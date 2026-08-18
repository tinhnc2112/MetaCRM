import {
  DatabaseOutlined,
  DeleteOutlined,
  EditOutlined,
  PlusOutlined,
  SearchOutlined,
  ShoppingOutlined
} from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Empty,
  Input,
  Modal,
  Pagination,
  Select,
  Space,
  Spin,
  Switch,
  Table,
  Tag,
  Typography
} from "antd";
import type { TableColumnsType } from "antd";
import { useEffect, useRef, useState } from "react";

import { ProductInventoryModal } from "../components/ProductInventoryModal";
import { getCurrentFacebookPage } from "../services/facebookService";
import {
  archiveProduct,
  createProduct,
  listProducts,
  updateProduct
} from "../services/productService";
import type {
  ProductCreatePayload,
  ProductListItem,
  ProductUpdatePayload
} from "../types/product";

const PAGE_SIZE = 20;
const MAX_MONEY = 9_999_999_999.99;

type ActiveFilter = "all" | "active" | "inactive";

type ProductDraft = {
  name: string;
  sku: string;
  currency: string;
  salePrice: string;
  description: string;
  isActive: boolean;
};

type CreateVariables = {
  pageId: string;
  payload: ProductCreatePayload;
};

type UpdateVariables = {
  pageId: string;
  productUuid: string;
  payload: ProductUpdatePayload;
};

type ArchiveVariables = {
  pageId: string;
  product: ProductListItem;
};

type InventorySelection = {
  pageId: string;
  product: ProductListItem;
};

export function ProductManagementPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [searchText, setSearchText] = useState("");
  const [query, setQuery] = useState("");
  const [activeFilter, setActiveFilter] = useState<ActiveFilter>("all");
  const [page, setPage] = useState(1);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingProduct, setEditingProduct] = useState<ProductListItem | null>(null);
  const [draft, setDraft] = useState<ProductDraft>(createEmptyDraft());
  const [formError, setFormError] = useState<string | null>(null);
  const [archiveTarget, setArchiveTarget] = useState<ProductListItem | null>(null);
  const [inventorySelection, setInventorySelection] = useState<InventorySelection | null>(null);

  const currentPageQuery = useQuery({
    queryKey: ["facebook-current-page"],
    queryFn: getCurrentFacebookPage
  });

  const currentPageId = currentPageQuery.data?.item?.page_id ?? null;
  const currentPageName = currentPageQuery.data?.item?.name ?? null;
  const currentPageIdRef = useRef<string | null>(currentPageId);
  currentPageIdRef.current = currentPageId;

  const active = activeFilter === "all" ? undefined : activeFilter === "active";
  const productsQuery = useQuery({
    queryKey: ["products", currentPageId, { page, pageSize: PAGE_SIZE, q: query, active }],
    queryFn: () =>
      listProducts({
        page,
        pageSize: PAGE_SIZE,
        q: query || undefined,
        active
      }),
    enabled: Boolean(currentPageId)
  });

  useEffect(() => {
    setPage(1);
    setEditorOpen(false);
    setEditingProduct(null);
    setDraft(createEmptyDraft());
    setFormError(null);
    setArchiveTarget(null);
    setInventorySelection(null);
  }, [currentPageId]);

  const createMutation = useMutation({
    mutationFn: ({ payload }: CreateVariables) => createProduct(payload),
    onSuccess: async (_, variables) => {
      await queryClient.invalidateQueries({ queryKey: ["products", variables.pageId] });
      if (currentPageIdRef.current !== variables.pageId) {
        return;
      }
      closeEditor();
      void message.success("Product created.");
    },
    onError: (error, variables) => {
      if (currentPageIdRef.current === variables.pageId) {
        setFormError(getReadableProductError(error, "Could not create the product."));
      }
    }
  });

  const updateMutation = useMutation({
    mutationFn: ({ productUuid, payload }: UpdateVariables) =>
      updateProduct(productUuid, payload),
    onSuccess: async (_, variables) => {
      await queryClient.invalidateQueries({ queryKey: ["products", variables.pageId] });
      if (currentPageIdRef.current !== variables.pageId) {
        return;
      }
      closeEditor();
      void message.success("Product updated.");
    },
    onError: (error, variables) => {
      if (currentPageIdRef.current === variables.pageId) {
        setFormError(getReadableProductError(error, "Could not update the product."));
      }
    }
  });

  const archiveMutation = useMutation({
    mutationFn: ({ product }: ArchiveVariables) => archiveProduct(product.uuid),
    onSuccess: async (_, variables) => {
      await queryClient.invalidateQueries({ queryKey: ["products", variables.pageId] });
      if (currentPageIdRef.current !== variables.pageId) {
        return;
      }
      if ((productsQuery.data?.items.length ?? 0) === 1 && page > 1) {
        setPage((current) => Math.max(1, current - 1));
      }
      setArchiveTarget(null);
      void message.success("Product archived.");
    },
    onError: (error, variables) => {
      if (currentPageIdRef.current === variables.pageId) {
        void message.error(getReadableProductError(error, "Could not archive the product."));
      }
    }
  });

  const products = productsQuery.data?.items ?? [];
  const pagination = productsQuery.data?.meta ?? null;
  const editorPending = createMutation.isPending || updateMutation.isPending;

  const openCreate = () => {
    setEditingProduct(null);
    setDraft(createEmptyDraft());
    setFormError(null);
    setEditorOpen(true);
  };

  const openEdit = (product: ProductListItem) => {
    setEditingProduct(product);
    setDraft({
      name: product.name,
      sku: product.sku ?? "",
      currency: product.currency,
      salePrice: product.sale_price,
      description: product.description ?? "",
      isActive: product.is_active
    });
    setFormError(null);
    setEditorOpen(true);
  };

  const closeEditor = () => {
    setEditorOpen(false);
    setEditingProduct(null);
    setDraft(createEmptyDraft());
    setFormError(null);
  };

  const handleSave = async () => {
    if (!currentPageId || editorPending) {
      return;
    }
    const validationError = validateDraft(draft);
    if (validationError) {
      setFormError(validationError);
      return;
    }

    setFormError(null);
    const normalized = normalizeDraft(draft);
    if (editingProduct) {
      const payload = buildUpdatePayload(editingProduct, normalized);
      if (Object.keys(payload).length === 0) {
        setFormError("No product changes to save.");
        return;
      }
      await updateMutation.mutateAsync({
        pageId: currentPageId,
        productUuid: editingProduct.uuid,
        payload
      }).catch(() => undefined);
      return;
    }

    await createMutation.mutateAsync({ pageId: currentPageId, payload: normalized }).catch(() => undefined);
  };

  const applySearch = (value = searchText) => {
    const normalized = value.trim();
    setSearchText(value);
    setQuery(normalized);
    setPage(1);
  };

  const columns: TableColumnsType<ProductListItem> = [
    {
      title: "Product",
      key: "product",
      render: (_, product) => (
        <div className="product-name-cell">
          <Typography.Text strong>{product.name}</Typography.Text>
          {product.description ? (
            <Typography.Text type="secondary" ellipsis={{ tooltip: product.description }}>
              {product.description}
            </Typography.Text>
          ) : null}
        </div>
      )
    },
    {
      title: "SKU",
      dataIndex: "sku",
      key: "sku",
      width: 180,
      render: (sku: string | null) => sku ?? <Typography.Text type="secondary">No SKU</Typography.Text>
    },
    {
      title: "Sale price",
      key: "sale_price",
      width: 180,
      render: (_, product) => formatMoney(product.sale_price, product.currency)
    },
    {
      title: "Status",
      dataIndex: "is_active",
      key: "is_active",
      width: 120,
      render: (isActive: boolean) => (
        <Tag color={isActive ? "success" : "default"}>{isActive ? "Active" : "Inactive"}</Tag>
      )
    },
    {
      title: "Inventory",
      dataIndex: "track_inventory",
      key: "track_inventory",
      width: 130,
      render: (trackInventory: boolean) => (
        <Tag color={trackInventory ? "success" : "default"}>
          {trackInventory ? "Tracked" : "Not tracked"}
        </Tag>
      )
    },
    {
      title: "Updated",
      dataIndex: "updated_at",
      key: "updated_at",
      width: 180,
      render: (updatedAt: string) => formatTimestamp(updatedAt)
    },
    {
      title: "Actions",
      key: "actions",
      width: 340,
      render: (_, product) => (
        <Space wrap>
          <Button
            icon={<DatabaseOutlined />}
            onClick={() => {
              if (currentPageId) {
                setInventorySelection({ pageId: currentPageId, product });
              }
            }}
          >
            Inventory
          </Button>
          <Button icon={<EditOutlined />} onClick={() => openEdit(product)}>
            Edit
          </Button>
          <Button
            danger
            icon={<DeleteOutlined />}
            disabled={archiveMutation.isPending}
            onClick={() => setArchiveTarget(product)}
          >
            Archive
          </Button>
        </Space>
      )
    }
  ];

  if (currentPageQuery.isLoading) {
    return (
      <div className="product-page-loading">
        <Spin />
      </div>
    );
  }

  if (currentPageQuery.isError) {
    return <Alert type="error" showIcon message="Could not load the current Facebook Page." />;
  }

  if (!currentPageId) {
    return (
      <Alert
        type="info"
        showIcon
        message="No Facebook Page selected"
        description="Open Facebook settings and select a page before managing products."
      />
    );
  }

  return (
    <div className="product-management-page">
      <div className="product-management-header">
        <div>
          <Typography.Title level={2}>Products</Typography.Title>
          <Typography.Text type="secondary">
            Manage the product catalog for the currently selected Facebook Page.
          </Typography.Text>
        </div>
        <Space wrap>
          <Tag color="blue" icon={<ShoppingOutlined />}>
            {pagination?.total ?? 0} products
          </Tag>
          {currentPageName ? <Tag>{currentPageName}</Tag> : null}
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            Create Product
          </Button>
        </Space>
      </div>

      <section className="product-management-section">
        <div className="product-management-toolbar">
          <Input.Search
            value={searchText}
            onChange={(event) => setSearchText(event.target.value)}
            onSearch={applySearch}
            allowClear
            enterButton={
              <Space>
                <SearchOutlined />
                Search
              </Space>
            }
            placeholder="Search by product name or SKU"
          />
          <Select<ActiveFilter>
            value={activeFilter}
            className="product-active-filter"
            aria-label="Filter products by active status"
            options={[
              { label: "All statuses", value: "all" },
              { label: "Active", value: "active" },
              { label: "Inactive", value: "inactive" }
            ]}
            onChange={(value) => {
              setActiveFilter(value);
              setPage(1);
            }}
          />
        </div>

        {productsQuery.isLoading ? (
          <div className="product-page-loading">
            <Spin />
          </div>
        ) : productsQuery.isError ? (
          <Alert
            type="error"
            showIcon
            message="Could not load products."
            description={getReadableProductError(productsQuery.error, "Check your connection and try again.")}
            action={<Button onClick={() => void productsQuery.refetch()}>Retry</Button>}
          />
        ) : products.length === 0 ? (
          <Empty
            description={
              query || activeFilter !== "all"
                ? "No products match the current search and filter"
                : "No products yet"
            }
          >
            {!query && activeFilter === "all" ? (
              <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
                Create Product
              </Button>
            ) : null}
          </Empty>
        ) : (
          <>
            <Table<ProductListItem>
              rowKey="uuid"
              columns={columns}
              dataSource={products}
              pagination={false}
              scroll={{ x: 980 }}
            />
            {pagination ? (
              <div className="product-management-pagination">
                <Typography.Text type="secondary">
                  Page {pagination.page} · {pagination.total} total
                </Typography.Text>
                <Pagination
                  current={pagination.page}
                  pageSize={pagination.page_size}
                  total={pagination.total}
                  showSizeChanger={false}
                  onChange={setPage}
                />
              </div>
            ) : null}
          </>
        )}
      </section>

      <Modal
        title={editingProduct ? "Edit Product" : "Create Product"}
        open={editorOpen}
        okText={editingProduct ? "Save Changes" : "Create Product"}
        confirmLoading={editorPending}
        closable={!editorPending}
        maskClosable={!editorPending}
        keyboard={!editorPending}
        onOk={() => void handleSave()}
        onCancel={() => {
          if (!editorPending) {
            closeEditor();
          }
        }}
        destroyOnClose
      >
        <div className="product-editor-form">
          {formError ? <Alert type="error" showIcon message={formError} /> : null}
          <label className="product-form-field">
            <span>Name *</span>
            <Input
              value={draft.name}
              maxLength={255}
              autoFocus
              disabled={editorPending}
              onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))}
              placeholder="Product name"
            />
          </label>
          <label className="product-form-field">
            <span>SKU</span>
            <Input
              value={draft.sku}
              maxLength={255}
              disabled={editorPending}
              onChange={(event) => setDraft((current) => ({ ...current, sku: event.target.value }))}
              placeholder="Optional; unique within this Page"
            />
          </label>
          <div className="product-form-row">
            <label className="product-form-field">
              <span>Currency *</span>
              <Input
                value={draft.currency}
                maxLength={8}
                disabled={editorPending}
                onChange={(event) =>
                  setDraft((current) => ({ ...current, currency: event.target.value.toUpperCase() }))
                }
                placeholder="VND"
              />
            </label>
            <label className="product-form-field">
              <span>Sale price *</span>
              <Input
                value={draft.salePrice}
                inputMode="decimal"
                disabled={editorPending}
                onChange={(event) => setDraft((current) => ({ ...current, salePrice: event.target.value }))}
                placeholder="0.00"
              />
            </label>
          </div>
          <label className="product-form-field">
            <span>Description</span>
            <Input.TextArea
              value={draft.description}
              rows={4}
              disabled={editorPending}
              onChange={(event) =>
                setDraft((current) => ({ ...current, description: event.target.value }))
              }
              placeholder="Optional product description"
            />
          </label>
          <div className="product-active-field">
            <div>
              <Typography.Text strong>Active</Typography.Text>
              <Typography.Paragraph type="secondary">
                Inactive products remain manageable but cannot be selected for new product-backed orders.
              </Typography.Paragraph>
            </div>
            <Switch
              checked={draft.isActive}
              disabled={editorPending}
              onChange={(checked) => setDraft((current) => ({ ...current, isActive: checked }))}
            />
          </div>
        </div>
      </Modal>

      <Modal
        title="Archive Product"
        open={archiveTarget !== null}
        okText="Archive"
        okButtonProps={{ danger: true }}
        confirmLoading={archiveMutation.isPending}
        closable={!archiveMutation.isPending}
        maskClosable={!archiveMutation.isPending}
        keyboard={!archiveMutation.isPending}
        onCancel={() => {
          if (!archiveMutation.isPending) {
            setArchiveTarget(null);
          }
        }}
        onOk={() => {
          if (!archiveTarget || !currentPageId || archiveMutation.isPending) {
            return;
          }
          archiveMutation.mutate({ pageId: currentPageId, product: archiveTarget });
        }}
      >
        <Typography.Paragraph>
          Archive <Typography.Text strong>{archiveTarget?.name}</Typography.Text>?
        </Typography.Paragraph>
        <Typography.Paragraph type="secondary">
          The product will be hidden from normal product lists. Existing order history and item snapshots will remain unchanged.
        </Typography.Paragraph>
      </Modal>

      <ProductInventoryModal
        product={inventorySelection?.product ?? null}
        currentPageId={inventorySelection?.pageId ?? null}
        open={
          inventorySelection !== null && inventorySelection.pageId === currentPageId
        }
        onClose={() => setInventorySelection(null)}
      />
    </div>
  );
}

function createEmptyDraft(): ProductDraft {
  return {
    name: "",
    sku: "",
    currency: "VND",
    salePrice: "",
    description: "",
    isActive: true
  };
}

function validateDraft(draft: ProductDraft): string | null {
  if (!draft.name.trim()) {
    return "Product name is required.";
  }
  if (draft.name.trim().length > 255) {
    return "Product name must be 255 characters or fewer.";
  }
  if (draft.sku.trim().length > 255) {
    return "SKU must be 255 characters or fewer.";
  }
  const currency = draft.currency.trim();
  if (!currency) {
    return "Currency is required.";
  }
  if (currency.length > 8) {
    return "Currency must be 8 characters or fewer.";
  }
  const priceText = draft.salePrice.trim();
  if (!priceText) {
    return "Sale price is required.";
  }
  const price = Number(priceText);
  if (!Number.isFinite(price)) {
    return "Sale price must be a finite number.";
  }
  if (price < 0) {
    return "Sale price cannot be negative.";
  }
  if (price > MAX_MONEY) {
    return "Sale price cannot exceed 9,999,999,999.99.";
  }
  return null;
}

function normalizeDraft(draft: ProductDraft): ProductCreatePayload {
  return {
    name: draft.name.trim(),
    sku: normaliseOptionalText(draft.sku),
    currency: draft.currency.trim().toUpperCase(),
    sale_price: draft.salePrice.trim(),
    description: normaliseOptionalText(draft.description),
    is_active: draft.isActive
  };
}

function buildUpdatePayload(
  product: ProductListItem,
  normalized: ProductCreatePayload
): ProductUpdatePayload {
  const payload: ProductUpdatePayload = {};
  if (normalized.name !== product.name) {
    payload.name = normalized.name;
  }
  if (normalized.sku !== product.sku) {
    payload.sku = normalized.sku;
  }
  if (normalized.currency !== product.currency) {
    payload.currency = normalized.currency;
  }
  if (!moneyValuesEqual(normalized.sale_price, product.sale_price)) {
    payload.sale_price = normalized.sale_price;
  }
  if (normalized.description !== product.description) {
    payload.description = normalized.description;
  }
  if (normalized.is_active !== product.is_active) {
    payload.is_active = normalized.is_active;
  }
  return payload;
}

function normaliseOptionalText(value: string): string | null {
  const trimmed = value.trim();
  return trimmed || null;
}

function moneyValuesEqual(first: string, second: string): boolean {
  const firstNumber = Number(first);
  const secondNumber = Number(second);
  return Number.isFinite(firstNumber) && Number.isFinite(secondNumber) && firstNumber === secondNumber;
}

function formatMoney(value: string, currency: string): string {
  const amount = Number(value);
  if (!Number.isFinite(amount)) {
    return `${value} ${currency}`.trim();
  }
  return `${amount.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  })} ${currency}`.trim();
}

function formatTimestamp(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function getReadableProductError(error: unknown, fallback: string): string {
  if (typeof error === "object" && error !== null && "response" in error) {
    const response = (error as {
      response?: { status?: number; data?: { detail?: unknown } };
    }).response;
    const detail = response?.data?.detail;
    if (typeof detail === "string") {
      return detail;
    }
    if (Array.isArray(detail)) {
      return "Some product fields are invalid. Please review the form and try again.";
    }
    if (response?.status === 401) {
      return "Your session has expired. Sign in and try again.";
    }
    if (response?.status === 404) {
      return "The product was not found for the current Facebook Page.";
    }
    if (response?.status === 409) {
      return "That SKU is already used by another product on this Facebook Page.";
    }
    if (response?.status === 422) {
      return "Some product fields are invalid. Please review the form and try again.";
    }
  }
  return fallback;
}
