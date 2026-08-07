import { LockOutlined, UserOutlined } from "@ant-design/icons";
import { useMutation } from "@tanstack/react-query";
import { App, Button, Card, Form, Input, Typography } from "antd";
import { useNavigate } from "react-router-dom";

import { login } from "../services/authService";
import { useAuthStore } from "../stores/authStore";

type LoginFormValues = {
  username: string;
  password: string;
};

export function LoginPage() {
  const { message } = App.useApp();
  const navigate = useNavigate();
  const setSession = useAuthStore((state) => state.setSession);

  const loginMutation = useMutation({
    mutationFn: login,
    onSuccess: (tokens, values) => {
      setSession({
        username: values.username,
        accessToken: tokens.access_token,
        refreshToken: tokens.refresh_token
      });
      navigate("/dashboard");
    },
    onError: () => {
      void message.error("Sign in failed. Check your credentials and try again.");
    }
  });

  const handleFinish = (values: LoginFormValues) => {
    loginMutation.mutate(values);
  };

  return (
    <main className="login-page">
      <Card className="login-card">
        <Typography.Title level={2}>MetaCRM</Typography.Title>
        <Typography.Paragraph type="secondary">
          Sign in to continue to your workspace.
        </Typography.Paragraph>
        <Form layout="vertical" onFinish={handleFinish} requiredMark={false}>
          <Form.Item
            label="Username or email"
            name="username"
            rules={[{ required: true, message: "Enter your username or email" }]}
          >
            <Input prefix={<UserOutlined />} autoComplete="username" size="large" />
          </Form.Item>
          <Form.Item
            label="Password"
            name="password"
            rules={[{ required: true, message: "Enter your password" }]}
          >
            <Input.Password prefix={<LockOutlined />} autoComplete="current-password" size="large" />
          </Form.Item>
          <Button type="primary" htmlType="submit" size="large" loading={loginMutation.isPending} block>
            Sign in
          </Button>
        </Form>
      </Card>
    </main>
  );
}
