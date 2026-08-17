import { Button, Layout, Space, Typography } from "antd";
import { useLocation, useNavigate } from "react-router-dom";

import { useAuthStore } from "../stores/authStore";

export function AppHeader() {
  const navigate = useNavigate();
  const location = useLocation();
  const clearSession = useAuthStore((state) => state.clearSession);
  const title = getHeaderTitle(location.pathname);

  return (
    <Layout.Header className="app-header">
      <Typography.Text strong>{title}</Typography.Text>
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

function getHeaderTitle(pathname: string): string {
  if (pathname.startsWith("/customers")) {
    return "Customers";
  }
  if (pathname.startsWith("/messenger")) {
    return "Messenger Inbox";
  }
  if (pathname.startsWith("/settings/facebook")) {
    return "Facebook Settings";
  }
  if (pathname.startsWith("/settings/segments")) {
    return "Customer Segments";
  }
  if (pathname.startsWith("/settings/duplicates")) {
    return "Customer Duplicates";
  }
  if (pathname.startsWith("/dashboard")) {
    return "Dashboard";
  }
  return "MetaCRM";
}
