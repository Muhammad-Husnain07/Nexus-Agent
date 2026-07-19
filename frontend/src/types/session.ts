export interface Session {
  id: string;
  tenant_id: string;
  user_id: string;
  title: string;
  status: "active" | "archived";
  metadata?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface SessionCreatePayload {
  title?: string;
  session_id?: string;
}

export interface SessionUpdatePayload {
  title?: string;
  status?: "active" | "archived";
}
