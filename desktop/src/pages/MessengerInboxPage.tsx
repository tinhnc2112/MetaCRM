import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Avatar, Badge, Button, Empty, Input, List, Spin, Typography } from "antd";

import { CustomerProfilePanel } from "../components/CustomerProfilePanel";
import { CustomerTagManagerModal } from "../components/CustomerTagManagerModal";
import { getCurrentFacebookPage } from "../services/facebookService";
import {
  createCustomerNote,
  deleteCustomerNote,
  getCustomerProfile,
  updateCustomerNote
} from "../services/customerService";
import {
  assignCustomerTag,
  createCustomerTag,
  deleteCustomerTag,
  listCustomerTagCustomers,
  listCustomerTags,
  removeCustomerTag,
  updateCustomerTag
} from "../services/customerTagService";
import { listConversations, listMessages, markConversationRead, sendMessage } from "../services/messengerService";
import type { Conversation, Message } from "../types/messenger";
import type { CustomerTag } from "../types/customer";

type InboxEvent = {
  type?: string;
  conversation_id?: string;
  page_id?: string;
  message_id?: string;
};

export function MessengerInboxPage() {
  const queryClient = useQueryClient();
  const [selectedConversationId, setSelectedConversationId] = useState<string | null>(null);
  const [draftText, setDraftText] = useState("");
  const [sendError, setSendError] = useState<string | null>(null);
  const [tagManagerOpen, setTagManagerOpen] = useState(false);
  const [selectedTagId, setSelectedTagId] = useState<number | null>(null);

  const currentPageQuery = useQuery({
    queryKey: ["facebook-current-page"],
    queryFn: getCurrentFacebookPage
  });

  const currentPageId = currentPageQuery.data?.item?.page_id ?? null;

  const conversationsQuery = useQuery({
    queryKey: ["messenger-conversations", currentPageId],
    queryFn: () => listConversations(currentPageId ?? undefined),
    enabled: Boolean(currentPageId)
  });

  const selectedConversation = useMemo(
    () => conversationsQuery.data?.items.find((item) => item.id === selectedConversationId) ?? null,
    [conversationsQuery.data?.items, selectedConversationId]
  );

  const messagesQuery = useQuery({
    queryKey: ["messenger-messages", selectedConversationId],
    queryFn: () => listMessages(selectedConversationId as string),
    enabled: Boolean(selectedConversationId)
  });

  const customerProfileQuery = useQuery({
    queryKey: ["customer-profile", selectedConversationId],
    queryFn: () => getCustomerProfile(selectedConversationId as string),
    enabled: Boolean(selectedConversationId)
  });

  const pageTagsQuery = useQuery({
    queryKey: ["customer-tags", currentPageId],
    queryFn: listCustomerTags,
    enabled: Boolean(currentPageId)
  });

  const tagCustomersQuery = useQuery({
    queryKey: ["customer-tag-customers", currentPageId, selectedTagId],
    queryFn: () => listCustomerTagCustomers(selectedTagId as number),
    enabled: Boolean(currentPageId && tagManagerOpen && selectedTagId !== null)
  });

  const markReadMutation = useMutation({
    mutationFn: markConversationRead,
    onSuccess: async (_, conversationId) => {
      await queryClient.invalidateQueries({ queryKey: ["messenger-conversations", currentPageId] });
      await queryClient.invalidateQueries({ queryKey: ["messenger-messages", conversationId] });
      await queryClient.invalidateQueries({ queryKey: ["customer-profile", conversationId] });
    }
  });

  const sendMessageMutation = useMutation({
    mutationFn: ({ conversationId, text }: { conversationId: string; text: string }) =>
      sendMessage(conversationId, text),
    onSuccess: async (message) => {
      setDraftText("");
      setSendError(null);
      if (selectedConversationId) {
        await queryClient.invalidateQueries({ queryKey: ["messenger-messages", selectedConversationId] });
        await queryClient.invalidateQueries({ queryKey: ["customer-profile", selectedConversationId] });
      }
      await queryClient.invalidateQueries({ queryKey: ["messenger-conversations", currentPageId] });
      queryClient.setQueryData(["messenger-messages", selectedConversationId], (previous: any) => {
        if (!previous?.items) {
          return previous;
        }
        const nextItems = previous.items.some((item: Message) => item.id === message.id)
          ? previous.items
          : [message, ...previous.items];
        return { ...previous, items: nextItems };
      });
    },
    onError: () => {
      setSendError("Could not send the message.");
    }
  });

  const saveCustomerNoteMutation = useMutation({
    mutationFn: async ({ noteId, content }: { noteId: string | null; content: string }) => {
      if (!selectedConversationId) {
        return null;
      }
      if (noteId) {
        return updateCustomerNote(noteId, content);
      }
      return createCustomerNote(selectedConversationId, content);
    },
    onSuccess: async () => {
      if (!selectedConversationId) {
        return;
      }
      await queryClient.invalidateQueries({ queryKey: ["customer-profile", selectedConversationId] });
    }
  });

  const createCustomerTagMutation = useMutation({
    mutationFn: createCustomerTag,
    onSuccess: async (tag) => {
      setSelectedTagId(tag.id);
      await queryClient.invalidateQueries({ queryKey: ["customer-tags", currentPageId] });
    }
  });

  const updateCustomerTagMutation = useMutation({
    mutationFn: ({ tagId, input }: { tagId: number; input: { name: string; description: string | null } }) =>
      updateCustomerTag(tagId, input),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["customer-tags", currentPageId] });
      if (selectedConversationId) {
        await queryClient.invalidateQueries({ queryKey: ["customer-profile", selectedConversationId] });
      }
      if (selectedTagId !== null) {
        await queryClient.invalidateQueries({ queryKey: ["customer-tag-customers", currentPageId, selectedTagId] });
      }
    }
  });

  const deleteCustomerTagMutation = useMutation({
    mutationFn: deleteCustomerTag,
    onSuccess: async (_, tagId) => {
      if (selectedTagId === tagId) {
        setSelectedTagId(null);
      }
      await queryClient.invalidateQueries({ queryKey: ["customer-tags", currentPageId] });
      if (selectedConversationId) {
        await queryClient.invalidateQueries({ queryKey: ["customer-profile", selectedConversationId] });
      }
    }
  });

  const assignCustomerTagMutation = useMutation({
    mutationFn: ({ conversationId, tagId }: { conversationId: string; tagId: number }) =>
      assignCustomerTag(conversationId, tagId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["customer-tags", currentPageId] });
      if (selectedConversationId) {
        await queryClient.invalidateQueries({ queryKey: ["customer-profile", selectedConversationId] });
      }
      if (tagManagerOpen && selectedTagId !== null) {
        await queryClient.invalidateQueries({ queryKey: ["customer-tag-customers", currentPageId, selectedTagId] });
      }
    }
  });

  const removeCustomerTagMutation = useMutation({
    mutationFn: ({ conversationId, tagId }: { conversationId: string; tagId: number }) =>
      removeCustomerTag(conversationId, tagId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["customer-tags", currentPageId] });
      if (selectedConversationId) {
        await queryClient.invalidateQueries({ queryKey: ["customer-profile", selectedConversationId] });
      }
      if (tagManagerOpen && selectedTagId !== null) {
        await queryClient.invalidateQueries({ queryKey: ["customer-tag-customers", currentPageId, selectedTagId] });
      }
    }
  });

  const deleteCustomerNoteMutation = useMutation({
    mutationFn: deleteCustomerNote,
    onSuccess: async () => {
      if (!selectedConversationId) {
        return;
      }
      await queryClient.invalidateQueries({ queryKey: ["customer-profile", selectedConversationId] });
    }
  });

  useEffect(() => {
    if (!currentPageId) {
      return;
    }

    const baseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";
    const wsUrl = new URL("/api/v1/ws", baseUrl);
    wsUrl.protocol = wsUrl.protocol === "https:" ? "wss:" : "ws:";
    wsUrl.searchParams.set("channel", `page:${currentPageId}`);

    const socket = new WebSocket(wsUrl.toString());
    socket.addEventListener("message", (event) => {
      if (typeof event.data !== "string") {
        return;
      }
      let payload: InboxEvent | null = null;
      try {
        payload = JSON.parse(event.data) as InboxEvent;
      } catch {
        return;
      }
      if (payload?.type !== "new_message") {
        return;
      }
      void queryClient.invalidateQueries({ queryKey: ["messenger-conversations", currentPageId] });
      void queryClient.invalidateQueries({ queryKey: ["customer-profile", payload.conversation_id] });
      if (payload.conversation_id === selectedConversationId) {
        void queryClient.invalidateQueries({ queryKey: ["messenger-messages", selectedConversationId] });
      }
    });

    return () => {
      socket.close();
    };
  }, [currentPageId, queryClient, selectedConversationId]);

  useEffect(() => {
    if (selectedConversationId) {
      markReadMutation.mutate(selectedConversationId);
    }
  }, [selectedConversationId]);

  useEffect(() => {
    if (!tagManagerOpen) {
      return;
    }
    const tags = pageTagsQuery.data?.items ?? [];
    if (tags.length === 0) {
      setSelectedTagId(null);
      return;
    }
    if (selectedTagId === null || !tags.some((tag: CustomerTag) => tag.id === selectedTagId)) {
      setSelectedTagId(tags[0].id);
    }
  }, [pageTagsQuery.data?.items, selectedTagId, tagManagerOpen]);

  const conversations = conversationsQuery.data?.items ?? [];
  const messages = messagesQuery.data?.items ?? [];
  const trimmedDraft = draftText.trim();
  const customerProfile = customerProfileQuery.data ?? null;
  const pageTags = pageTagsQuery.data?.items ?? [];
  const tagCustomers = tagCustomersQuery.data?.items ?? [];

  const handleSend = () => {
    if (!selectedConversationId || !trimmedDraft || sendMessageMutation.isPending) {
      return;
    }
    void sendMessageMutation.mutateAsync({ conversationId: selectedConversationId, text: trimmedDraft });
  };

  const handleSaveNote = async ({ noteId, content }: { noteId: string | null; content: string }) => {
    await saveCustomerNoteMutation.mutateAsync({ noteId, content });
  };

  const handleDeleteNote = async (noteId: string) => {
    await deleteCustomerNoteMutation.mutateAsync(noteId);
  };

  const handleAssignTag = async (tagId: number) => {
    if (!selectedConversationId) {
      return;
    }
    await assignCustomerTagMutation.mutateAsync({ conversationId: selectedConversationId, tagId });
  };

  const handleRemoveTag = async (tagId: number) => {
    if (!selectedConversationId) {
      return;
    }
    await removeCustomerTagMutation.mutateAsync({ conversationId: selectedConversationId, tagId });
  };

  const handleCreateTag = async (input: { name: string; description: string | null }) => {
    await createCustomerTagMutation.mutateAsync(input);
  };

  const handleUpdateTag = async (tagId: number, input: { name: string; description: string | null }) => {
    await updateCustomerTagMutation.mutateAsync({ tagId, input });
  };

  const handleDeleteTag = async (tagId: number) => {
    await deleteCustomerTagMutation.mutateAsync(tagId);
  };

  return (
    <div className="messenger-inbox-page">
      <div className="messenger-inbox-header">
        <div>
          <Typography.Title level={2}>Messenger Inbox</Typography.Title>
          <Typography.Text type="secondary">
            Realtime conversations for your currently selected Facebook Page.
          </Typography.Text>
        </div>
      </div>

      {!currentPageId ? (
        <Alert
          type="info"
          showIcon
          message="No Facebook Page selected"
          description="Open Facebook settings and select a page to start loading conversations."
        />
      ) : (
        <div className="messenger-inbox-grid">
          <section className="messenger-list-panel">
            {conversationsQuery.isLoading ? (
              <div className="messenger-loading">
                <Spin />
              </div>
            ) : conversationsQuery.isError ? (
              <Alert type="error" showIcon message="Could not load conversations." />
            ) : conversations.length === 0 ? (
              <Empty description="No conversations yet" />
            ) : (
              <List
                dataSource={conversations}
                renderItem={(conversation) => (
                  <ConversationListItem
                    conversation={conversation}
                    selected={conversation.id === selectedConversationId}
                    onClick={() => setSelectedConversationId(conversation.id)}
                  />
                )}
              />
            )}
          </section>

          <section className="messenger-thread-panel">
            {!selectedConversation ? (
              <Empty description="Select a conversation to view messages" />
            ) : messagesQuery.isLoading ? (
              <div className="messenger-loading">
                <Spin />
              </div>
            ) : messagesQuery.isError ? (
              <Alert type="error" showIcon message="Could not load messages." />
            ) : messages.length === 0 ? (
              <div className="messenger-thread-shell">
                <Empty description="No messages in this conversation" />
                <MessageComposer
                  value={draftText}
                  error={sendError}
                  loading={sendMessageMutation.isPending}
                  disabled={!trimmedDraft}
                  onChange={setDraftText}
                  onSend={handleSend}
                />
              </div>
            ) : (
              <div className="messenger-thread-shell">
                <div className="messenger-thread">
                  {messages.map((message) => (
                    <MessageBubble key={message.id} message={message} />
                  ))}
                </div>
                <MessageComposer
                  value={draftText}
                  error={sendError}
                  loading={sendMessageMutation.isPending}
                  disabled={!trimmedDraft}
                  onChange={setDraftText}
                  onSend={handleSend}
                />
              </div>
            )}
          </section>

          <CustomerProfilePanel
            profile={customerProfile}
            pageTags={pageTags}
            loading={customerProfileQuery.isLoading}
            error={customerProfileQuery.isError}
            savingNote={saveCustomerNoteMutation.isPending || deleteCustomerNoteMutation.isPending}
            savingTag={assignCustomerTagMutation.isPending || removeCustomerTagMutation.isPending}
            onSaveNote={handleSaveNote}
            onDeleteNote={handleDeleteNote}
            onAssignTag={handleAssignTag}
            onRemoveTag={handleRemoveTag}
            onManageTags={() => setTagManagerOpen(true)}
          />
        </div>
      )}

      <CustomerTagManagerModal
        open={tagManagerOpen}
        tags={pageTags}
        selectedTagId={selectedTagId}
        customers={tagCustomers}
        customersLoading={tagCustomersQuery.isLoading}
        onClose={() => setTagManagerOpen(false)}
        onSelectTag={setSelectedTagId}
        onCreateTag={handleCreateTag}
        onUpdateTag={handleUpdateTag}
        onDeleteTag={handleDeleteTag}
        onSelectConversation={(conversationId) => {
          setSelectedConversationId(conversationId);
          setTagManagerOpen(false);
        }}
      />
    </div>
  );
}

