import { apiClient } from "./apiClient";
import type {
  InventoryAdjustmentPayload,
  InventoryEnablePayload,
  InventoryState,
  StockMovement,
  StockMovementListParams,
  StockMovementListResponse
} from "../types/inventory";

function inventoryPath(productUuid: string): string {
  return `/api/v1/facebook/products/${encodeURIComponent(productUuid)}/inventory`;
}

export async function getProductInventory(productUuid: string): Promise<InventoryState> {
  const response = await apiClient.get<InventoryState>(inventoryPath(productUuid));
  return response.data;
}

export async function enableProductInventory(
  productUuid: string,
  payload: InventoryEnablePayload
): Promise<InventoryState> {
  const response = await apiClient.post<InventoryState>(
    `${inventoryPath(productUuid)}/enable`,
    payload
  );
  return response.data;
}

export async function disableProductInventory(productUuid: string): Promise<InventoryState> {
  const response = await apiClient.post<InventoryState>(
    `${inventoryPath(productUuid)}/disable`
  );
  return response.data;
}

export async function adjustProductInventory(
  productUuid: string,
  payload: InventoryAdjustmentPayload
): Promise<StockMovement> {
  const response = await apiClient.post<StockMovement>(
    `${inventoryPath(productUuid)}/adjustments`,
    payload
  );
  return response.data;
}

export async function listProductInventoryMovements(
  productUuid: string,
  input?: StockMovementListParams
): Promise<StockMovementListResponse> {
  const response = await apiClient.get<StockMovementListResponse>(
    `${inventoryPath(productUuid)}/movements`,
    {
      params: {
        page: input?.page,
        page_size: input?.pageSize,
        movement_type: input?.movementType
      }
    }
  );
  return response.data;
}
