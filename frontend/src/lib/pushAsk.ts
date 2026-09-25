/**
 * How often the app offers to turn on push after login (MysteryMixClub-gxh3,
 * Dawn's call): at most three times per account on this device, at least a
 * week apart. After that, Profile is the only place that offers it.
 *
 * Per-viewer convenience state, so localStorage is right; every access is
 * best-effort (storage can throw or be empty) and a failure means "don't ask",
 * never an error.
 */
export const MAX_PUSH_ASKS = 3;
export const PUSH_ASK_INTERVAL_MS = 7 * 24 * 60 * 60 * 1000;

type AskRecord = { count: number; last: number };

function key(userId: string): string {
  return `mmc:push-ask:${userId}`;
}

function read(userId: string): AskRecord | null {
  try {
    const raw = localStorage.getItem(key(userId));
    if (!raw) return { count: 0, last: 0 };
    const parsed = JSON.parse(raw) as Partial<AskRecord>;
    return { count: Number(parsed.count) || 0, last: Number(parsed.last) || 0 };
  } catch {
    return null;
  }
}

export function shouldAskForPush(userId: string, now = Date.now()): boolean {
  const record = read(userId);
  if (record === null) return false;
  if (record.count >= MAX_PUSH_ASKS) return false;
  return record.count === 0 || now - record.last >= PUSH_ASK_INTERVAL_MS;
}

export function recordPushAsk(userId: string, now = Date.now()): void {
  const record = read(userId);
  if (record === null) return;
  try {
    localStorage.setItem(key(userId), JSON.stringify({ count: record.count + 1, last: now }));
  } catch {
    // Storage unavailable: the ask simply may repeat; nothing else depends on it.
  }
}
