/** Authentication utilities and types. */

export interface LoginCredentials {
  email: string;
  password: string;
}

export interface User {
  id: number;
  email: string;
  username: string;
  first_name: string;
  last_name: string;
  status: string;
  is_admin: boolean;
  is_super_admin: boolean;
  created_at: string;
  profile_attributes: Record<string, unknown>;
}

export interface Session {
  id: number;
  user_id: number;
  created_at: string;
  last_activity_at: string;
  expires_at: string;
  is_expired: boolean;
  is_admin_session: boolean;
}

export interface AuthResponse {
  user: User;
  session: Session;
  success: boolean;
}

export interface AuditEvent {
  id: number;
  timestamp: string;
  actor_id: string | null;
  actor_type: string | null;
  actor_ip_address: string | null;
  action: string;
  event_type: string;
  target_id: string | null;
  target_type: string | null;
  metadata: Record<string, unknown> | null;
}

/** Check if the current session is authenticated */
export async function checkAuth(): Promise<boolean> {
  try {
    const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/health`, {
      credentials: "include",
    });
    return response.ok;
  } catch {
    return false;
  }
}