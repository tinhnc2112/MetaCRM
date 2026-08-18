import { SearchOutlined, ShoppingOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Alert, Select, Spin, Tag, Typography } from "antd";
import { useEffect, useMemo, useState } from "react";

import { listProducts } from "../services/productService";
import type { ProductListItem } from "../types/product";

const SEARCH_DELAY_MS = 300;

type ProductPickerProps = {
  inputId: string;
  currentPageId: string | null;
  orderCurrency: string;
  selectedProduct: ProductListItem | null;
  disabled: boolean;
  onSelect: (product: ProductListItem) => void;
};

export function ProductPicker({
  inputId,
  currentPageId,
  orderCurrency,
  selectedProduct,
  disabled,
  onSelect
}: ProductPickerProps) {
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [selectionError, setSelectionError] = useState<string | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => setSearch(searchInput.trim()), SEARCH_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [searchInput]);

  useEffect(() => {
    setSearchInput("");
    setSearch("");
    setSelectionError(null);
  }, [currentPageId]);

  useEffect(() => {
    setSelectionError(null);
  }, [orderCurrency]);

  const productsQuery = useQuery({
    queryKey: ["product-picker", currentPageId, search, true],
    queryFn: () =>
      listProducts({
        page: 1,
        pageSize: 20,
        q: search || undefined,
        active: true
      }),
    enabled: Boolean(currentPageId),
    refetchOnMount: "always"
  });

  const products = useMemo(() => {
    const results = productsQuery.data?.items ?? [];
    if (
      !selectedProduct ||
      search ||
      results.some((product) => product.uuid === selectedProduct.uuid)
    ) {
      return results;
    }
    return [selectedProduct, ...results];
  }, [productsQuery.data?.items, selectedProduct]);

  const normalizedOrderCurrency = orderCurrency.trim().toUpperCase();
  const selectedCurrencyMismatch = Boolean(
    selectedProduct &&
      normalizedOrderCurrency &&
      selectedProduct.currency.toUpperCase() !== normalizedOrderCurrency
  );

  if (!currentPageId) {
    return (
      <Alert
        type="info"
        showIcon
        message="Select a Facebook Page before searching Products."
      />
    );
  }

  return (
    <div className="product-picker">
      <label className="product-picker-label" htmlFor={inputId}>
        Catalog product
      </label>
      <Select
        id={inputId}
        aria-label="Search and select a catalog product"
        showSearch
        allowClear={false}
        filterOption={false}
        searchValue={searchInput}
        onSearch={setSearchInput}
        value={selectedProduct?.uuid}
        disabled={disabled}
        placeholder="Search active products by name or SKU"
        suffixIcon={<SearchOutlined />}
        loading={productsQuery.isFetching}
        notFoundContent={
          productsQuery.isFetching ? (
            <Spin size="small" />
          ) : productsQuery.isError ? (
            "Product search unavailable"
          ) : (
            "No active products found"
          )
        }
        options={products.map((product) => ({
          value: product.uuid,
          label: buildProductOptionLabel(product)
        }))}
        onChange={(productUuid) => {
          const product = products.find((item) => item.uuid === productUuid);
          if (!product) {
            return;
          }
          if (
            normalizedOrderCurrency &&
            product.currency.toUpperCase() !== normalizedOrderCurrency
          ) {
            setSelectionError(
              `This Product uses ${product.currency}; select a Product using ${normalizedOrderCurrency} or change the Order currency.`
            );
            return;
          }
          setSelectionError(null);
          setSearchInput("");
          onSelect(product);
        }}
      />

      {productsQuery.isError ? (
        <Alert
          type="warning"
          showIcon
          message="Product search is unavailable. You can switch this item to Manual."
        />
      ) : null}

      {selectionError ? <Alert type="warning" showIcon message={selectionError} /> : null}

      {selectedProduct ? (
        <div className="product-picker-selection">
          <div className="product-picker-selection-title">
            <ShoppingOutlined />
            <Typography.Text strong>{selectedProduct.name}</Typography.Text>
            <Tag color="success">Active</Tag>
          </div>
          <Typography.Text type="secondary">
            SKU: {selectedProduct.sku ?? "No SKU"} · Catalog price: {formatProductPrice(selectedProduct)}
          </Typography.Text>
        </div>
      ) : (
        <Typography.Text type="secondary">
          Search the current Page catalog, or switch this row to Manual.
        </Typography.Text>
      )}

      {selectedCurrencyMismatch ? (
        <Alert
          type="error"
          showIcon
          message={`Selected Product currency ${selectedProduct?.currency} does not match Order currency ${normalizedOrderCurrency}.`}
        />
      ) : null}
    </div>
  );
}

function buildProductOptionLabel(product: ProductListItem): string {
  const sku = product.sku ? ` · ${product.sku}` : " · No SKU";
  return `${product.name}${sku} · ${formatProductPrice(product)}`;
}

function formatProductPrice(product: ProductListItem): string {
  const value = Number(product.sale_price);
  const amount = Number.isFinite(value)
    ? value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : product.sale_price;
  return `${amount} ${product.currency}`;
}
