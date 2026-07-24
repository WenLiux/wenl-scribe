"use client";

import type { RefObject } from "react";
import { useCallback, useEffect, useState } from "react";

type UseFloatingPlayerOptions = {
  originRef: RefObject<HTMLDivElement | null>;
  enabled?: boolean;
  topOffset?: number;
};

export function useFloatingPlayer({
  originRef,
  enabled = true,
  topOffset = 12,
}: UseFloatingPlayerOptions) {
  const [isPastOrigin, setIsPastOrigin] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const [mobileExpanded, setMobileExpanded] = useState(false);

  useEffect(() => {
    if (!enabled) return;
    const origin = originRef.current;
    if (!origin || typeof IntersectionObserver === "undefined") return;

    const observer = new IntersectionObserver(([entry]) => {
      const rootTop = entry.rootBounds?.top ?? 0;
      const passedAbove = !entry.isIntersecting && entry.boundingClientRect.bottom <= rootTop + topOffset;
      setIsPastOrigin(passedAbove);
    }, { root: null, threshold: [0, 0.01] });

    observer.observe(origin);
    return () => observer.disconnect();
  }, [enabled, originRef, topOffset]);

  const closeFloatingPlayer = useCallback(() => {
    setDismissed(true);
    setMobileExpanded(false);
  }, []);
  const restoreFloatingPlayer = useCallback(() => setDismissed(false), []);
  const showForTimestamp = useCallback(() => {
    setDismissed(false);
    setMobileExpanded(true);
  }, []);
  const collapseMobilePlayer = useCallback(() => setMobileExpanded(false), []);
  const expandMobilePlayer = useCallback(() => setMobileExpanded(true), []);
  const returnToOrigin = useCallback(() => {
    originRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [originRef]);

  return {
    isPastOrigin,
    dismissed,
    mobileExpanded,
    closeFloatingPlayer,
    restoreFloatingPlayer,
    showForTimestamp,
    collapseMobilePlayer,
    expandMobilePlayer,
    returnToOrigin,
  };
}
