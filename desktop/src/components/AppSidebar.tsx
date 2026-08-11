import { DashboardOutlined, FacebookOutlined, MessageOutlined, SettingOutlined } from "@ant-design/icons";
import { Layout, Menu } from "antd";
import { useLocation, useNavigate } from "react-router-dom";

export function AppSidebar() {
  const location = useLocation();
  const navigate = useNavigate();

  return (
    <Layout.Sider className="app-sidebar" width={232}>
      <div className="sidebar-brand">MetaCRM</div>
      <Menu
        mode="inline"
        selectedKeys={[location.pathname]}
        onClick={({ key }) => navigate(key)}
        items={[
          {
            key: "/dashboard",
            icon: <DashboardOutlined />,
            label: "Dashboard"
          },
          {
            key: "/messenger",
            icon: <MessageOutlined />,
            label: "Messenger / Inbox"
          },
          {
            key: "settings",
            icon: <SettingOutlined />,
            label: "Settings",
            children: [
              {
                key: "/settings/facebook",
                icon: <FacebookOutlined />,
                label: "Facebook"
              }
            ]
          }
        ]}
      />
    </Layout.Sider>
  );
}
