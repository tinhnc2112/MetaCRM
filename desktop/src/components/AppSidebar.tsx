import {
  DashboardOutlined,
  FacebookOutlined,
  FilterOutlined,
  MessageOutlined,
  ShoppingCartOutlined,
  ShoppingOutlined,
  SettingOutlined,
  TruckOutlined,
  TeamOutlined,
  UserSwitchOutlined
} from "@ant-design/icons";
import { Layout, Menu } from "antd";
import { useLocation, useNavigate } from "react-router-dom";

export function AppSidebar() {
  const location = useLocation();
  const navigate = useNavigate();
  const selectedKey = location.pathname.startsWith("/customers")
    ? "/customers"
    : location.pathname.startsWith("/messenger")
      ? "/messenger"
      : location.pathname;

  return (
    <Layout.Sider className="app-sidebar" width={232}>
      <div className="sidebar-brand">MetaCRM</div>
      <Menu
        mode="inline"
        defaultOpenKeys={["settings"]}
        selectedKeys={[selectedKey]}
        onClick={({ key }) => navigate(key)}
        items={[
          {
            key: "/dashboard",
            icon: <DashboardOutlined />,
            label: "Dashboard"
          },
          {
            key: "/customers",
            icon: <TeamOutlined />,
            label: "Customers"
          },
          {
            key: "/messenger",
            icon: <MessageOutlined />,
            label: "Messenger / Inbox"
          },
          {
            key: "/products",
            icon: <ShoppingOutlined />,
            label: "Products"
          },
          {
            key: "/orders",
            icon: <ShoppingCartOutlined />,
            label: "Orders"
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
              },
              {
                key: "/settings/carriers",
                icon: <TruckOutlined />,
                label: "Carriers"
              },
              {
                key: "/settings/segments",
                icon: <FilterOutlined />,
                label: "Customer Segments"
              },
              {
                key: "/settings/duplicates",
                icon: <UserSwitchOutlined />,
                label: "Customer Duplicates"
              }
            ]
          }
        ]}
      />
    </Layout.Sider>
  );
}
