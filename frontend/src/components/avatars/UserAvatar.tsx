import { CassetteAvatar } from "./CassetteAvatar";

type UserAvatarProps = {
  userId: string;
  size?: number;
  /** Draw the cassette in `accent` rather than `muted-foreground`.
   *
   *  Set this for the viewer's **own** avatar and nowhere else. `ProfileScreen`
   *  passes it; `ClubHomeScreen`'s member roster does not, so a club of twenty
   *  is twenty neutral cassettes rather than twenty amber ones. Same line the
   *  `/home` display-name eyebrow draws — amber on a person means "you". */
  accent?: boolean;
};

/** Circular avatar showing a cassette tape illustration. Placeholder until real
 *  profile photos are supported.
 *
 *  Surface is `tile` — an inset chip inside a card — with a `hairline` edge. The
 *  illustration strokes `muted-foreground` (5.37:1 on `tile`) or, for the
 *  viewer's own avatar, `accent` (6.59:1). Both clear the 3:1 floor for
 *  non-text graphics with room to spare. The legacy `vinyl` mid-blue they
 *  replace was never contrast-checked against a dark surface. */
export function UserAvatar({ size = 48, accent = false }: UserAvatarProps) {
  return (
    <div
      className={`flex shrink-0 items-center justify-center rounded-full border border-hairline bg-tile ${
        accent ? "text-accent" : "text-muted-foreground"
      }`}
      style={{ width: size, height: size }}
    >
      <CassetteAvatar size={Math.round(size * 0.72)} />
    </div>
  );
}
