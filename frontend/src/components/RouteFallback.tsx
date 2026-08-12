import { ConcentricRings } from "./ConcentricRings";

/** Suspense fallback for lazy-loaded routes (MYS-240) — the same rotating-disc
 *  loading motif used elsewhere in the app, not a spinner. The page background
 *  is `floor` from `body`, so this needs no surface of its own. */
export function RouteFallback() {
  return (
    <main className="min-h-screen flex items-center justify-center px-4 sm:px-8">
      <ConcentricRings size={72} spinning />
    </main>
  );
}
