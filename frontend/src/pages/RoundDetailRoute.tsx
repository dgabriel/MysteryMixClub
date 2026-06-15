import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  ApiError,
  getLeague,
  getLeagueMembers,
  getMySubmission,
  getPlaylist,
  getRound,
  getRoundSubmissions,
  submitSong,
  updateRound,
  type League,
  type LeagueMember,
  type PlaylistEntry,
  type ResolvedSong,
  type Round,
  type RoundState,
  type SubmissionResult,
} from "../services/api";
import { useAuth } from "../hooks/useAuth";
import { Button } from "../components/Button";
import { Badge } from "../components/Badge";
import { Card } from "../components/Card";
import { ConcentricRings } from "../components/ConcentricRings";
import { SongSearchCard } from "../components/songs/SongSearchCard";

const STATE_LABEL: Record<RoundState, string> = {
  open_submission: "submissions open",
  open_voting: "voting open",
  closed: "closed",
};

const PLATFORM_LABELS: { key: string; label: string }[] = [
  { key: "spotify", label: "Spotify" },
  { key: "appleMusic", label: "Apple Music" },
  { key: "deezer", label: "Deezer" },
  { key: "youtube", label: "YouTube" },
];

/**
 * Round detail (`/rounds/:id`). State-aware:
 *  - open_submission → submit/replace your song (organizer can open voting)
 *  - open_voting     → the anonymous, shuffled playlist (organizer can close)
 *  - closed          → revealed submissions
 * Self-contained: loads the round + league (for organizer/name) plus the
 * state-specific data, and wires submit / advance back to the API.
 */
