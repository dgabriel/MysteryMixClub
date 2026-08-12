type ClubNameProps = {
  name: string;
  /** The name is on the light page surface (`paper`, ADR 0013) rather than
   *  inside a dark card.
   *
   *  `accent` is 7.42:1 on `card` but **2.62:1 on `paper`** — an AA failure. The
   *  accented word is ordinary title text, not large-display type, so it owes
   *  the full 4.5:1 and takes `ink-accent`. */
  onPaper?: boolean;
};

/**
 * A club name with its **second word in the accent**, echoing the brand
 * lockup's own `MYSTERY MIX`+`CLUB` two-tone treatment. Single-word names render
 * plain — there is no second word to colour.
 *
 * This is a typographic treatment, not a signal: it says nothing about the club
 * and is safe to ignore. It is therefore purely decorative, and everything that
 * matters about a club — state, your role in it — is carried elsewhere in text.
 *
 * **Surface constraint.** `accent` is 7.42:1 on `card` but 2.62:1 on `paper`, so
 * a club title on the light surface must pass `onPaper` to take `ink-accent`
 * instead (ADR 0013). The club detail page's `h1` is exactly that case.
 *
 * Deliberately not applied to the mix screen's back button: that is navigation
 * chrome, which the style guide excludes from the accent by name.
 *
 * Whitespace is preserved rather than normalised — the split keeps its
 * separators — so an odd double space in a user-entered name survives a round
 * trip through this component instead of being silently rewritten.
 */
export function ClubName({ name, onPaper = false }: ClubNameProps) {
  // Capturing split: words land on even indices, the whitespace that separated
  // them on odd ones, so re-joining any slice reproduces the original exactly.
  const parts = name.split(/(\s+)/);
  const wordPositions = parts.reduce<number[]>((acc, part, i) => {
    if (i % 2 === 0 && part !== "") acc.push(i);
    return acc;
  }, []);

  if (wordPositions.length < 2) return <>{name}</>;

  const second = wordPositions[1];
  return (
    <>
      {parts.slice(0, second).join("")}
      <span className={onPaper ? "text-ink-accent" : "text-accent"}>{parts[second]}</span>
      {parts.slice(second + 1).join("")}
    </>
  );
}
