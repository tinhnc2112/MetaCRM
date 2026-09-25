import { App, Button, Layout, Space, Typography } from "antd";
import { useLocation, useNavigate } from "react-router-dom";

import { useAuthStore } from "../stores/authStore";
import { logout } from "../services/authService";

export function AppHeader() {
  const navigate = useNavigate();
  const location = useLocation();
  const clearSession = useAuthStore((state) => state.clearSession);
  const refreshToken = useAuthStore((state) => state.session?.refreshToken);
  const { message } = App.useApp();
  const signOut = async () => {
    try {
      if (refreshToken) await logout(refreshToken);
    } catch {
      void message.warning("Server sign out could not be confirmed. Your local session was cleared.");
    } finally {
      clearSession();
      navigate("/login");
    }
  };
  const title = getHeaderTitle(location.pathname);

  return (
    <Layout.Header className="app-header">
      <Typography.Text strong>{title}</Typography.Text>
      <Space>
        <Button
          onClick={() => { void signOut(); }}
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
  if (pathname.startsWith("/products")) {
    return "Products";
  }
  if (pathname.startsWith("/orders")) {
    return "Orders";
  }
  if (pathname.startsWith("/settings/facebook")) {
    return "Facebook Settings";
  }
  if (pathname.startsWith("/settings/carriers")) {
    return "Carrier Settings";
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
