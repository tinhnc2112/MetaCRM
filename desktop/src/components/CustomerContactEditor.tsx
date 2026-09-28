import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Input, Modal } from "antd";
import axios from "axios";
import { useEffect, useState } from "react";

import { updateCustomerContact } from "../services/customerService";
import type { CustomerContactUpdate, CustomerSummary } from "../types/customer";

type ContactDraft = {
  name: string;
  phone: string;
  email: string;
  address_line: string;
  ward: string;
  district: string;
  province: string;
  postal_code: string;
  country_code: string;
  note: string;
};

function draftFromCustomer(customer: CustomerSummary): ContactDraft {
  const address = customer.default_shipping_address;
  return {
    name: customer.name ?? "",
    phone: customer.phone ?? "",
    email: customer.email ?? "",
    address_line: address?.address_line ?? "",
    ward: address?.ward ?? "",
    district: address?.district ?? "",
    province: address?.province ?? "",
    postal_code: address?.postal_code ?? "",
    country_code: address?.country_code ?? "VN",
    note: address?.note ?? ""
  };
}

function optional(value: string): string | null {
  return value.trim() || null;
}

function payloadFromDraft(draft: ContactDraft): CustomerContactUpdate {
  const hasAddress = [draft.address_line, draft.ward, draft.district,
    draft.province, draft.postal_code, draft.note].some((value) => Boolean(optional(value)));
  return {
    name: optional(draft.name),
    phone: optional(draft.phone),
    email: optional(draft.email),
    default_shipping_address: hasAddress ? {
      address_line: optional(draft.address_line),
      ward: optional(draft.ward),
      district: optional(draft.district),
      province: optional(draft.province),
      postal_code: optional(draft.postal_code),
      country_code: optional(draft.country_code)?.toUpperCase() ?? null,
      note: optional(draft.note)
    } : null
  };
}

function validate(draft: ContactDraft): string | null {
  if (draft.name.length > 255 || draft.email.length > 255 || draft.phone.length > 32) {
    return "A contact field is too long.";
  }
  const phone = optional(draft.phone);
  if (phone && (!/^[+\d\s().-]+$/.test(phone) || !/^\d{8,15}$/.test(phone.replace(/\D/g, "")))) {
    return "Phone must contain 8–15 digits and only phone punctuation.";
  }
  const email = optional(draft.email);
  if (email && (!/^[^@\s]+@[^@\s]+$/.test(email))) {
    return "Enter a valid email address.";
  }
  const country = optional(draft.country_code);
  if (country && !/^[a-zA-Z]{2}$/.test(country)) return "Country code must contain two letters.";
  if (draft.address_line.length > 5000 || draft.note.length > 5000 ||
      [draft.ward, draft.district, draft.province].some((part) => part.length > 255) ||
      draft.postal_code.length > 32) return "A shipping address field is too long.";
  return null;
}

export function CustomerContactEditor({
  customer, currentPageId, open, onClose
}: {
  customer: CustomerSummary;
  currentPageId: string;
  open: boolean;
  onClose: () => void;
}) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<ContactDraft>(() => draftFromCustomer(customer));
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (open) {
      setDraft(draftFromCustomer(customer));
      setError(null);
    }
  }, [open, customer.uuid, currentPageId]);

  const mutation = useMutation({
    mutationFn: (input: CustomerContactUpdate) => updateCustomerContact(customer.uuid, input),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["customer-profile", currentPageId] }),
        queryClient.invalidateQueries({ queryKey: ["customer-list", currentPageId] })
      ]);
      onClose();
      void message.success("Customer contact saved.");
    },
    onError: (failure) => {
      setError(axios.isAxiosError(failure) && failure.response?.status === 403
        ? "You are not authorized to edit this customer."
        : "Customer contact could not be saved. Check the fields and try again.");
    }
  });

  const change = (field: keyof ContactDraft, value: string) => {
    setDraft((current) => ({ ...current, [field]: value }));
    setError(null);
  };
  const submit = () => {
    const validationError = validate(draft);
    if (validationError) {
      setError(validationError);
      return;
    }
    mutation.mutate(payloadFromDraft(draft));
  };

  return (
    <Modal title="Edit customer contact" open={open}
      onCancel={() => { if (!mutation.isPending) onClose(); }} onOk={submit}
      okText="Save customer" okButtonProps={{ loading: mutation.isPending }}
      cancelButtonProps={{ disabled: mutation.isPending }} closable={!mutation.isPending}
      maskClosable={!mutation.isPending}>
      {error && <Alert type="error" message={error} showIcon />}
      {([
        ["name", "Name", 255], ["phone", "Phone", 32], ["email", "Email", 255],
        ["address_line", "Default address", 5000], ["ward", "Ward", 255],
        ["district", "District", 255], ["province", "Province", 255],
        ["postal_code", "Postal code", 32], ["country_code", "Country code", 2],
        ["note", "Delivery note", 5000]
      ] as const).map(([field, label, length]) => (
        <label key={field} style={{ display: "block", marginTop: 12 }}>
          {label}
          <Input value={draft[field]} maxLength={length} disabled={mutation.isPending}
            onChange={(event) => change(field, event.target.value)} />
        </label>
      ))}
    </Modal>
  );
}
