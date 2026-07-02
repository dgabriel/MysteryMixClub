import { CassetteAvatar } from "./CassetteAvatar";

/** Circular avatar showing a cassette tape illustration in Vinyl color.
 *  Placeholder until real profile photos are supported (see Linear backlog). */
export function UserAvatar({ size = 48 }: { userId: string; size?: number }) {
  return (
    <div
      className="flex shrink-0 items-center justify-center rounded-full border border-border bg-cream text-vinyl"
      style={{ width: size, height: size }}
    >
      <CassetteAvatar size={Math.round(size * 0.72)} />
    </div>
  );
}
