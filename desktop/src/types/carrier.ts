export type CarrierCapabilities = {
  supports_credentials: boolean;
  requires_credentials: boolean;
  shipment_binding: boolean;
  waybills: boolean;
  labels: boolean;
  tracking: boolean;
  rates: boolean;
  webhooks: boolean;
};

export type CarrierProvider = {
  code: string;
  display_name: string;
  capabilities: CarrierCapabilities;
};

export type CarrierProviderListResponse = {
  items: CarrierProvider[];
};

export type CarrierAccountStatus = "active" | "inactive";

export type CarrierAccount = {
  uuid: string;
  provider_code: string;
  display_name: string;
  status: CarrierAccountStatus;
  configuration: Record<string, unknown>;
  configured: boolean;
  created_at: string;
  updated_at: string;
  deactivated_at: string | null;
};

export type CarrierAccountListResponse = {
  items: CarrierAccount[];
};

export type CarrierAccountCreateInput = {
  provider_code: string;
  display_name: string;
  configuration: Record<string, unknown>;
  credentials?: Record<string, unknown>;
};

export type CarrierAccountUpdateInput = {
  display_name?: string;
  configuration?: Record<string, unknown>;
};

export type CarrierCredentialsUpdateInput = {
  credentials: Record<string, unknown>;
};
