import { useEffect, useRef } from "react";

const DEFAULT_INTERVAL_MS = 60_000;

/**
 * Calls `callback` on a fixed interval. Pauses when the tab is hidden and
 * fires an immediate tick when the tab becomes visible again. Cleans up on
 * unmount. Callback identity changes are tracked via a ref — no need to wrap
 * the callback in useCallback at the call site.
 */
export function usePolling(callback: () => void, intervalMs = DEFAULT_INTERVAL_MS) {
  const savedCallback = useRef(callback);

  useEffect(() => {
    savedCallback.current = callback;
  });

  useEffect(() => {
    let timer: ReturnType<typeof setInterval> | null = null;

    const tick = () => savedCallback.current();

    const start = () => {
      if (timer === null) timer = setInterval(tick, intervalMs);
    };

    const stop = () => {
      if (timer !== null) {
        clearInterval(timer);
        timer = null;
      }
    };

    const onVisibilityChange = () => {
      if (document.hidden) {
        stop();
      } else {
        tick();
        start();
      }
    };

    if (!document.hidden) start();
    document.addEventListener("visibilitychange", onVisibilityChange);

    return () => {
      stop();
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [intervalMs]);
}
