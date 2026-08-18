import type { PaginationMeta } from "./messenger";

export type Product = {
  uuid: string;
  name: string;
  sku: string | null;
  currency: string;
  sale_price: string;
  description: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type ProductListItem = Product;
export type ProductResponse = Product;

export type ProductListResponse = {
  items: ProductListItem[];
  meta: PaginationMeta;
};

export type ProductListParams = {
  page?: number;
  pageSize?: number;
  q?: string;
  active?: boolean;
  sku?: string;
};

export type ProductCreatePayload = {
  name: string;
  sku?: string | null;
  currency: string;
  sale_price: string;
  description?: string | null;
  is_active: boolean;
};

export type ProductUpdatePayload = Partial<ProductCreatePayload>;
