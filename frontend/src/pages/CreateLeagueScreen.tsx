import { type FormEvent, useState } from "react";
import { Button } from "../components/Button";
import { TextField } from "../components/TextField";
import { ConcentricRings } from "../components/ConcentricRings";

type CreateLeagueInput = {
  name: string;
  description?: string;
  total_rounds: number;
  votes_per_player: number;
};

type CreateLeagueScreenProps = {
  onSubmit: (input: CreateLeagueInput) => void;
  submitting: boolean;
  error?: string | null;
  onCancel: () => void;
};

export function CreateLeagueScreen({
  onSubmit,
  submitting,
  error,
  onCancel,
}: CreateLeagueScreenProps) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [totalRounds, setTotalRounds] = useState("6");
  const [votesPerPlayer, setVotesPerPlayer] = useState("3");
  const [guard, setGuard] = useState<string | null>(null);

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const trimmedName = name.trim();
    const rounds = Number(totalRounds);
    const votes = Number(votesPerPlayer);

    if (!trimmedName) {
      setGuard("a league needs a name.");
      return;
    }
    if (!Number.isFinite(rounds) || rounds < 1) {
      setGuard("rounds must be at least 1.");
      return;
    }
    if (!Number.isFinite(votes) || votes < 1) {
      setGuard("votes per player must be at least 1.");
      return;
    }

    setGuard(null);
    const trimmedDescription = description.trim();
    onSubmit({
      name: trimmedName,
      ...(trimmedDescription ? { description: trimmedDescription } : {}),
      total_rounds: rounds,
      votes_per_player: votes,
    });
  }

  return (
    <main className="min-h-screen flex flex-col items-center justify-center px-4 py-8 sm:px-8">
      <div className="w-full max-w-sm">
        {/* Motif — the screen's single Rust use lives in the off-center ring dot. */}
        <ConcentricRings size={72} accent className="mx-auto" />

        <h1 className="mt-8 text-center font-serif text-[34px] leading-tight">new league</h1>

        <form onSubmit={handleSubmit} className="mt-10 space-y-8">
          <TextField
            id="league-name"
            label="name"
            name="name"
            placeholder="what's this league called?"
            value={name}
            onChange={(e) => setName(e.target.value)}
            disabled={submitting}
          />

          <TextField
            id="league-description"
            label="description (optional)"
            name="description"
            placeholder="a line about the vibe"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            disabled={submitting}
          />

          <TextField
            id="league-total-rounds"
            label="rounds"
            name="total_rounds"
            type="number"
            min={1}
            value={totalRounds}
            onChange={(e) => setTotalRounds(e.target.value)}
            disabled={submitting}
          />

          <TextField
            id="league-votes-per-player"
            label="votes per player"
            name="votes_per_player"
            type="number"
            min={1}
            value={votesPerPlayer}
            onChange={(e) => setVotesPerPlayer(e.target.value)}
            disabled={submitting}
          />

          {guard ? (
            <p role="alert" className="font-mono text-[11px] text-ink">
              {guard}
            </p>
          ) : null}

          {error ? (
            <p role="alert" className="font-mono text-[11px] text-ink">
              {error}
            </p>
          ) : null}

          <div className="space-y-4">
            <Button type="submit" disabled={submitting} className="w-full">
              {submitting ? "creating…" : "create"}
            </Button>
            <div className="text-center">
              <Button variant="ghost" type="button" onClick={onCancel} disabled={submitting}>
                cancel
              </Button>
            </div>
          </div>
        </form>
      </div>
    </main>
  );
}
