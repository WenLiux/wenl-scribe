"use client";

import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";
import { BilibiliPlayer } from "./BilibiliPlayer";
import { formatPlayerTimestamp } from "./bilibili";
import { useFloatingPlayer } from "./useFloatingPlayer";
import { useMediaQuery } from "./useMediaQuery";

export type FloatingBilibiliPlayerHandle = {
  showForTimestamp: () => void;
};

type FloatingBilibiliPlayerProps = {
  bvid: string;
  page?: number;
  duration?: number | null;
  startTime?: number;
  autoplay?: boolean;
  reloadKey?: number;
  enabled?: boolean;
  side?: "left" | "right";
};

export const FloatingBilibiliPlayer = forwardRef<
  FloatingBilibiliPlayerHandle,
  FloatingBilibiliPlayerProps
>(function FloatingBilibiliPlayer({
  bvid,
  page = 1,
  duration,
  startTime = 0,
  autoplay = false,
  reloadKey = 0,
  enabled = true,
  side = "left",
}, ref) {
  const originRef = useRef<HTMLDivElement>(null);
  const shellRef = useRef<HTMLDivElement>(null);
  const [originHeight, setOriginHeight] = useState(0);
  const isMobile = useMediaQuery("(max-width: 767px)");
  const floating = useFloatingPlayer({ originRef, enabled: enabled && Boolean(bvid) });

  useImperativeHandle(ref, () => ({
    showForTimestamp: floating.showForTimestamp,
  }), [floating.showForTimestamp]);

  const desktopPastOrigin = enabled && !isMobile && floating.isPastOrigin;
  const desktopFloating = desktopPastOrigin && !floating.dismissed;
  const desktopDismissed = desktopPastOrigin && floating.dismissed;
  const mobileVisible = enabled && isMobile && floating.isPastOrigin && !floating.dismissed;
  const mobileExpanded = mobileVisible && floating.mobileExpanded;
  const detached = desktopPastOrigin || mobileVisible;

  useEffect(() => {
    const shell = shellRef.current;
    if (!shell || detached || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      setOriginHeight(entry.borderBoxSize?.[0]?.blockSize ?? entry.contentRect.height);
    });
    observer.observe(shell);
    return () => observer.disconnect();
  }, [detached]);

  const shellClassName = useMemo(() => [
    "floatingVideoShell",
    desktopFloating && (side === "right" ? "isFloatingRight" : "isFloatingLeft"),
    desktopDismissed && "isFloatingDismissed",
    mobileVisible && !mobileExpanded && "isMobileCollapsed",
    mobileExpanded && "isMobileExpanded",
  ].filter(Boolean).join(" "), [desktopDismissed, desktopFloating, mobileExpanded, mobileVisible, side]);

  return <>
    <div
      ref={originRef}
      className={`videoPlayerOrigin${detached ? " hasDetachedPlayer" : ""}`}
      style={detached && originHeight > 0 ? { minHeight: originHeight } : undefined}
    >
      <div ref={shellRef} className={shellClassName}>
        <BilibiliPlayer
          bvid={bvid}
          page={page}
          duration={duration}
          startTime={startTime}
          autoplay={autoplay}
          reloadKey={reloadKey}
        />

        {(desktopFloating || mobileExpanded) && <div className="floatingVideoBar">
          <span>定位 {formatPlayerTimestamp(startTime)}</span>
          <div className="floatingVideoControls">
            <button type="button" onClick={floating.returnToOrigin} aria-label="返回视频原位">返回原位</button>
            {isMobile
              ? <button type="button" onClick={floating.collapseMobilePlayer} aria-label="收起迷你播放器">收起</button>
              : <button type="button" onClick={floating.closeFloatingPlayer} aria-label="将悬浮视频缩略成按钮">缩略</button>}
          </div>
        </div>}

        {mobileVisible && !mobileExpanded && <button
          type="button"
          className="mobileVideoLauncher"
          onClick={floating.expandMobilePlayer}
          aria-label={`展开视频，当前定位 ${formatPlayerTimestamp(startTime)}`}
        >
          <span>▶ 视频</span><strong>展开</strong>
        </button>}
      </div>
    </div>

    {enabled && floating.dismissed && floating.isPastOrigin && <button
      type="button"
      className="restoreFloatingVideo"
      onClick={floating.restoreFloatingPlayer}
      aria-label="展开悬浮视频"
    >
      ▶ 视频
    </button>}

    <span className="srOnly" aria-live="polite">
      {autoplay ? `已定位至 ${formatPlayerTimestamp(startTime)}` : ""}
    </span>
  </>;
});
