import type { MixState } from "../services/api";

/**
 * User-facing name for each mix state. Shared, because it was duplicated
 * byte-for-byte between the club page and the mix page — and a state that reads
 * one way in a list and another on its own page is precisely the drift this map
 * exists to prevent.
 *
 * `closed` reads as **"completed"** (Dawn, 2026-08-11). The API value stays
 * `closed`; only the word shown to people changed, and only *here* — the admin
 * metrics breakdown and the help page's lifecycle line deliberately still say
 * "closed", because this rename is about the state badge people see on a card,
 * not a rewrite of the app's vocabulary. The *action* is still "close mix" too:
 * closing is the verb, completed is the resulting state.
 */
export const MIX_STATE_LABEL: Record<MixState, string> = {
  pending: "upcoming",
  open_submission: "submissions open",
  open_voting: "voting open",
  closed: "completed",
};

/** A mix is "active" when members can act on it right now. */
export function isActiveMix(state: MixState): boolean {
  return state === "open_submission" || state === "open_voting";
}

/**
 * The three buckets a mix is grouped, ordered and styled by. Narrower than
 * `MixState`, which splits "active" into submissions vs voting — a distinction
 * the order and the badge weight do not care about, though the badge's own
 * label still spells it out.
 *
 * Shared rather than duplicated: the club page lists mixes and the mix page
 * shows one, and a mix that reads "live" on one screen must read "live" on the
 * other. Two copies of this would drift.
 */
export type MixGroup = "active" | "upcoming" | "done";

export function mixGroup(state: MixState): MixGroup {
  if (isActiveMix(state)) return "active";
  return state === "closed" ? "done" : "upcoming";
}

/** Sort weight per group: act on it, then what is coming, then what is done. */
export const MIX_ORDER: Record<MixGroup, number> = { active: 0, upcoming: 1, done: 2 };

/**
 * Badge weight per group — the ladder that makes state legible at a glance.
 * `positive` is a solid green fill and is reachable by at most one mix in a
 * club, since the API allows only one active mix at a time.
 */
export const MIX_BADGE: Record<MixGroup, "positive" | "strong" | "default"> = {
  active: "positive",
  upcoming: "strong",
  done: "default",
};
