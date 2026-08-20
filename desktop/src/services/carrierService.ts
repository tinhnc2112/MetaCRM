import { apiClient } from "./apiClient";
import type {
  CarrierAccount,
  CarrierAccountCreateInput,
  CarrierAccountListResponse,
  CarrierAccountUpdateInput,
  CarrierCredentialsUpdateInput,
  CarrierProviderListResponse
} from "../types/carrier";

export async function listCarrierProviders(): Promise<CarrierProviderListResponse> {
  const response = await apiClient.get<CarrierProviderListResponse>("/api/v1/facebook/carriers/providers");
  return response.data;
}

export async function listCarrierAccounts(): Promise<CarrierAccountListResponse> {
  const response = await apiClient.get<CarrierAccountListResponse>("/api/v1/facebook/carrier-accounts");
  return response.data;
}

export async function createCarrierAccount(input: CarrierAccountCreateInput): Promise<CarrierAccount> {
  const response = await apiClient.post<CarrierAccount>("/api/v1/facebook/carrier-accounts", input);
  return response.data;
}

export async function getCarrierAccount(accountUuid: string): Promise<CarrierAccount> {
  const response = await apiClient.get<CarrierAccount>(
    `/api/v1/facebook/carrier-accounts/${encodeURIComponent(accountUuid)}`
  );
  return response.data;
}

export async function updateCarrierAccount(
  accountUuid: string,
  input: CarrierAccountUpdateInput
): Promise<CarrierAccount> {
  const response = await apiClient.patch<CarrierAccount>(
    `/api/v1/facebook/carrier-accounts/${encodeURIComponent(accountUuid)}`,
    input
  );
  return response.data;
}

export async function updateCarrierCredentials(
  accountUuid: string,
  input: CarrierCredentialsUpdateInput
): Promise<CarrierAccount> {
  const response = await apiClient.put<CarrierAccount>(
    `/api/v1/facebook/carrier-accounts/${encodeURIComponent(accountUuid)}/credentials`,
    input
  );
  return response.data;
}

export async function deactivateCarrierAccount(accountUuid: string): Promise<CarrierAccount> {
  const response = await apiClient.post<CarrierAccount>(
    `/api/v1/facebook/carrier-accounts/${encodeURIComponent(accountUuid)}/deactivate`
  );
  return response.data;
}
