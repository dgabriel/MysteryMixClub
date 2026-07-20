import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { CreateClubScreen } from "./CreateClubScreen";
import { ApiError, createClub } from "../services/api";

/**
 * Protected create-club route. Submits the form to the backend and, on
 * success, drops the user straight into the new club's home (replace so the
 * empty form isn't in the back stack). An ApiError keeps the user on the screen
 * with a calm message.
 */
export function CreateClubRoute() {
  const navigate = useNavigate();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(input: {
    name: string;
    description?: string;
    total_mixes: number;
    votes_per_player: number;
    songs_per_submission: number;
    default_vibe_mode: boolean;
    submission_window_hours: number;
    voting_window_hours: number;
  }) {
    setSubmitting(true);
    setError(null);
    try {
      const club = await createClub(input);
      navigate(`/clubs/${club.id}`, { replace: true });
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "couldn't create the club. try again.",
      );
      setSubmitting(false);
    }
  }

  return (
    <CreateClubScreen
      onSubmit={handleSubmit}
      submitting={submitting}
      error={error}
      onCancel={() => navigate("/home")}
    />
  );
}
