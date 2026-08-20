import { EditOutlined, PlusOutlined, PoweroffOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Empty,
  Form,
  Input,
  List,
  Modal,
  Select,
  Space,
  Tag,
  Typography
} from "antd";
import { useEffect, useRef, useState } from "react";

import {
  createCarrierAccount,
  deactivateCarrierAccount,
  getCarrierAccount,
  listCarrierAccounts,
  listCarrierProviders,
  updateCarrierAccount,
  updateCarrierCredentials
} from "../services/carrierService";
import { getCurrentFacebookPage } from "../services/facebookService";
import type {
  CarrierAccount,
  CarrierAccountCreateInput,
  CarrierAccountUpdateInput
} from "../types/carrier";

type AccountFormValues = {
  displayName: string;
  providerCode: string;
  configuration: string;
};

type CredentialFormValues = {
  credentials: string;
};

export function CarrierSettingsPage() {
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const [accountForm] = Form.useForm<AccountFormValues>();
  const [credentialForm] = Form.useForm<CredentialFormValues>();
  const [accountModalOpen, setAccountModalOpen] = useState(false);
  const [credentialModalOpen, setCredentialModalOpen] = useState(false);
  const [editingAccount, setEditingAccount] = useState<CarrierAccount | null>(null);
  const [credentialAccount, setCredentialAccount] = useState<CarrierAccount | null>(null);
  const pageIdRef = useRef<string | null>(null);

  const currentPageQuery = useQuery({
    queryKey: ["facebook-current-page"],
    queryFn: getCurrentFacebookPage
  });
  const currentPage = currentPageQuery.data?.item ?? null;
  const currentPageId = currentPage?.page_id ?? null;
  pageIdRef.current = currentPageId;

  const providersQuery = useQuery({
    queryKey: ["carrier-providers", currentPageId],
    queryFn: listCarrierProviders,
    enabled: Boolean(currentPageId)
  });

  const accountsQuery = useQuery({
    queryKey: ["carrier-accounts", currentPageId],
    queryFn: listCarrierAccounts,
    enabled: Boolean(currentPageId)
  });

  const closeAccountModal = () => {
    setAccountModalOpen(false);
    setEditingAccount(null);
    accountForm.resetFields();
  };

  const closeCredentialModal = () => {
    setCredentialModalOpen(false);
    setCredentialAccount(null);
    credentialForm.resetFields();
  };

  useEffect(() => {
    closeAccountModal();
    closeCredentialModal();
  }, [currentPageId]);

  const refreshAccountsForPage = async (pageId: string) => {
    if (pageIdRef.current !== pageId) {
      return;
    }
    await queryClient.invalidateQueries({ queryKey: ["carrier-accounts", pageId], exact: true });
  };

  const createMutation = useMutation({
    mutationFn: ({ input }: { pageId: string; input: CarrierAccountCreateInput }) => createCarrierAccount(input),
    onSuccess: async (_, variables) => {
      if (pageIdRef.current !== variables.pageId) {
        return;
      }
      await refreshAccountsForPage(variables.pageId);
      closeAccountModal();
      void message.success("Carrier account added.");
    },
    onError: (_, variables) => {
      if (pageIdRef.current === variables.pageId) {
        void message.error("Carrier account could not be added.");
      }
    }
  });

  const updateMutation = useMutation({
    mutationFn: ({ accountUuid, input }: { pageId: string; accountUuid: string; input: CarrierAccountUpdateInput }) =>
      updateCarrierAccount(accountUuid, input),
    onSuccess: async (_, variables) => {
      if (pageIdRef.current !== variables.pageId) {
        return;
      }
      await refreshAccountsForPage(variables.pageId);
      closeAccountModal();
      void message.success("Carrier account updated.");
    },
    onError: (_, variables) => {
      if (pageIdRef.current === variables.pageId) {
        void message.error("Carrier account could not be updated.");
      }
    }
  });

  const credentialsMutation = useMutation({
    mutationFn: ({ accountUuid, credentials }: { pageId: string; accountUuid: string; credentials: Record<string, unknown> }) =>
      updateCarrierCredentials(accountUuid, { credentials }),
    onSuccess: async (_, variables) => {
      credentialForm.resetFields();
      if (pageIdRef.current !== variables.pageId) {
        return;
      }
      await refreshAccountsForPage(variables.pageId);
      closeCredentialModal();
      void message.success("Credentials saved.");
    },
    onError: (_, variables) => {
      credentialForm.resetFields();
      if (pageIdRef.current === variables.pageId) {
        void message.error("Credentials could not be saved. Re-enter them to try again.");
      }
    }
  });

  const deactivateMutation = useMutation({
    mutationFn: ({ accountUuid }: { pageId: string; accountUuid: string }) => deactivateCarrierAccount(accountUuid),
    onSuccess: async (_, variables) => {
      if (pageIdRef.current !== variables.pageId) {
        return;
      }
      await refreshAccountsForPage(variables.pageId);
      void message.success("Carrier account deactivated.");
    },
    onError: (_, variables) => {
      if (pageIdRef.current === variables.pageId) {
        void message.error("Carrier account could not be deactivated.");
      }
    }
  });

  const openCreate = () => {
    setEditingAccount(null);
    accountForm.resetFields();
    accountForm.setFieldsValue({ displayName: "", configuration: "{}" });
    setAccountModalOpen(true);
  };

  const openEdit = async (account: CarrierAccount) => {
    const pageId = currentPageId;
    if (!pageId) {
      return;
    }
    try {
      const detail = await getCarrierAccount(account.uuid);
      if (pageIdRef.current !== pageId) {
        return;
      }
      setEditingAccount(detail);
      accountForm.setFieldsValue({
        displayName: detail.display_name,
        providerCode: detail.provider_code,
        configuration: JSON.stringify(detail.configuration, null, 2)
      });
      setAccountModalOpen(true);
    } catch {
      if (pageIdRef.current === pageId) {
        void message.error("Carrier account could not be loaded.");
      }
    }
  };

  const openCredentials = (account: CarrierAccount) => {
    credentialForm.resetFields();
    setCredentialAccount(account);
    setCredentialModalOpen(true);
  };

  const saveAccount = async () => {
    if (!currentPageId) {
      return;
    }
    try {
      const values = await accountForm.validateFields();
      const configuration = parseJsonObject(values.configuration, "Configuration");
      if (editingAccount) {
        updateMutation.mutate({
          pageId: currentPageId,
          accountUuid: editingAccount.uuid,
          input: { display_name: values.displayName.trim(), configuration }
        });
      } else {
        createMutation.mutate({
          pageId: currentPageId,
          input: {
            provider_code: values.providerCode,
            display_name: values.displayName.trim(),
            configuration
          }
        });
      }
    } catch (error) {
      if (error instanceof Error) {
        void message.error(error.message);
      }
    }
  };

  const saveCredentials = async () => {
    if (!currentPageId || !credentialAccount) {
      return;
    }
    try {
      const values = await credentialForm.validateFields();
      const credentials = parseJsonObject(values.credentials, "Credentials");
      credentialsMutation.mutate({ pageId: currentPageId, accountUuid: credentialAccount.uuid, credentials });
    } catch (error) {
      if (error instanceof Error) {
        void message.error(error.message);
      }
    }
  };

  const confirmDeactivate = (account: CarrierAccount) => {
    if (!currentPageId) {
      return;
    }
    const pageId = currentPageId;
    modal.confirm({
      title: "Deactivate carrier account?",
      content: `${account.display_name} will no longer be available for new carrier operations.`,
      okText: "Deactivate",
      okButtonProps: { danger: true },
      onOk: () => deactivateMutation.mutateAsync({ pageId, accountUuid: account.uuid })
    });
  };

  const providers = providersQuery.data?.items ?? [];
  const providerNames = new Map(providers.map((provider) => [provider.code, provider.display_name]));
  const providerCapabilities = new Map(providers.map((provider) => [provider.code, provider.capabilities]));
  const accounts = accountsQuery.data?.items ?? [];
  const savingAccount = createMutation.isPending || updateMutation.isPending;

  if (!currentPageQuery.isLoading && !currentPage) {
    return (
      <div className="settings-page">
        <Typography.Title level={2}>Carriers</Typography.Title>
        <Alert type="info" showIcon message="Select a Facebook Page before configuring carriers." />
      </div>
    );
  }

  return (
    <div className="settings-page">
      <div className="settings-header">
        <div>
          <Typography.Title level={2}>Carriers</Typography.Title>
          <Typography.Text type="secondary">
            {currentPage ? `Settings for ${currentPage.name}` : "Loading Page context…"}
          </Typography.Text>
        </div>
        <Button type="primary" icon={<PlusOutlined />} disabled={!currentPageId} onClick={openCreate}>
          Add account
        </Button>
      </div>

      <section className="settings-section">
        <List
          loading={currentPageQuery.isLoading || providersQuery.isLoading || accountsQuery.isLoading}
          dataSource={accounts}
          locale={{ emptyText: <Empty description="No carrier accounts configured for this Page" /> }}
          renderItem={(account) => (
            <List.Item
              actions={[
                <Button key="edit" icon={<EditOutlined />} onClick={() => void openEdit(account)}>
                  Edit
                </Button>,
                providerCapabilities.get(account.provider_code)?.supports_credentials ? (
                  <Button
                    key="credentials"
                    onClick={() => openCredentials(account)}
                    disabled={account.status !== "active"}
                  >
                    {account.configured ? "Replace credentials" : "Save credentials"}
                  </Button>
                ) : null,
                <Button
                  key="deactivate"
                  danger
                  icon={<PoweroffOutlined />}
                  disabled={account.status !== "active"}
                  loading={deactivateMutation.isPending}
                  onClick={() => confirmDeactivate(account)}
                >
                  Deactivate
                </Button>
              ]}
            >
              <List.Item.Meta
                title={account.display_name}
                description={providerNames.get(account.provider_code) ?? account.provider_code}
              />
              <Space wrap>
                <Tag color={account.status === "active" ? "success" : "default"}>
                  {account.status === "active" ? "Active" : "Inactive"}
                </Tag>
                <Tag color={account.configured ? "blue" : "warning"}>
                  {account.configured ? "Configured" : "Unconfigured"}
                </Tag>
              </Space>
            </List.Item>
          )}
        />
      </section>

      <Modal
        title={editingAccount ? "Edit carrier account" : "Add carrier account"}
        open={accountModalOpen}
        onCancel={closeAccountModal}
        onOk={() => void saveAccount()}
        confirmLoading={savingAccount}
        destroyOnClose
      >
        <Form form={accountForm} layout="vertical" preserve={false}>
          <Form.Item name="displayName" label="Display name" rules={[{ required: true, whitespace: true }]}>
            <Input maxLength={255} />
          </Form.Item>
          <Form.Item name="providerCode" label="Provider" rules={[{ required: true }]}>
            <Select
              disabled={Boolean(editingAccount)}
              options={providers.map((provider) => ({ value: provider.code, label: provider.display_name }))}
            />
          </Form.Item>
          <Form.Item
            name="configuration"
            label="Configuration (JSON)"
            rules={[{ required: true, message: "Enter a JSON object, or {}." }]}
          >
            <Input.TextArea autoSize={{ minRows: 5, maxRows: 12 }} spellCheck={false} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`Save credentials${credentialAccount ? ` — ${credentialAccount.display_name}` : ""}`}
        open={credentialModalOpen}
        onCancel={closeCredentialModal}
        onOk={() => void saveCredentials()}
        confirmLoading={credentialsMutation.isPending}
        okText="Save credentials"
        destroyOnClose
      >
        <Alert
          type="warning"
          showIcon
          message="Credentials are write-only"
          description="Existing credentials are never displayed. Enter the complete replacement JSON object; this field is cleared after every save attempt and when this dialog closes."
        />
        <Form form={credentialForm} layout="vertical" preserve={false} className="carrier-credential-form">
          <Form.Item
            name="credentials"
            label="Credentials (JSON)"
            rules={[{ required: true, message: "Enter the complete credentials JSON object." }]}
          >
            <Input.TextArea autoSize={{ minRows: 6, maxRows: 14 }} spellCheck={false} autoComplete="off" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

function parseJsonObject(value: string, label: string): Record<string, unknown> {
  let parsed: unknown;
  try {
    parsed = JSON.parse(value);
  } catch {
    throw new Error(`${label} must be valid JSON.`);
  }
  if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
    throw new Error(`${label} must be a JSON object.`);
  }
  return parsed as Record<string, unknown>;
}
