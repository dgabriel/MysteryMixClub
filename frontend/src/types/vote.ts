export interface VoteCreate {
  round_id: number;
  ranked_submissions: number[];  // Array of submission IDs in ranked order [1st, 2nd, 3rd]
}

export interface VoteUpdate {
  ranked_submissions: number[];
}

export interface UserVotesResponse {
  round_id: number;
  ranked_submissions: number[];
  voted_at: string;
}
