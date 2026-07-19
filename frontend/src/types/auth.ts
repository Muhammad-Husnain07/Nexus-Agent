export interface LoginRequest {
  email: string;
}

export interface LoginResponse {
  access_token: string;
  refresh_token: string;
  user: UserProfile;
}

export interface UserProfile {
  id: string;
  email: string;
  role: "tenant_admin" | "developer" | "end_user" | "viewer";
  tenant_id: string;
  created_at?: string;
}

export interface RefreshRequest {
  refresh_token: string;
}

export interface RefreshResponse {
  access_token: string;
  refresh_token: string;
}
