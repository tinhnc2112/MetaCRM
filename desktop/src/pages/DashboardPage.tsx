import { Card, Typography } from "antd";

export function DashboardPage() {
  return (
    <div className="dashboard-page">
      <Card className="dashboard-card">
        <Typography.Title level={1}>MetaCRM</Typography.Title>
        <Typography.Title level={2}>Dashboard</Typography.Title>
      </Card>
    </div>
  );
}
