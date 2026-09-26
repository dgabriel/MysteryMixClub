import { useEffect, useId, useRef, useState } from "react";
import { Button } from "./Button";
import { MODAL_PANEL, MODAL_SCRIM } from "./modalSurface";
import { useFocusTrap } from "../hooks/useFocusTrap";
import {
  nativePushAvailable,
  onAppResume,
  pushPermissionStatus,
  requestPushPermissionAndRegister,
  syncPushRegistration,
} from "../ios/push";
import { openNotificationSettings } from "../ios/appSettings";
import { recordPushAsk, shouldAskForPush } from "../lib/pushAsk";

type AskMode = "prompt" | "denied";

/**
 * Offers to turn on push right after login (MysteryMixClub-gxh3), on native
 * iOS only, instead of leaving it buried in Profile. Dawn's calls: the white
 * modal, asked at most three times a week apart (lib/pushAsk.ts).
 *
 * - Never asked by iOS yet: an explainer first, so the one-shot system prompt
 *   isn't spent on someone who doesn't know why it's there.
 * - Denied: iOS won't show its prompt again, so "turn on" opens this app's
 *   notification settings, and coming back with permission granted registers
 *   the device.
 * - Granted: nothing to ask (a missing registration retries silently, and
 *   Profile shows its status).
 *
 * Declining never blocks anything in the app.
 */
export function PushActivationPrompt({ userId }: { userId: string }) {
  const [mode, setMode] = useState<AskMode | null>(null);

  useEffect(() => {
    if (!nativePushAvailable()) return;
    let cancelled = false;
    void pushPermissionStatus()
      .then((status) => {
        if (cancelled || status === "granted" || !shouldAskForPush(userId)) return;
        recordPushAsk(userId);
        setMode(status);
      })
      .catch(() => {
        // No permission answer: don't ask this time.
      });
    return () => {
      cancelled = true;
    };
  }, [userId]);

  if (mode === null) return null;
  return <PushActivationModal mode={mode} onClose={() => setMode(null)} />;
}

function PushActivationModal({ mode, onClose }: { mode: AskMode; onClose: () => void }) {
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  useFocusTrap(dialogRef, onClose);

  function turnOn() {
    void requestPushPermissionAndRegister();
    onClose();
  }

  function openSettings() {
    // Coming back from Settings with permission granted: register this device
    // now rather than waiting for a relaunch.
    const stop = onAppResume(() => {
      stop();
      void pushPermissionStatus().then((status) => {
        if (status === "granted") void syncPushRegistration();
      });
    });
    void openNotificationSettings();
    onClose();
  }

  return (
    <div className={MODAL_SCRIM}>
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className={`w-full max-w-sm px-6 py-5 ${MODAL_PANEL}`}
      >
        <span className="font-mono text-mini uppercase tracking-mono-caps text-ink-muted">
          notifications
        </span>
        <h2
          id={titleId}
          className="mt-3 font-display text-[1.375rem] font-extrabold uppercase leading-none tracking-display-snug text-ink"
        >
          never miss your turn
        </h2>
        <p className="mt-3 text-sm leading-[1.6] text-ink-muted">
          {mode === "denied"
            ? "notifications are off for mystery mix club in ios settings. turn them on there to get a nudge when it's your turn to submit or vote."
            : "get a nudge when it's your turn to submit or vote, and when the results are in."}
        </p>
        <p className="mt-2 text-meta leading-[1.6] text-ink-muted">
          you can change this any time in your profile.
        </p>
        <div className="mt-6 flex flex-wrap gap-4">
          {mode === "denied" ? (
            <Button onPaper type="button" onClick={openSettings}>
              open ios settings
            </Button>
          ) : (
            <Button onPaper type="button" onClick={turnOn}>
              turn on notifications
            </Button>
          )}
          <Button onPaper variant="ghost" type="button" onClick={onClose}>
            not now
          </Button>
        </div>
      </div>
    </div>
  );
}
