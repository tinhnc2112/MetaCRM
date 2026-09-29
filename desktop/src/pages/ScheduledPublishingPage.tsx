import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Card, Form, Image, Input, List, Select, Space, Tag, Typography } from "antd";

import { getFacebookPages } from "../services/facebookService";
import {
  cancelScheduledPost, getPublishingConfig, listScheduledPosts, reschedulePost,
  resolvePost, retryScheduledPost, savePublishingConfig, syncPublishingSheet
} from "../services/publishingService";
import type { ScheduledPost } from "../types/publishing";

const statuses = ["INVALID", "READY", "SCHEDULED", "PUBLISHING", "PUBLISHED", "FAILED", "UNCERTAIN", "CANCELLED"];
const retryableCodes = new Set(["GRAPH_REJECTED", "PAGE_UNAVAILABLE", "INVALID_IMAGE", "VERIFIED_ABSENT"]);

export function ScheduledPublishingPage() {
  const { message, modal } = App.useApp();
  const client = useQueryClient();
  const [pageId, setPageId] = useState<string>();
  const [status, setStatus] = useState<string>();
  const [syncResult, setSyncResult] = useState<string>();
  const [form] = Form.useForm();
  const config = useQuery({ queryKey: ["publishing-config"], queryFn: getPublishingConfig });
  const pages = useQuery({ queryKey: ["facebook-pages"], queryFn: getFacebookPages });
  const posts = useQuery({ queryKey: ["scheduled-posts", pageId, status], queryFn: () => listScheduledPosts(pageId, status) });
  useEffect(() => {
    if (config.data) form.setFieldsValue({
      spreadsheet_id: config.data.spreadsheet_id,
      worksheet: config.data.worksheet,
      timezone: config.data.timezone || "Asia/Ho_Chi_Minh"
    });
  }, [config.data, form]);
  const refresh = async () => {
    await client.invalidateQueries({ queryKey: ["scheduled-posts"] });
    await client.invalidateQueries({ queryKey: ["publishing-config"] });
  };
  const sync = useMutation({
    mutationFn: syncPublishingSheet,
    onSuccess: async (result) => {
      setSyncResult(`Created ${result.created}, updated ${result.updated}, invalid ${result.invalid}`);
      await refresh();
    },
    onError: () => void message.error("Sheet sync failed. Check admin access and service account setup.")
  });
  const save = useMutation({
    mutationFn: savePublishingConfig,
    onSuccess: async () => { await refresh(); void message.success("Sheet configuration saved."); },
    onError: () => void message.error("Configuration could not be saved. Admin access is required.")
  });
  const action = useMutation({
    mutationFn: async ({ type, post, value }: { type: string; post: ScheduledPost; value?: string }) => {
      if (type === "cancel") return cancelScheduledPost(post.id);
      if (type === "retry") return retryScheduledPost(post.id);
      if (type === "reschedule") return reschedulePost(post.id, new Date(value || "").toISOString());
      if (type === "published") return resolvePost(post.id, "published", value);
      return resolvePost(post.id, "verified_not_published");
    },
    onSuccess: async () => { await refresh(); void message.success("Post updated."); },
    onError: () => void message.error("Post action failed or its state changed.")
  });
  const act = (type: string, post: ScheduledPost, value?: string) => action.mutate({ type, post, value });

  return <div className="settings-page">
    <Typography.Title level={2}>Scheduled Facebook Publishing</Typography.Title>
    <Card title="Google Sheet" style={{ marginBottom: 16 }}>
      <Typography.Paragraph>
        Last sync: {config.data?.last_synced_at ? new Date(config.data.last_synced_at).toLocaleString() : "Never"}
      </Typography.Paragraph>
      {config.data?.last_sync_result && <Typography.Paragraph>
        Last result: {JSON.stringify(config.data.last_sync_result)}
      </Typography.Paragraph>}
      {config.data?.last_sync_error && <Alert type="error" message={config.data.last_sync_error} />}
      {syncResult && <Alert type="success" message={syncResult} />}
      <Button type="primary" loading={sync.isPending} onClick={() => sync.mutate()} disabled={!config.data?.configured}>Sync Google Sheet</Button>
      <Form form={form} layout="inline" style={{ marginTop: 16 }}
        initialValues={{ spreadsheet_id: config.data?.spreadsheet_id, worksheet: config.data?.worksheet, timezone: config.data?.timezone || "Asia/Ho_Chi_Minh" }}
        onFinish={(values) => save.mutate(values)}>
        <Form.Item name="spreadsheet_id" rules={[{ required: true }]}><Input placeholder="Spreadsheet ID" /></Form.Item>
        <Form.Item name="worksheet" rules={[{ required: true }]}><Input placeholder="Worksheet" /></Form.Item>
        <Form.Item name="timezone" rules={[{ required: true }]}><Input placeholder="IANA timezone" /></Form.Item>
        <Button htmlType="submit" loading={save.isPending}>Save config (admin)</Button>
      </Form>
    </Card>
    <Space style={{ marginBottom: 16 }}>
      <Select allowClear placeholder="All Pages" style={{ width: 220 }} value={pageId} onChange={setPageId}
        options={(pages.data?.items || []).map((page) => ({ value: page.page_id, label: page.name }))} />
      <Select allowClear placeholder="All statuses" style={{ width: 180 }} value={status} onChange={setStatus}
        options={statuses.map((value) => ({ value, label: value }))} />
    </Space>
    <List loading={posts.isLoading} dataSource={posts.data?.items || []} renderItem={(post) => <List.Item
      actions={[
        ...(post.status === "SCHEDULED" ? [
          <Button key="reschedule" onClick={() => modal.confirm({ title: "Reschedule (ISO date and time with offset)",
            content: <Input id={`reschedule-${post.id}`} placeholder="2026-10-01T10:00:00+07:00" />,
            onOk: () => act("reschedule", post, (document.getElementById(`reschedule-${post.id}`) as HTMLInputElement)?.value) })}>Reschedule</Button>,
          <Button key="cancel" onClick={() => act("cancel", post)}>Cancel</Button>
        ] : []),
        ...(post.status === "FAILED" && post.attempt_count < 3 && retryableCodes.has(post.last_error_code || "") ? [<Button key="retry" onClick={() => act("retry", post)}>Retry</Button>] : []),
        ...(post.status === "UNCERTAIN" ? [
          <Button key="resolve" onClick={() => modal.confirm({ title: "Confirm published post on Facebook",
            content: <Input id={`post-id-${post.id}`} placeholder="Facebook post ID if published" />,
            onOk: () => {
              const id = (document.getElementById(`post-id-${post.id}`) as HTMLInputElement)?.value;
              if (!id) { void message.error("Facebook post ID is required."); return; }
              act("published", post, id);
            } })}>Mark published</Button>,
          <Button key="absent" onClick={() => modal.confirm({
            title: "Verified absent on Facebook?",
            content: "Only confirm after checking the Page. This enables a later manual retry.",
            onOk: () => act("absent", post)
          })}>Mark absent</Button>
        ] : [])
      ]}>
      <List.Item.Meta
        avatar={post.image_url ? <Image src={post.image_url} width={72} alt="Post image" /> : undefined}
        title={<Space><Tag>{post.status}</Tag><strong>{post.page_name || "Unresolved Page"}</strong>
          {post.scheduled_for_utc && <span>{new Date(post.scheduled_for_utc).toLocaleString()}</span>}</Space>}
        description={<><Typography.Paragraph ellipsis={{ rows: 3, expandable: true }}>{post.caption}</Typography.Paragraph>
          <Typography.Text type="secondary">Sheet ID: {post.external_id}{post.source_row ? ` · row ${post.source_row}` : ""}</Typography.Text>
          {post.last_error_message && <Alert type="warning" message={post.last_error_message} />}
          {post.writeback_error && <Alert type="warning" message={post.writeback_error} />}
          {post.facebook_post_id && <a href={`https://www.facebook.com/${encodeURIComponent(post.facebook_post_id)}`} target="_blank" rel="noreferrer">Facebook post {post.facebook_post_id}</a>}
        </>} />
    </List.Item>} />
  </div>;
}
