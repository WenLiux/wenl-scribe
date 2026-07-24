"use client";

import { useCallback, useState } from "react";
import { normalizeSeconds } from "./bilibili";
import type { VideoSeekRequest } from "./types";

const INITIAL_REQUEST: VideoSeekRequest = { seconds: 0, autoplay: false, version: 0 };

export function useVideoSeek(duration?: number | null) {
  const [request, setRequest] = useState<VideoSeekRequest>(INITIAL_REQUEST);

  const locate = useCallback((seconds: number | null | undefined) => {
    if (seconds == null) return;
    setRequest(previous => ({
      seconds: normalizeSeconds(seconds, duration),
      autoplay: true,
      version: previous.version + 1,
    }));
  }, [duration]);

  const reset = useCallback(() => setRequest(INITIAL_REQUEST), []);

  return { request, locate, reset };
}