function ConversationListItem({
  conversation,
  selected,
  onClick
}: {
  conversation: Conversation;
  selected: boolean;
  onClick: () => void;
}) {
  const displayName = conversation.customer_name ?? conversation.psid;
  return (
    <List.Item className={selected ? "messenger-conversation selected" : "messenger-conversation"} onClick={onClick}>
      <List.Item.Meta
        avatar={
          conversation.customer_avatar_url ? (
            <Avatar src={conversation.customer_avatar_url} />
          ) : (
            <Avatar>{displayName.slice(0, 1).toUpperCase()}</Avatar>
          )
        }
        title={
          <div className="messenger-conversation-title">
            <span>{displayName}</span>
            {conversation.unread_count > 0 ? <Badge count={conversation.unread_count} /> : null}
          </div>
        }
        description={
          <div className="messenger-conversation-meta">
            <span>{conversation.last_message_preview ?? "No message preview"}</span>
            <span>{formatTimestamp(conversation.last_message_at)}</span>
          </div>
        }
      />
    </List.Item>
  );
}

function MessageBubble({ message }: { message: Message }) {
  return (
    <article className={message.is_from_page ? "messenger-message from-page" : "messenger-message from-customer"}>
      <div className="messenger-message-body">{message.text ?? message.postback_payload ?? message.event_type}</div>
      <div className="messenger-message-time">{formatTimestamp(message.sent_at ?? message.created_at)}</div>
    </article>
  );
}

function MessageComposer({
  value,
  error,
  loading,
  disabled,
  onChange,
  onSend
}: {
  value: string;
  error: string | null;
  loading: boolean;
  disabled: boolean;
  onChange: (value: string) => void;
  onSend: () => void;
}) {
  return (
    <div className="messenger-composer">
      {error ? <Alert type="error" showIcon message={error} /> : null}
      <Input.TextArea
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder="Write a reply..."
        autoSize={{ minRows: 3, maxRows: 6 }}
        onPressEnter={(event) => {
          if (!event.shiftKey) {
            event.preventDefault();
            onSend();
          }
        }}
      />
      <div className="messenger-composer-actions">
        <Typography.Text type="secondary">Enter to send, Shift+Enter for a new line</Typography.Text>
        <Button type="primary" onClick={onSend} loading={loading} disabled={disabled}>
          Send
        </Button>
      </div>
    </div>
  );
}

function formatTimestamp(value: string | null): string {
  if (!value) {
    return "Unknown time";
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}
