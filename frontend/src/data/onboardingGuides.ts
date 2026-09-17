/**
 * Persistence for the two "how it works" onboarding guides
 * (MysteryMixClub-6eo8): the empty-clubs welcome (first landing with no
 * clubs) and the club-invite welcome (just joined a club via invite).
 *
 * Same best-effort `localStorage` convention as releaseNotes.ts: a thrown
 * read/write is swallowed, since losing the dismissal flag just means a guide
 * shows one extra time, never a broken screen.
 *
 * Dismissal is scoped **per account** (`userId`), not global -- a shared
 * device or browser profile shouldn't carry one person's "seen it" into
 * another's first session, which is also why this can't reuse a single
 * un-namespaced key the way `pendingInvitePath` does.
 */

export type OnboardingGuide = "emptyClubs" | "invite";

function dismissedKey(guide: OnboardingGuide, userId: string): string {
  return `onboardingGuide:${guide}:${userId}:dismissed`;
}

/** True once `dismissGuide` has been called for this guide + account. */
export function isGuideDismissed(guide: OnboardingGuide, userId: string): boolean {
  try {
    return localStorage.getItem(dismissedKey(guide, userId)) === "1";
  } catch {
    return false;
  }
}

/** Record a guide as dismissed for this account, so its auto-trigger doesn't
 *  fire again. Reopening it later (the "how it works" action) does not call
 *  this -- only an actual dismissal (close, Escape, or the primary CTA)
 *  should suppress the *next* auto-trigger. */
export function dismissGuide(guide: OnboardingGuide, userId: string): void {
  try {
    localStorage.setItem(dismissedKey(guide, userId), "1");
  } catch {
    // Best-effort -- worst case the guide shows again next visit.
  }
}

const JUST_JOINED_KEY = "onboardingGuide:justJoinedClubId";

/**
 * Set right before navigating into a club the caller just joined via invite
 * -- either the explicit accept-invite action (JoinClubRoute.handleJoin) or
 * the auto-join that runs server-side during magic-link verify (surfaced to
 * the frontend as `already_member: true` immediately after a stashed
 * pending-invite sign-in, see JoinClubRoute).
 *
 * A one-shot signal ClubHomeRoute consumes on its very next mount to decide
 * whether to auto-show the invite-welcome guide, mirroring the existing
 * `pendingInvitePath` convention (JoinClubRoute / HomeRoute) of a single
 * un-namespaced localStorage slot rather than a per-account key -- it only
 * ever needs to survive one redirect.
 */
export function markJustJoinedClub(clubId: string): void {
  try {
    localStorage.setItem(JUST_JOINED_KEY, clubId);
  } catch {
    // Best-effort -- worst case the invite guide just doesn't auto-show.
  }
}

/**
 * Read-and-clear: true only on the one mount right after `markJustJoinedClub`
 * was called for this exact club. Consuming it (removing the key) regardless
 * of the outcome keeps this single-shot even if it's ever read against the
 * "wrong" club, so a stale flag can't misfire on some later, unrelated club.
 */
export function consumeJustJoinedClub(clubId: string): boolean {
  try {
    const value = localStorage.getItem(JUST_JOINED_KEY);
    if (value === null) return false;
    localStorage.removeItem(JUST_JOINED_KEY);
    return value === clubId;
  } catch {
    return false;
  }
}
