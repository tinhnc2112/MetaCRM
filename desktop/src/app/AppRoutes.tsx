import { Navigate, Route, Routes } from "react-router-dom";

import { AppLayout } from "../layouts/AppLayout";
import { DashboardPage } from "../pages/DashboardPage";
import { FacebookSettingsPage } from "../pages/FacebookSettingsPage";
import { CustomerSegmentsPage } from "../pages/CustomerSegmentsPage";
import { CustomerDuplicatesPage } from "../pages/CustomerDuplicatesPage";
import { CustomerBrowserPage } from "../pages/CustomerBrowserPage";
import { MessengerInboxPage } from "../pages/MessengerInboxPage";
import { LoginPage } from "../pages/LoginPage";
import { ProductManagementPage } from "../pages/ProductManagementPage";
import { OrderOperationsPage } from "../pages/OrderOperationsPage";
import { CarrierSettingsPage } from "../pages/CarrierSettingsPage";

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<AppLayout />}>
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/customers" element={<CustomerBrowserPage />} />
        <Route path="/customers/:customerId" element={<CustomerBrowserPage />} />
        <Route path="/messenger" element={<MessengerInboxPage />} />
        <Route path="/products" element={<ProductManagementPage />} />
        <Route path="/orders" element={<OrderOperationsPage />} />
        <Route path="/settings/facebook" element={<FacebookSettingsPage />} />
        <Route path="/settings/carriers" element={<CarrierSettingsPage />} />
        <Route path="/settings/segments" element={<CustomerSegmentsPage />} />
        <Route path="/settings/duplicates" element={<CustomerDuplicatesPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  );
}
