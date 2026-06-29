import { CassetteAvatar } from "./CassetteAvatar";
import { RecordAvatar } from "./RecordAvatar";
import { BoomBoxAvatar } from "./BoomBoxAvatar";
import { WalkmanAvatar } from "./WalkmanAvatar";
import { FlyingVAvatar } from "./FlyingVAvatar";

const ILLUSTRATIONS = [
  CassetteAvatar,
  RecordAvatar,
  BoomBoxAvatar,
  WalkmanAvatar,
  FlyingVAvatar,
];

/** Deterministic pick: same userId always gets the same illustration. */
function illustrationIndex(userId: string): number {
  let hash = 0;
  for (let i = 0; i < userId.length; i++) {
    hash = (hash * 31 + userId.charCodeAt(i)) | 0;
  }
  return Math.abs(hash) % ILLUSTRATIONS.length;
}

/** Circular avatar showing a randomly-assigned music hardware illustration.
 *  Uses the Vinyl color token. Deterministic: the same userId always gets the
 *  same illustration. */
export function UserAvatar({ userId, size = 48 }: { userId: string; size?: number }) {
  const Illustration = ILLUSTRATIONS[illustrationIndex(userId)];
  return (
    <div
      className="flex shrink-0 items-center justify-center rounded-full border border-border bg-cream text-vinyl"
      style={{ width: size, height: size }}
    >
      <Illustration size={Math.round(size * 0.62)} />
    </div>
  );
}
