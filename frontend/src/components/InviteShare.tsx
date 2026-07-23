import { useEffect, useState } from "react";
import { Button } from "./Button";

/**
 * A shareable invite link: read-only field (select-on-focus), copy button
 * (clipboard, with a 2s "copied" confirmation), and a native share-sheet
 * button when the browser supports it. Shared by the per-club invite flow
 * and the admin screen's platform invite (MYS-182).
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
      <label htmlFor="invite-url" className="block">
        <span className="block font-mono uppercase tracking-label text-[9px] text-muted">
          share link
        </span>
        <input
          id="invite-url"
          readOnly
          value={inviteUrl}
          onFocus={(e) => e.currentTarget.select()}
          className="mt-2 w-full bg-transparent font-mono text-[13px] text-ink border-0 border-b border-ink rounded-none px-0 py-1 focus:outline-none focus:border-sage"
        />
      </label>
      <p className="mt-3 font-mono text-[13px] font-light text-muted">
        this link expires in 48 hours.
      </p>
      <div className="mt-4 flex items-center gap-4">
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
