import { Song, SongInput } from './song';

export enum RoundStatus {
  PENDING = 'pending',
  ACTIVE = 'active',
  COMPLETED = 'completed'
}

export interface Round {
  id: number;
  league_id: number;
  league_name?: string | null;
  theme: string;
  description: string | null;
  order: number;
  status: RoundStatus;

  // Timestamps (null until round starts)
  started_at: string | null;
  submission_deadline: string | null;
  voting_started_at: string | null;
  voting_deadline: string | null;
  completed_at: string | null;

  created_at: string;
  submission_count?: number;
  user_has_submitted?: boolean;
  user_has_voted?: boolean;
  is_admin?: boolean;
  songs_per_round?: number;  // From league settings
}

export interface Submission {
  id: number;
  round_id: number;
  user_id: number;
  submitted_at: string;
  songs: Song[];
  user_name?: string | null;
}

export interface RoundDetail extends Round {
  submissions: Submission[];
}

export interface RoundCreate {
  league_id: number;
  theme: string;
  description?: string;
  order?: number;  // Optional, defaults to last position
}

export interface RoundUpdate {
  theme?: string;
  description?: string;
  // Note: deadlines are auto-calculated, not editable
}

export interface RoundReorderItem {
  id: number;
  order: number;
}

export interface SubmissionCreate {
  round_id: number;
  songs: SongInput[];
}
