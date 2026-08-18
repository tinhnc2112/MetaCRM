import { apiClient } from "./apiClient";
import type {
  ProductCreatePayload,
  ProductListParams,
  ProductListResponse,
  ProductResponse,
  ProductUpdatePayload
} from "../types/product";

const PRODUCT_PATH = "/api/v1/facebook/products";

export async function listProducts(input?: ProductListParams): Promise<ProductListResponse> {
  const response = await apiClient.get<ProductListResponse>(PRODUCT_PATH, {
    params: {
      page: input?.page,
      page_size: input?.pageSize,
      q: input?.q,
      active: input?.active,
      sku: input?.sku
    }
  });
  return response.data;
}

export async function getProduct(productUuid: string): Promise<ProductResponse> {
  const response = await apiClient.get<ProductResponse>(
    `${PRODUCT_PATH}/${encodeURIComponent(productUuid)}`
  );
  return response.data;
}

export async function createProduct(payload: ProductCreatePayload): Promise<ProductResponse> {
  const response = await apiClient.post<ProductResponse>(PRODUCT_PATH, payload);
  return response.data;
}

export async function updateProduct(
  productUuid: string,
  payload: ProductUpdatePayload
): Promise<ProductResponse> {
  const response = await apiClient.patch<ProductResponse>(
    `${PRODUCT_PATH}/${encodeURIComponent(productUuid)}`,
    payload
  );
  return response.data;
}

export async function archiveProduct(productUuid: string): Promise<ProductResponse> {
  const response = await apiClient.delete<ProductResponse>(
    `${PRODUCT_PATH}/${encodeURIComponent(productUuid)}`
  );
  return response.data;
}
