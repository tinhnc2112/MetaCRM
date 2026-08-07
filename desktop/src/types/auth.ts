export type AuthUser = {
  uuid: string;
  username: string;
  email: string;
  fullName?: string | null;
  avatarUrl?: string | null;
};

export type AuthTokens = {
  access_token: string;
  refresh_token: string;
  token_type: "bearer";
};

export type LoginRequest = {
  username: string;
  password: string;
};
