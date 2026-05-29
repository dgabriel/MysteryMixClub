import { useState } from "react";
import { EmailEntryScreen } from "./EmailEntryScreen";
import { CheckEmailScreen } from "./CheckEmailScreen";
import { requestMagicLink } from "../services/api";

/**
 * Login flow container. Drives EmailEntryScreen → CheckEmailScreen.
 * Wires the presentational screens via their documented props only.
 */
export function LoginRoute() {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sentTo, setSentTo] = useState<string | null>(null);

  async function handleSubmit(email: string) {
    setSubmitting(true);
    setError(null);
    try {
      await requestMagicLink(email);
      setSentTo(email);
    } catch {
      setError("that didn't work. check the address and try again.");
    } finally {
      setSubmitting(false);
    }
  }

  if (sentTo) {
    return <CheckEmailScreen email={sentTo} onBack={() => setSentTo(null)} />;
  }

  return (
    <EmailEntryScreen onSubmit={handleSubmit} submitting={submitting} error={error} />
  );
}
