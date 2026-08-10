import { FacebookOutlined, SyncOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, Empty, List, Space, Tag, Typography } from "antd";

import {
  getCurrentFacebookPage,
  getFacebookAuthUrl,
  getFacebookPages,
  selectFacebookPage,
  syncFacebookPages
} from "../services/facebookService";

export function FacebookSettingsPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();

  const pagesQuery = useQuery({
    queryKey: ["facebook-pages"],
    queryFn: getFacebookPages
  });

  const currentPageQuery = useQuery({
    queryKey: ["facebook-current-page"],
    queryFn: getCurrentFacebookPage
  });

  const connectMutation = useMutation({
    mutationFn: getFacebookAuthUrl,
    onSuccess: ({ url }) => {
      window.open(url, "_blank", "noopener,noreferrer");
    },
    onError: () => {
      void message.error("Facebook connection could not be started.");
    }
  });

  const syncMutation = useMutation({
    mutationFn: syncFacebookPages,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["facebook-pages"] });
      await queryClient.invalidateQueries({ queryKey: ["facebook-current-page"] });
      void message.success("Facebook Pages synced.");
    },
    onError: () => {
      void message.error("Facebook Pages could not be synced.");
    }
  });

  const selectMutation = useMutation({
    mutationFn: selectFacebookPage,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["facebook-current-page"] });
    },
    onError: () => {
      void message.error("Page selection failed.");
    }
  });

  const pages = pagesQuery.data?.items ?? [];
  const currentPage = currentPageQuery.data?.item;
  const connected = pages.length > 0;

  return (
    <div className="settings-page">
      <div className="settings-header">
        <div>
          <Typography.Title level={2}>Facebook</Typography.Title>
        </div>
        <Space>
          <Tag color={connected ? "success" : "default"}>{connected ? "Connected" : "Disconnected"}</Tag>
          <Button
            icon={<FacebookOutlined />}
            type="primary"
            loading={connectMutation.isPending}
            onClick={() => connectMutation.mutate()}
          >
            Connect Facebook
          </Button>
          <Button
            icon={<SyncOutlined />}
            loading={syncMutation.isPending}
            onClick={() => syncMutation.mutate()}
          >
            Sync Pages
          </Button>
        </Space>
      </div>

      <section className="settings-section">
        <Typography.Title level={4}>Current Page</Typography.Title>
        <Typography.Text>{currentPage ? currentPage.name : "No Page selected"}</Typography.Text>
      </section>

      <section className="settings-section">
        <Typography.Title level={4}>Pages</Typography.Title>
        <List
          loading={pagesQuery.isLoading}
          dataSource={pages}
          locale={{ emptyText: <Empty description="No Facebook Pages synced" /> }}
          renderItem={(page) => {
            const isCurrent = currentPage?.page_id === page.page_id;
            return (
              <List.Item
                actions={[
                  <Button
                    key="select"
                    type={isCurrent ? "primary" : "default"}
                    disabled={isCurrent}
                    loading={selectMutation.isPending && !isCurrent}
                    onClick={() => selectMutation.mutate(page.page_id)}
                  >
                    {isCurrent ? "Current Page" : "Select"}
                  </Button>
                ]}
              >
                <List.Item.Meta
                  avatar={
                    page.picture_url ? (
                      <img className="facebook-page-avatar" src={page.picture_url} alt="" />
                    ) : undefined
                  }
                  title={page.name}
                  description={page.username ? `@${page.username}` : page.page_id}
                />
              </List.Item>
            );
          }}
        />
      </section>
    </div>
  );
}
