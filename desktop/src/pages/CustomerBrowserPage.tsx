import { SearchOutlined, TagOutlined, TeamOutlined, MessageOutlined } from "@ant-design/icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Alert, Avatar, Badge, Empty, Input, List, Pagination, Space, Spin, Tag, Typography } from "antd";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

import { CustomerProfilePanel } from "../components/CustomerProfilePanel";
import { getCurrentFacebookPage } from "../services/facebookService";
import {
  createCustomerNote,
  deleteCustomerNote,
  getCustomerProfileByCustomerId,
  listCustomers,
  updateCustomerNote
} from "../services/customerService";
import { assignCustomerTag, listCustomerTags, removeCustomerTag } from "../services/customerTagService";
import type { CustomerListItem, CustomerProfileResponse } from "../types/customer";

const DEFAULT_PAGE_SIZE = 20;

export function CustomerBrowserPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { customerId: routeCustomerId } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const [searchText, setSearchText] = useState(searchParams.get("q") ?? "");

  const currentPageQuery = useQuery({
    queryKey: ["facebook-current-page"],
    queryFn: getCurrentFacebookPage
  });

  const currentPageId = currentPageQuery.data?.item?.page_id ?? null;
  const currentPageName = currentPageQuery.data?.item?.name ?? null;
  const query = searchParams.get("q") ?? "";
  const page = parsePositiveInteger(searchParams.get("page")) ?? 1;
  const pageSize = DEFAULT_PAGE_SIZE;
  const selectedCustomerId = routeCustomerId ?? null;
  const activeConversationId = searchParams.get("conversationId");
  const previousPageIdRef = useRef<string | null>(null);

  useEffect(() => {
    setSearchText(query);
  }, [query]);

  const customersQuery = useQuery({
    queryKey: ["customer-list", currentPageId, query, page, pageSize],
    queryFn: () =>
      listCustomers({
        query: query || undefined,
        page,
        pageSize
      }),
    enabled: Boolean(currentPageId)
  });

  const pageTagsQuery = useQuery({
    queryKey: ["customer-tags", currentPageId],
    queryFn: listCustomerTags,
    enabled: Boolean(currentPageId)
  });

  const selectedCustomerQuery = useQuery({
    queryKey: ["customer-profile", currentPageId, selectedCustomerId],
    queryFn: () => getCustomerProfileByCustomerId(selectedCustomerId ?? ""),
    enabled: Boolean(currentPageId && selectedCustomerId)
  });

  const selectedCustomer = selectedCustomerQuery.data ?? null;
  const customerItems = customersQuery.data?.items ?? [];
  const pagination = customersQuery.data?.meta ?? null;
  const conversationOptions = selectedCustomer?.conversations ?? [];

  const resolvedConversationId = useMemo(() => {
    if (!selectedCustomer) {
      return null;
    }
    const availableConversationIds = new Set(conversationOptions.map((conversation) => conversation.uuid));
    if (activeConversationId && availableConversationIds.has(activeConversationId)) {
      return activeConversationId;
    }
    return selectedCustomer.conversation.uuid;
  }, [activeConversationId, conversationOptions, selectedCustomer]);

  const displayProfile = useMemo<CustomerProfileResponse | null>(() => {
    if (!selectedCustomer) {
      return null;
    }
    const activeConversation =
      conversationOptions.find((conversation) => conversation.uuid === resolvedConversationId) ??
      selectedCustomer.conversation;
    return {
      ...selectedCustomer,
      conversation: activeConversation
    };
  }, [conversationOptions, resolvedConversationId, selectedCustomer]);

  useEffect(() => {
    if (!currentPageId || selectedCustomerId || customerItems.length === 0) {
      return;
    }
    navigate(buildCustomerRoute(customerItems[0].uuid, searchParams), { replace: true });
  }, [currentPageId, customerItems, navigate, searchParams, selectedCustomerId]);

  useEffect(() => {
    const previousPageId = previousPageIdRef.current;
    previousPageIdRef.current = currentPageId;

    if (!previousPageId || previousPageId === currentPageId || !selectedCustomerId) {
      return;
    }
    if (selectedCustomerQuery.isLoading || !selectedCustomerQuery.isError) {
      return;
    }

    const nextSearch = buildCustomerSearchParams(searchParams, { conversationId: null }).toString();
    navigate(nextSearch ? `/customers?${nextSearch}` : "/customers", { replace: true });
  }, [currentPageId, navigate, searchParams, selectedCustomerId, selectedCustomerQuery.isError, selectedCustomerQuery.isLoading]);

  useEffect(() => {
    if (!selectedCustomerId || !selectedCustomer || !resolvedConversationId) {
      return;
    }
    if (searchParams.get("conversationId") === resolvedConversationId) {
      return;
    }
    setSearchParams(buildCustomerSearchParams(searchParams, { conversationId: resolvedConversationId }), { replace: true });
  }, [resolvedConversationId, searchParams, selectedCustomer, selectedCustomerId, setSearchParams]);

  const handleApplySearch = () => {
    const nextSearchParams = buildCustomerSearchParams(searchParams, {
      q: searchText.trim() ? searchText.trim() : null,
      page: 1,
      conversationId: null
    });
    setSearchParams(nextSearchParams, { replace: true });
  };

  const handlePageChange = (nextPage: number) => {
    const nextSearchParams = buildCustomerSearchParams(searchParams, {
      page: nextPage,
      conversationId: null
    });
    setSearchParams(nextSearchParams, { replace: true });
  };

  const handleSelectCustomer = (customer: CustomerListItem) => {
    navigate(buildCustomerRoute(customer.uuid, searchParams), { replace: false });
  };

  const handleSelectConversation = (conversationId: string) => {
    setSearchParams(buildCustomerSearchParams(searchParams, { conversationId }), { replace: true });
  };

  const handleOpenConversation = (conversationId: string) => {
    navigate(`/messenger?conversationId=${encodeURIComponent(conversationId)}`);
  };

  const handleOpenCustomer = (customerId: string) => {
    navigate(buildCustomerRoute(customerId, searchParams), { replace: false });
  };

  const handleSaveNote = async ({ noteId, content }: { noteId: string | null; content: string }) => {
    if (!resolvedConversationId) {
      return;
    }
    if (noteId) {
      await updateCustomerNote(noteId, content);
    } else {
      await createCustomerNote(resolvedConversationId, content);
    }
    await queryClient.invalidateQueries({ queryKey: ["customer-profile", currentPageId, selectedCustomerId] });
  };

  const handleDeleteNote = async (noteId: string) => {
    await deleteCustomerNote(noteId);
    await queryClient.invalidateQueries({ queryKey: ["customer-profile", currentPageId, selectedCustomerId] });
  };

  const handleAssignTag = async (tagId: number) => {
    if (!resolvedConversationId || !currentPageId) {
      return;
    }
    await assignCustomerTag(resolvedConversationId, tagId);
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["customer-profile", currentPageId, selectedCustomerId] }),
      queryClient.invalidateQueries({ queryKey: ["customer-list", currentPageId] })
    ]);
  };

  const handleRemoveTag = async (tagId: number) => {
    if (!resolvedConversationId || !currentPageId) {
      return;
    }
    await removeCustomerTag(resolvedConversationId, tagId);
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["customer-profile", currentPageId, selectedCustomerId] }),
      queryClient.invalidateQueries({ queryKey: ["customer-list", currentPageId] })
    ]);
  };

  if (!currentPageId) {
    return (
      <Alert
        type="info"
        showIcon
        message="No Facebook Page selected"
        description="Open Facebook settings and select a page before browsing customers."
      />
    );
  }

  return (
    <div className="customer-browser-page">
      <div className="customer-browser-header">
        <div>
          <Typography.Title level={2}>Customers</Typography.Title>
          <Typography.Text type="secondary">
            Browse the canonical customer list, inspect multi-conversation history, and jump into Messenger threads.
          </Typography.Text>
        </div>
        <Space wrap>
          <Tag color="blue" icon={<TeamOutlined />}>
            {pagination?.total ?? 0} customers
          </Tag>
          {currentPageName ? <Tag>{currentPageName}</Tag> : null}
        </Space>
      </div>

      <section className="customer-browser-toolbar">
        <Input.Search
          value={searchText}
          onChange={(event) => setSearchText(event.target.value)}
          placeholder="Search by name, phone, email, or PSID"
          allowClear
          enterButton={
            <Space>
              <SearchOutlined />
              Search
            </Space>
          }
          onSearch={() => handleApplySearch()}
        />
        <Typography.Text type="secondary">
          Page {pagination?.page ?? page} of {Math.max(Math.ceil((pagination?.total ?? 0) / pageSize), 1)}
        </Typography.Text>
      </section>

      <div className="customer-browser-layout">
        <section className="customer-browser-list-panel">
          {customersQuery.isLoading ? (
            <div className="customer-browser-loading">
              <Spin />
            </div>
          ) : customersQuery.isError ? (
            <Alert type="error" showIcon message="Could not load customers." />
          ) : customerItems.length === 0 ? (
            <Empty description={query ? "No customers matched your search" : "No customers found"} />
          ) : (
            <>
              <List
                dataSource={customerItems}
                renderItem={(customer) => (
                  <List.Item
                    className={
                      customer.uuid === selectedCustomerId
                        ? "customer-browser-item selected"
                        : "customer-browser-item"
                    }
                    onClick={() => handleSelectCustomer(customer)}
                  >
                    <List.Item.Meta
                      avatar={
                        customer.avatar_url ? (
                          <Avatar src={customer.avatar_url} />
                        ) : (
                          <Avatar>{getCustomerInitial(customer)}</Avatar>
                        )
                      }
                      title={
                        <div className="customer-browser-item-title">
                          <span>{customer.name ?? customer.email ?? customer.phone ?? customer.uuid}</span>
                          {customer.unread_count > 0 ? <Badge count={customer.unread_count} /> : null}
                        </div>
                      }
                      description={
                        <div className="customer-browser-item-meta">
                          <span>{buildCustomerSummary(customer)}</span>
                          <span>{formatTimestamp(customer.last_message_at)}</span>
                        </div>
                      }
                    />
                    <Space wrap size={6}>
                      <Tag icon={<MessageOutlined />}>{customer.conversation_count} conversations</Tag>
                      {customer.tags.slice(0, 3).map((tag) => (
                        <Tag key={tag.id} icon={<TagOutlined />}>
                          {tag.name}
                        </Tag>
                      ))}
                    </Space>
                  </List.Item>
                )}
              />

              {pagination ? (
                <div className="customer-browser-pagination">
                  <Pagination
                    current={pagination.page}
                    pageSize={pagination.page_size}
                    total={pagination.total}
                    onChange={handlePageChange}
                    showSizeChanger={false}
                  />
                </div>
              ) : null}
            </>
          )}
        </section>

        <section className="customer-browser-detail-panel">
          {selectedCustomerQuery.isLoading && !displayProfile ? (
            <div className="customer-browser-loading">
              <Spin />
            </div>
          ) : selectedCustomerQuery.isError ? (
            <Alert
              type="error"
              showIcon
              message="Could not load customer details."
              description="Try selecting another customer from the list."
            />
          ) : displayProfile ? (
            <CustomerProfilePanel
              profile={displayProfile}
              currentPageId={currentPageId}
              pageTags={pageTagsQuery.data?.items ?? []}
              loading={selectedCustomerQuery.isLoading}
              error={selectedCustomerQuery.isError}
              savingNote={false}
              savingTag={false}
              onSaveNote={handleSaveNote}
              onDeleteNote={handleDeleteNote}
              onAssignTag={handleAssignTag}
              onRemoveTag={handleRemoveTag}
              onManageTags={() => {
                void message.info("Tag management is available from the Messenger inbox.");
              }}
              onOpenCustomer={handleOpenCustomer}
              onOpenConversation={handleOpenConversation}
              onSelectConversation={handleSelectConversation}
            />
          ) : (
            <Empty description="Select a customer to browse their profile" />
          )}
        </section>
      </div>
    </div>
  );
}

