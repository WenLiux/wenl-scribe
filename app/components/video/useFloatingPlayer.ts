"use client";

import type { RefObject } from "react";
import { useCallback, useEffect, useRef, useState } from "react";

type UseFloatingPlayerOptions = {
  originRef: RefObject<HTMLDivElement | null>;
  enabled?: boolean;
  autoExpand?: boolean;
  topOffset?: number;
};

export function useFloatingPlayer({
  originRef,
  enabled = true,
  autoExpand = true,
  topOffset = 12,
}: UseFloatingPlayerOptions) {
  const [isPastOrigin, setIsPastOrigin] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const wasPastOriginRef = useRef(false);
  const preferredExpandedRef = useRef(autoExpand);
  const previousAutoExpandRef = useRef(autoExpand);
  const hasFloatingStateRef = useRef(false);

  useEffect(() => {
    if (!enabled) return;
    const origin = originRef.current;
    if (!origin) return;

    const updateFloatingState = (passedAbove: boolean) => {
      const wasPastOrigin = wasPastOriginRef.current;
      if (passedAbove === wasPastOrigin) return;
      wasPastOriginRef.current = passedAbove;
      setIsPastOrigin(passedAbove);
      if (passedAbove && !wasPastOrigin) {
        if (!hasFloatingStateRef.current) {
          preferredExpandedRef.current = autoExpand;
          hasFloatingStateRef.current = true;
        }
        setExpanded(preferredExpandedRef.current);
      }
      if (!passedAbove) setExpanded(false);
    };

    const evaluatePosition = () => {
      const bounds = origin.getBoundingClientRect();
      const documentHeight = document.documentElement.scrollHeight;
      const atPageBottom = window.scrollY + window.innerHeight >= documentHeight - 2;
      const fullyPastOrigin = bounds.bottom <= topOffset;
      const shortPageFallback = atPageBottom && bounds.top <= topOffset;
      updateFloatingState(fullyPastOrigin || shortPageFallback);
    };

    let animationFrame = 0;
    const scheduleEvaluation = () => {
      if (animationFrame) return;
      animationFrame = window.requestAnimationFrame(() => {
        animationFrame = 0;
        evaluatePosition();
      });
    };

    const observer = typeof IntersectionObserver === "undefined"
      ? null
      : new IntersectionObserver(scheduleEvaluation, { root: null, threshold: [0, 0.01, 0.5, 1] });

    observer?.observe(origin);
    window.addEventListener("scroll", scheduleEvaluation, { passive: true });
    window.addEventListener("resize", scheduleEvaluation);
    evaluatePosition();
    return () => {
      observer?.disconnect();
      window.removeEventListener("scroll", scheduleEvaluation);
      window.removeEventListener("resize", scheduleEvaluation);
      if (animationFrame) window.cancelAnimationFrame(animationFrame);
    };
  }, [autoExpand, enabled, originRef, topOffset]);

  useEffect(() => {
    if (previousAutoExpandRef.current === autoExpand) return;
    previousAutoExpandRef.current = autoExpand;
    preferredExpandedRef.current = autoExpand;
    hasFloatingStateRef.current = true;
    if (isPastOrigin) setExpanded(autoExpand);
  }, [autoExpand, isPastOrigin]);

  const collapseFloatingPlayer = useCallback(() => {
    hasFloatingStateRef.current = true;
    preferredExpandedRef.current = false;
    setExpanded(false);
  }, []);
  const expandFloatingPlayer = useCallback(() => {
    hasFloatingStateRef.current = true;
    preferredExpandedRef.current = true;
    setExpanded(true);
  }, []);
  const showDefaultFloatingPlayer = useCallback(() => {
    setExpanded(preferredExpandedRef.current);
  }, []);
  const showForTimestamp = useCallback(() => {
    hasFloatingStateRef.current = true;
    preferredExpandedRef.current = true;
    setExpanded(true);
  }, []);
  const returnToOrigin = useCallback(() => {
    setExpanded(false);
    originRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [originRef]);

  return {
    isPastOrigin,
    expanded,
    collapseFloatingPlayer,
    expandFloatingPlayer,
    showDefaultFloatingPlayer,
    showForTimestamp,
    returnToOrigin,
  };
}
