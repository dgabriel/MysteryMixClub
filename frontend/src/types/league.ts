import { User } from './user';

export interface League {
  id: number;
  name: string;
  description?: string | null;
  invite_code: string;
  created_by_id: number;
  created_at: string;
  member_count?: number;
  is_member?: boolean;
  is_admin?: boolean;
}

export interface LeagueMember {
  id: number;
  league_id: number;
  user_id: number;
  is_admin: boolean;
  joined_at: string;
  user_name?: string;
  user_email?: string;
}

export interface LeagueDetail extends League {
  members: LeagueMember[];
}

export interface LeagueCreate {
  name: string;
  description?: string;
}

export interface LeagueUpdate {
  name?: string;
  description?: string;
}

export interface JoinLeagueRequest {
  invite_code: string;
}
