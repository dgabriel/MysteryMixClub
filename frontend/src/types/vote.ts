export interface VoteCreate {
  round_id: number;
  ranked_songs: number[];  // Array of song IDs in ranked order [1st, 2nd, 3rd]
}

export interface VoteUpdate {
  ranked_songs: number[];
}

export interface UserVotesResponse {
  round_id: number;
  ranked_songs: number[];
  voted_at: string;
}
