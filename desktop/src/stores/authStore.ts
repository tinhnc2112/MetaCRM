import { create } from "zustand";

type AuthSession = {
  username: string;
  accessToken: string;
  refreshToken: string;
};

type AuthStore = {
  session: AuthSession | null;
  setSession: (session: AuthSession) => void;
  clearSession: () => void;
};

export const useAuthStore = create<AuthStore>((set) => ({
  session: null,
  setSession: (session) => set({ session }),
  clearSession: () => set({ session: null })
}));
