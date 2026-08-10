import { Layout } from "antd";
import { Outlet } from "react-router-dom";

import { AppHeader } from "../components/AppHeader";
import { AppSidebar } from "../components/AppSidebar";
import { useDeepLink } from "../hooks/useDeepLink";

export function AppLayout() {
  useDeepLink();

  return (
    <Layout className="app-shell">
      <AppSidebar />
      <Layout>
        <AppHeader />
        <Layout.Content className="app-content">
          <Outlet />
        </Layout.Content>
      </Layout>
    </Layout>
  );
}
