import { Button, Layout, Space, Typography } from "antd";
import { useNavigate } from "react-router-dom";

import { useAuthStore } from "../stores/authStore";

export function AppHeader() {
  const navigate = useNavigate();
  const clearSession = useAuthStore((state) => state.clearSession);

  return (
    <Layout.Header className="app-header">
      <Typography.Text strong>Dashboard</Typography.Text>
      <Space>
        <Button
          onClick={() => {
            clearSession();
            navigate("/login");
          }}
        >
          Sign out
        </Button>
      </Space>
    </Layout.Header>
  );
}
