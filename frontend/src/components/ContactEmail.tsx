import { useState } from "react";

type ContactEmailProps = {
  user: string;
  domain: string;
  /** Label shown before the address is revealed. */
  label?: string;
  className?: string;
};

/**
 * A contact email address kept out of the page until a click reveals it —
 * the address is never present as static text or a mailto: href at rest, so
 * it isn't picked up by scrapers that harvest rendered text or markup without
 * simulating interaction. Not a guarantee against a scraper that runs a full
 * browser and clicks through, but stops the vast majority of harvesting bots
 * for one extra click.
 */
export function ContactEmail({ user, domain, label = "email us", className }: ContactEmailProps) {
  const [revealed, setRevealed] = useState(false);

  if (revealed) {
    const address = `${user}@${domain}`;
    return (
      <a href={`mailto:${address}`} className={className}>
        {address}
      </a>
    );
  }

  return (
    <button type="button" onClick={() => setRevealed(true)} className={className}>
      {label}
    </button>
  );
}
