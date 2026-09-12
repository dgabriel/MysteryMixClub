import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router";
import { ClubSongsScreen } from "./ClubSongsScreen";
import { ApiError, getClub, getClubSongs, type ClubSong } from "../services/api";

/** Protected route for MysteryMixClub-ps1w.2: every song ever submitted to
 *  this club, across its closed mixes only. Linked from ClubHomeScreen's
 *  "songs" section. */
export function ClubSongsRoute() {
  const { id } = useParams();
  const navigate = useNavigate();

  const [clubName, setClubName] = useState<string | null>(null);
  const [entries, setEntries] = useState<ClubSong[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    void (async () => {
      try {
        const [club, songs] = await Promise.all([getClub(id), getClubSongs(id)]);
        if (cancelled) return;
        setClubName(club.name);
        setEntries(songs);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : "couldn't load these songs. try again.");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id]);

  return (
    <ClubSongsScreen
      clubName={clubName}
      entries={entries}
      loading={loading}
      error={error}
      onOpenMix={(mixId) => navigate(`/mixes/${mixId}`)}
    />
  );
}
