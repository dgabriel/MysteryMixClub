export interface RoundDetail {
  round_id: number;
  round_theme: string;
  points: number;
  song_title: string;
  artist_name: string;
}

export interface LeaderboardEntry {
  user_id: number;
  user_name: string;
  total_points: number;
  rounds_participated: number;
  round_details: RoundDetail[];
}

export interface LeagueLeaderboard {
  league_id: number;
  completed_rounds_count: number;
  leaderboard: LeaderboardEntry[];
}
