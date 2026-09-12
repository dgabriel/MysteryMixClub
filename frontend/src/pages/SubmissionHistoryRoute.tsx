import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { SubmissionHistoryScreen } from "./SubmissionHistoryScreen";
import { ApiError, getMySubmissionHistory, type MySubmission } from "../services/api";

/** Protected route for MysteryMixClub-ps1w.1: the caller's full cross-club
 *  submission history, linked from /profile. TopNav's persistent "profile"
 *  link is how a viewer gets back -- this screen doesn't add its own back
 *  affordance (the mix screen's "← club" is a plain in-content link, not the
 *  shared nav's unused `useNavBack` context mechanism). */
export function SubmissionHistoryRoute() {
  const navigate = useNavigate();

  const [entries, setEntries] = useState<MySubmission[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const history = await getMySubmissionHistory();
        if (!cancelled) setEntries(history);
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof ApiError ? err.message : "couldn't load your submissions. try again.",
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <SubmissionHistoryScreen
      entries={entries}
      loading={loading}
      error={error}
      onOpenMix={(mixId) => navigate(`/mixes/${mixId}`)}
    />
  );
}
