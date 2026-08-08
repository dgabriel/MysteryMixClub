import { CassetteAvatar } from "./CassetteAvatar";

/** Circular avatar showing a cassette tape illustration. Placeholder until real
 *  profile photos are supported.
 *
 *  Surface is `tile` — an inset chip inside a card — with a `hairline` edge.
 *  The illustration strokes `muted-foreground`, which measures 5.37:1 on `tile`
 *  and so clears the 3:1 floor for non-text graphics with room to spare. The
 *  legacy `vinyl` mid-blue it replaces was never contrast-checked against a
 *  dark surface. */
export function UserAvatar({ size = 48 }: { userId: string; size?: number }) {
  return (
    <div
      className="flex shrink-0 items-center justify-center rounded-full border border-hairline bg-tile text-muted-foreground"
      style={{ width: size, height: size }}
    >
      <CassetteAvatar size={Math.round(size * 0.72)} />
    </div>
  );
}