export function RoundDetailRoute() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { userId } = useAuth();

  const [round, setRound] = useState<Round | null>(null);
  const [league, setLeague] = useState<League | null>(null);
  const [mine, setMine] = useState<SubmissionResult | null>(null);
  const [playlist, setPlaylist] = useState<PlaylistEntry[]>([]);
  const [reveal, setReveal] = useState<SubmissionResult[]>([]);
  const [members, setMembers] = useState<LeagueMember[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [submitting, setSubmitting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [advancing, setAdvancing] = useState(false);

  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    setError(null);
    try {
      const loadedRound = await getRound(id);
      const loadedLeague = await getLeague(loadedRound.league_id);
      setRound(loadedRound);
      setLeague(loadedLeague);

      if (loadedRound.state === "open_submission") {
        setMine(await getMySubmission(id));
      } else if (loadedRound.state === "open_voting") {
        setPlaylist((await getPlaylist(id)).entries);
      } else {
        const [subs, mems] = await Promise.all([
          getRoundSubmissions(id),
          getLeagueMembers(loadedRound.league_id),
        ]);
        setReveal(subs);
        setMembers(mems);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "couldn't load this round.");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  const isOrganizer = !!userId && !!league && league.organizer_id === userId;

  async function handleSubmit(song: ResolvedSong) {
    if (!id || !song.isrc) {
      setActionError("this song is missing an ID and can't be submitted.");
      return;
    }
    setSubmitting(true);
    setActionError(null);
    try {
      const result = await submitSong(id, {
        title: song.title,
        artist: song.artist ?? "",
        isrc: song.isrc,
        album: song.album,
        album_art_url: song.thumbnail_url,
      });
      setMine(result);
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "couldn't submit. try again.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleAdvance(next: RoundState) {
    if (!id) return;
    setAdvancing(true);
    setActionError(null);
    try {
      await updateRound(id, { state: next });
      await load();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "couldn't update the round.");
      setAdvancing(false);
    }
  }

  if (loading) {
    return (
      <main className="flex min-h-screen items-center justify-center px-4 sm:px-8">
        <ConcentricRings size={88} spinning className="mx-auto" />
      </main>
    );
  }

  if (error || !round) {
    return (
      <main className="flex min-h-screen flex-col items-center justify-center px-4 text-center sm:px-8">
        <p className="font-mono text-[13px] font-light text-muted">{error ?? "round not found."}</p>
        <div className="mt-6">
          <Button variant="ghost" type="button" onClick={() => navigate("/home")}>
            home
          </Button>
        </div>
      </main>
    );
  }

  return (
    <div className="flex min-h-screen flex-col">
      <header className="px-4 py-4 sm:px-8">
        <Button
          variant="ghost"
          type="button"
          onClick={() => navigate(`/leagues/${round.league_id}`)}
        >
          back
        </Button>
      </header>

      <main className="mx-auto w-full max-w-lg px-4 pb-16 sm:px-8">
        <span className="font-mono uppercase tracking-label text-[9px] text-muted">
          round {round.round_number}
          {league ? ` · ${league.name}` : ""}
        </span>
        <div className="mt-1 flex items-start justify-between gap-4">
          <h1 className="font-serif text-[32px] leading-tight text-ink">{round.theme}</h1>
          <div className="shrink-0 pt-2">
            <Badge>{STATE_LABEL[round.state]}</Badge>
          </div>
        </div>

        {isOrganizer ? (
          <OrganizerControls state={round.state} advancing={advancing} onAdvance={handleAdvance} />
        ) : null}

        {actionError ? (
          <p role="alert" className="mt-6 font-mono text-[11px] text-ink">
            {actionError}
          </p>
        ) : null}

        <section className="mt-10">
          {round.state === "open_submission" ? (
            <SubmissionSection
              mine={mine}
              submitting={submitting}
              onSubmit={handleSubmit}
              onChange={() => setMine(null)}
            />
          ) : round.state === "open_voting" ? (
            <PlaylistSection entries={playlist} />
          ) : (
            <RevealSection submissions={reveal} members={members} userId={userId} />
          )}
        </section>
      </main>
    </div>
  );
}

function OrganizerControls({
  state,
  advancing,
  onAdvance,
}: {
  state: RoundState;
  advancing: boolean;
  onAdvance: (next: RoundState) => void;
}) {
  if (state === "closed") return null;
  const next: RoundState = state === "open_submission" ? "open_voting" : "closed";
  const label = state === "open_submission" ? "open voting" : "close round";
  return (
    <div className="mt-6 border-t border-border pt-6">
      <Button type="button" onClick={() => onAdvance(next)} disabled={advancing}>
        {advancing ? "…" : label}
      </Button>
    </div>
  );
}

function SubmissionSection({
  mine,
  submitting,
  onSubmit,
  onChange,
}: {
  mine: SubmissionResult | null;
  submitting: boolean;
  onSubmit: (song: ResolvedSong) => void;
  onChange: () => void;
}) {
  if (mine) {
    return (
      <Card>
        <span className="font-mono uppercase tracking-label text-[9px] text-muted">
          your submission
        </span>
        <h2 className="mt-1 font-serif text-[20px] leading-tight text-ink">{mine.title}</h2>
        {mine.artist ? (
          <p className="mt-1 font-mono text-[11px] font-light text-muted">{mine.artist}</p>
        ) : null}
        <div className="mt-3">
          <Badge>{mine.participation_mode}</Badge>
        </div>
        <button
          type="button"
          onClick={onChange}
          className="mt-5 font-mono uppercase tracking-ui text-[11px] text-sage underline underline-offset-[3px] transition-colors duration-150 hover:text-ink"
        >
          change song
        </button>
      </Card>
    );
  }
  return (
    <SongSearchCard
      eyebrow="this round"
      heading="submit a song"
      onSubmit={onSubmit}
      submitting={submitting}
    />
  );
}

function PlatformLinks({ entry }: { entry: PlaylistEntry }) {
  const available = PLATFORM_LABELS.filter(
    (p) => entry.platforms[p.key as keyof typeof entry.platforms],
  );
  return (
    <ul className="mt-3 flex flex-wrap gap-2">
      {available.map((p) => (
        <li key={p.key}>
          <a
            href={entry.platforms[p.key as keyof typeof entry.platforms]}
            target="_blank"
            rel="noopener noreferrer"
            aria-label={`open ${entry.title} on ${p.label} (opens in a new tab)`}
            className="inline-flex items-center rounded-[2px] border border-border px-2.5 py-1 font-mono uppercase tracking-ui text-[11px] text-ink transition-colors duration-150 hover:bg-sage-pale"
          >
            {p.label}
          </a>
        </li>
      ))}
    </ul>
  );
}

function PlaylistSection({ entries }: { entries: PlaylistEntry[] }) {
  if (entries.length === 0) {
    return <p className="font-mono text-[13px] font-light text-muted">no submissions yet</p>;
  }
  return (
    <>
      <h2 className="font-mono uppercase tracking-label text-[9px] text-muted">
        playlist ({entries.length})
      </h2>
      <ul className="mt-4 space-y-4">
        {entries.map((entry) => (
          <li key={entry.submission_id}>
            <Card>
              <h3 className="font-serif text-[18px] leading-tight text-ink">{entry.title}</h3>
              {entry.artist ? (
                <p className="mt-1 font-mono text-[11px] font-light text-muted">{entry.artist}</p>
              ) : null}
              <PlatformLinks entry={entry} />
            </Card>
          </li>
        ))}
      </ul>
    </>
  );
}

function RevealSection({
  submissions,
  members,
  userId,
}: {
  submissions: SubmissionResult[];
  members: LeagueMember[];
  userId: string | null;
}) {
  if (submissions.length === 0) {
    return <p className="font-mono text-[13px] font-light text-muted">no submissions</p>;
  }
  const nameFor = (id: string) =>
    id === userId ? "you" : (members.find((m) => m.user_id === id)?.display_name ?? "someone");
  return (
    <>
      <h2 className="font-mono uppercase tracking-label text-[9px] text-muted">
        submissions ({submissions.length})
      </h2>
      <ul className="mt-4 space-y-4">
        {submissions.map((s) => (
          <li key={s.id}>
            <Card>
              <span className="font-mono uppercase tracking-label text-[9px] text-muted">
                {nameFor(s.user_id)}
              </span>
              <h3 className="mt-1 font-serif text-[18px] leading-tight text-ink">{s.title}</h3>
              {s.artist ? (
                <p className="mt-1 font-mono text-[11px] font-light text-muted">{s.artist}</p>
              ) : null}
              {s.note ? (
                <p className="mt-2 font-mono text-[11px] font-light text-ink">“{s.note}”</p>
              ) : null}
            </Card>
          </li>
        ))}
      </ul>
    </>
  );
}
