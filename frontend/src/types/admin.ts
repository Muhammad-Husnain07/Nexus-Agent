export interface Tenant {
  id: string;
  name: string;
  slug: string;
  status?: string;
  created_at: string;
  updated_at?: string;
}

export interface TenantCreatePayload {
  name: string;
  slug: string;
}

export interface AdminUser {
  id: string;
  tenant_id: string;
  email: string;
  role: string;
  created_at: string;
}

export interface AdminUserCreatePayload {
  email: string;
  role: string;
}

export interface ApiKey {
  id: string;
  label?: string;
  scopes?: string[];
  role?: string;
  created_at: string;
  last_used_at?: string;
  expires_at?: string;
}

export interface AuditLogEntry {
  id: string;
  action: string;
  resource_type: string;
  resource_id?: string;
  actor_id?: string;
  tenant_id?: string;
  payload?: Record<string, unknown>;
  created_at: string;
}
