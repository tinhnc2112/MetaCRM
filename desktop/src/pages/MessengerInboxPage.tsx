import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Avatar, Badge, Empty, List, Spin, Typography } from "antd";

import { getCurrentFacebookPage } from "../services/facebookService";
import { listConversations, listMessages, markConversationRead } from "../services/messengerService";
import type { Conversation, Message } from "../types/messenger";

type InboxEvent = {
  type?: string;
  conversation_id?: string;
  page_id?: string;
  message_id?: string;
};

export function MessengerInboxPage() {
  const queryClient = useQueryClient();
  const [selectedConversationId, setSelectedConversationId] = useState<string | null>(null);

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

  const markReadMutation = useMutation({
    mutationFn: markConversationRead,
    onSuccess: async (_, conversationId) => {
      await queryClient.invalidateQueries({ queryKey: ["messenger-conversations", currentPageId] });
      await queryClient.invalidateQueries({ queryKey: ["messenger-messages", conversationId] });
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

  const conversations = conversationsQuery.data?.items ?? [];
  const messages = messagesQuery.data?.items ?? [];

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
              <Empty description="No messages in this conversation" />
            ) : (
              <div className="messenger-thread">
                {messages.map((message) => (
                  <MessageBubble key={message.id} message={message} />
                ))}
              </div>
            )}
          </section>
        </div>
      )}
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
  return (
    <List.Item className={selected ? "messenger-conversation selected" : "messenger-conversation"} onClick={onClick}>
      <List.Item.Meta
        avatar={<Avatar>{(conversation.customer_name ?? conversation.psid).slice(0, 1).toUpperCase()}</Avatar>}
        title={
          <div className="messenger-conversation-title">
            <span>{conversation.customer_name ?? conversation.psid}</span>
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

function formatTimestamp(value: string | null): string {
  if (!value) {
    return "Unknown time";
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}
