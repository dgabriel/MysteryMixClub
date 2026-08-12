import { useEffect, useState } from "react";
import { Button } from "./Button";
import { TextField } from "./TextField";

/**
 * A shareable invite link: read-only field (select-on-focus), copy button
 * (clipboard, with a 2s "copied" confirmation), and a native share-sheet
 * button when the browser supports it. Shared by the per-club invite flow
 * and the admin screen's platform invite (MYS-182).
 *
 * The link itself takes the shared `TextField` rather than a hand-rolled
 * underline input, so it picks up the system's resting `muted-foreground`
 * underline and `accent` focus border. It carries no `error`/`invalid` prop:
 * a read-only value cannot be invalid, and neither copy failure below is a
 * form error.
 *
 * **Both failure paths are deliberately silent, and stay that way.** A blocked
 * clipboard write and a dismissed or unsupported share sheet both leave the
 * url visible and selectable in the field, which is the fallback the user
 * needs. Rendering an error line for either would add a user-visible string
 * that has never existed here.
 */
export function InviteShare({ inviteUrl }: { inviteUrl: string }) {
  const [copied, setCopied] = useState(false);
  const canShare = typeof navigator !== "undefined" && typeof navigator.share === "function";

  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), 2000);
    return () => window.clearTimeout(timer);
  }, [copied]);

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(inviteUrl);
      setCopied(true);
    } catch {
      // clipboard unavailable — leave the field for manual copy.
    }
  }

  async function handleShare() {
    try {
      await navigator.share({ url: inviteUrl });
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      // any other share failure is non-fatal — the url remains visible.
    }
  }

  return (
    <div>
      <TextField
        id="invite-url"
        label="share link"
        readOnly
        value={inviteUrl}
        onFocus={(e) => e.currentTarget.select()}
      />
      <p className="mt-3 text-meta leading-[1.6] text-muted-foreground">
        this link expires in 48 hours.
      </p>
      <div className="mt-4 flex items-center gap-4">
        {/* Copy is the action, so it keeps the amber `primary` fill in both
            states. The confirmation is the label swapping to "copied" for 2s,
            not a color change: recoloring the button would move amber onto a
            result, and the label is what a screen reader picks up anyway. */}
        <Button type="button" onClick={handleCopy}>
          {copied ? "copied" : "copy"}
        </Button>
        {canShare ? (
          <Button variant="ghost" type="button" onClick={handleShare}>
            share
          </Button>
        ) : null}
      </div>
    </div>
  );
}
