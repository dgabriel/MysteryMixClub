export enum RoundStatus {
  PENDING = 'pending',
  ACTIVE = 'active',
  COMPLETED = 'completed'
}

export interface Round {
  id: number;
  league_id: number;
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
  is_admin?: boolean;
}

export interface Submission {
  id: number;
  round_id: number;
  user_id: number;
  song_title: string;
  artist_name: string;
  album_name: string | null;
  songlink_url: string;
  spotify_url: string | null;
  apple_music_url: string | null;
  youtube_url: string | null;
  artwork_url: string | null;
  submitted_at: string;
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
  song_title: string;
  artist_name: string;
  album_name?: string;
  songlink_url: string;
  spotify_url?: string;
  apple_music_url?: string;
  youtube_url?: string;
  artwork_url?: string;
}

export interface SubmissionUpdate {
  song_title?: string;
  artist_name?: string;
  album_name?: string;
  songlink_url?: string;
  spotify_url?: string;
  apple_music_url?: string;
  youtube_url?: string;
  artwork_url?: string;
}
