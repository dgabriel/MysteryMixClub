import { CassetteAvatar } from "./CassetteAvatar";

type UserAvatarProps = {
  userId: string;
  size?: number;
  /** Draw the cassette in the accent rather than the muted grey.
   *
   *  Set this for the viewer's **own** avatar and nowhere else. `ProfileScreen`
   *  passes it; `ClubHomeScreen`'s member roster does not, so a club of twenty
   *  is twenty neutral cassettes rather than twenty amber ones. Same line the
   *  `/home` display-name eyebrow draws — amber on a person means "you". */
  accent?: boolean;
  /** The avatar sits directly on the light `paper` page (ADR 0013) rather than
   *  on a dark surface.
   *
   *  This has to be a prop rather than a global switch: the roster on
   *  `ClubHomeScreen` renders inside hand-rolled dark islands on what is
   *  otherwise a paper route, so "the page is light" says nothing about which
   *  ramp a given avatar owes. */
  onPaper?: boolean;
};

/** Circular avatar showing a cassette tape illustration. Placeholder until real
 *  profile photos are supported.
 *
 *  **On a dark surface** the chip is `tile` with a `hairline` edge, and the
 *  illustration strokes `muted-foreground` (5.37:1 on `tile`) or, for the
 *  viewer's own avatar, `accent` (6.59:1).
 *
 *  **On paper** it inverts: a white chip with a near-black `ink` ring, and the
 *  cassette in `ink-accent` rather than `accent`. That swap is not cosmetic —
 *  `accent` on white is 2.62:1, where `ink-accent` is 4.61:1. The old
 *  `hairline` edge (white at 9%) was invisible on paper, which is why the ring
 *  becomes a real stroke here rather than staying a hairline.
 *
 *  Every combination clears the 3:1 floor for non-text graphics with room to
 *  spare, which is more than the illustration strictly owes — it is
 *  `aria-hidden` and decorative — but a 1.2–1.4px stroke needs the contrast to
 *  read at all. */
export function UserAvatar({ size = 48, accent = false, onPaper = false }: UserAvatarProps) {
  const chip = onPaper ? "border-ink bg-paper" : "border-hairline bg-tile";
  const ink = onPaper
    ? accent
      ? "text-ink-accent"
      : "text-ink-muted"
    : accent
      ? "text-accent"
      : "text-muted-foreground";
  return (
    <div
      className={`flex shrink-0 items-center justify-center rounded-full border ${chip} ${ink}`}
      style={{ width: size, height: size }}
    >
      <CassetteAvatar size={Math.round(size * 0.72)} />
    </div>
  );
}
