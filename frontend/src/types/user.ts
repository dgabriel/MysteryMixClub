export interface User {
  id: number;
  email: string;
  name: string;
  avatar_url?: string | null;
  is_super_user: boolean;
  is_active: boolean;
  created_at: string;
  tidal_connected?: boolean;
}

export interface UserCreate {
  email: string;
  name: string;
  password: string;
}

export interface UserUpdate {
  name?: string;
  avatar_url?: string | null;
}
