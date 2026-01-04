export interface SubmissionResult {
  submission_id: number;
  song_title: string;
  artist_name: string;
  submitter_id: number;
  submitter_name: string;
  total_points: number;
  votes_received: Array<{
    voter_id: number;
    voter_name: string;
    rank: number;
  }>;
  first_place_votes: number;
  second_place_votes: number;
  third_place_votes: number;
}

export interface RoundResults {
  round_id: number;
  round_theme: string;
  results: SubmissionResult[];
}
