import { Navigate, Route, Routes } from "react-router-dom";

import { AppLayout } from "../layouts/AppLayout";
import { DashboardPage } from "../pages/DashboardPage";
import { FacebookSettingsPage } from "../pages/FacebookSettingsPage";
import { CustomerSegmentsPage } from "../pages/CustomerSegmentsPage";
import { MessengerInboxPage } from "../pages/MessengerInboxPage";
import { LoginPage } from "../pages/LoginPage";

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<AppLayout />}>
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/messenger" element={<MessengerInboxPage />} />
        <Route path="/settings/facebook" element={<FacebookSettingsPage />} />
        <Route path="/settings/segments" element={<CustomerSegmentsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  );
}