function buildCustomerRoute(customerId: string, searchParams: URLSearchParams): string {
  const nextSearch = buildCustomerSearchParams(searchParams, { conversationId: null }).toString();
  return nextSearch
    ? `/customers/${encodeURIComponent(customerId)}?${nextSearch}`
    : `/customers/${encodeURIComponent(customerId)}`;
}

function buildCustomerSearchParams(
  searchParams: URLSearchParams,
  updates: {
    q?: string | null;
    page?: number | null;
    conversationId?: string | null;
  }
): URLSearchParams {
  const next = new URLSearchParams(searchParams);
  if (updates.q !== undefined) {
    if (updates.q && updates.q.trim()) {
      next.set("q", updates.q.trim());
    } else {
      next.delete("q");
    }
  }
  if (updates.page !== undefined) {
    if (updates.page && updates.page > 1) {
      next.set("page", String(updates.page));
    } else {
      next.delete("page");
    }
  }
  if (updates.conversationId !== undefined) {
    if (updates.conversationId) {
      next.set("conversationId", updates.conversationId);
    } else {
      next.delete("conversationId");
    }
  }
  return next;
}

function parsePositiveInteger(value: string | null): number | null {
  if (!value) {
    return null;
  }
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed) || parsed < 1) {
    return null;
  }
  return parsed;
}

function getCustomerInitial(customer: CustomerListItem): string {
  const value = customer.name ?? customer.email ?? customer.phone ?? customer.uuid;
  return value.slice(0, 1).toUpperCase();
}

function buildCustomerSummary(customer: CustomerListItem): string {
  const fields = [customer.phone, customer.email, `Customer ${customer.uuid}`].filter(Boolean);
  return fields.join(" | ");
}

function formatTimestamp(value: string | null): string {
  if (!value) {
    return "Unknown time";
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}
