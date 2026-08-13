import { useEffect, useState } from "react";

/** Particle colors, tuned to read on a near-black page. Confetti fires only on
 *  club completion (`ClubHomeScreen`, `isComplete`), which is an achievement
 *  moment, so the burst is amber-led — the amber marks the achievement.
 *
 *  These are inline `backgroundColor` values — a particle cannot read a
 *  Tailwind class — so each literal names the token it comes from, for the R18
 *  sweep. The retired palette this replaces had already drifted: its `#7A9E82`
 *  was the *pre*-MYS-186 sage, stale before the redesign began. */
const COLORS = [
  "#F3821D", // accent
  "#F7F5F1", // foreground
  "#D2B27C", // chart-5
  "#00A692", // chart-2
  "#8E8F93", // muted-foreground
];

const COUNT = 55;

type Particle = {
  id: number;
  x: number;
  delay: number;
  duration: number;
  size: number;
  color: string;
  startRotation: number;
  isCircle: boolean;
};

function makeParticles(): Particle[] {
  return Array.from({ length: COUNT }, (_, i) => ({
    id: i,
    x: Math.random() * 100,
    delay: Math.random() * 900,
    duration: 1700 + Math.random() * 1100,
    size: 4 + Math.random() * 7,
    color: COLORS[Math.floor(Math.random() * COLORS.length)],
    startRotation: Math.random() * 360,
    isCircle: Math.random() > 0.45,
  }));
}

/** One-shot CSS confetti burst. Fires on mount, unmounts itself after ~3.5s.
 *  Skips entirely for prefers-reduced-motion (MYS-121) — a full-viewport
 *  particle burst is exactly the kind of motion that setting opts out of. */
export function Confetti() {
  const [particles] = useState(makeParticles);
  const [visible, setVisible] = useState(true);
  const [reducedMotion] = useState(
    () =>
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  );

  useEffect(() => {
    const t = setTimeout(() => setVisible(false), 3500);
    return () => clearTimeout(t);
  }, []);

  if (!visible || reducedMotion) return null;

  return (
    <div aria-hidden="true" className="pointer-events-none fixed inset-0 z-50 overflow-hidden">
      <style>{`
        @keyframes confetti-fall {
          0%   { transform: translateY(-16px) rotate(0deg); opacity: 1; }
          80%  { opacity: 1; }
          100% { transform: translateY(110vh) rotate(580deg); opacity: 0; }
        }
      `}</style>
      {particles.map((p) => (
        <div
          key={p.id}
          style={{
            position: "absolute",
            top: 0,
            left: `${p.x}%`,
            width: p.size,
            height: p.isCircle ? p.size : p.size * 0.45,
            backgroundColor: p.color,
            borderRadius: p.isCircle ? "50%" : "1px",
            transform: `rotate(${p.startRotation}deg)`,
            animationName: "confetti-fall",
            animationDuration: `${p.duration}ms`,
            animationDelay: `${p.delay}ms`,
            animationTimingFunction: "ease-in",
            animationFillMode: "forwards",
          }}
        />
      ))}
    </div>
  );
}
