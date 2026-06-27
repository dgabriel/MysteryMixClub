import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { CreateLeagueScreen } from "./CreateLeagueScreen";
import { ApiError, createLeague } from "../services/api";

/**
 * Protected create-league route. Submits the form to the backend and, on
 * success, drops the user straight into the new league's home (replace so the
 * empty form isn't in the back stack). An ApiError keeps the user on the screen
 * with a calm message.
 */
export function CreateLeagueRoute() {
  const navigate = useNavigate();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(input: {
    name: string;
    description?: string;
    total_rounds: number;
    votes_per_player: number;
    songs_per_submission: number;
    default_vibe_mode: boolean;
  }) {
    setSubmitting(true);
    setError(null);
    try {
      const league = await createLeague(input);
      navigate(`/leagues/${league.id}`, { replace: true });
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "couldn't create the league. try again.",
      );
      setSubmitting(false);
    }
  }

  return (
    <CreateLeagueScreen
      onSubmit={handleSubmit}
      submitting={submitting}
      error={error}
      onCancel={() => navigate("/home")}
    />
  );
}
