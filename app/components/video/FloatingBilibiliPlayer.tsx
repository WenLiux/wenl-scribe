"use client";

import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { BilibiliPlayer } from "./BilibiliPlayer";
import { formatPlayerTimestamp } from "./bilibili";
import { useFloatingPlayer } from "./useFloatingPlayer";

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
  autoExpand?: boolean;
  side?: "left" | "right";
};

type AnchorPoint = { x: number; y: number };

const VIEWPORT_GAP = 12;

function clampAnchor(point: AnchorPoint, width: number, height: number) {
  return {
    x: Math.max(VIEWPORT_GAP, Math.min(window.innerWidth - width - VIEWPORT_GAP, point.x)),
    y: Math.max(VIEWPORT_GAP, Math.min(window.innerHeight - height - VIEWPORT_GAP, point.y)),
  };
}

function panelStyleFromAnchor(anchor: AnchorPoint, launcherWidth: number, launcherHeight: number): CSSProperties {
  const rootStyles = window.getComputedStyle(document.documentElement);
  const configuredWidth = Number.parseFloat(rootStyles.getPropertyValue("--floating-player-width")) || 360;
  const width = Math.min(configuredWidth, window.innerWidth - VIEWPORT_GAP * 2);
  const height = width * 9 / 16 + 43;
  const preferredLeft = anchor.x + launcherWidth - width;
  const preferredTop = anchor.y + launcherHeight - height;
  return {
    left: Math.max(VIEWPORT_GAP, Math.min(window.innerWidth - width - VIEWPORT_GAP, preferredLeft)),
    top: Math.max(VIEWPORT_GAP, Math.min(window.innerHeight - height - VIEWPORT_GAP, preferredTop)),
    width,
  };
}

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
  autoExpand = true,
  side = "left",
}, ref) {
  const originRef = useRef<HTMLDivElement>(null);
  const shellRef = useRef<HTMLDivElement>(null);
  const launcherRef = useRef<HTMLButtonElement>(null);
  const previousSideRef = useRef(side);
  const dragRef = useRef<{ pointerX: number; pointerY: number; anchorX: number; anchorY: number } | null>(null);
  const didDragRef = useRef(false);
  const userMovedRef = useRef(false);
  const [originHeight, setOriginHeight] = useState(0);
  const [anchor, setAnchor] = useState<AnchorPoint | null>(null);
  const [launcherSize, setLauncherSize] = useState({ width: 88, height: 40 });
  const floating = useFloatingPlayer({ originRef, enabled: enabled && Boolean(bvid), autoExpand });
  const detached = enabled && floating.isPastOrigin;
  const {
    collapseFloatingPlayer,
    expandFloatingPlayer,
    returnToOrigin,
    showDefaultFloatingPlayer,
  } = floating;

  const rememberLauncherAnchor = useCallback(() => {
    const launcher = launcherRef.current;
    if (!launcher) return anchor;
    const rect = launcher.getBoundingClientRect();
    const next = { x: rect.left, y: rect.top };
    setLauncherSize({ width: rect.width, height: rect.height });
    setAnchor(next);
    return next;
  }, [anchor]);

  const expandFromLauncher = useCallback(() => {
    rememberLauncherAnchor();
    expandFloatingPlayer();
  }, [expandFloatingPlayer, rememberLauncherAnchor]);

  useImperativeHandle(ref, () => ({
    showForTimestamp: expandFromLauncher,
  }), [expandFromLauncher]);

  useEffect(() => {
    if (previousSideRef.current === side) return;
    previousSideRef.current = side;
    userMovedRef.current = false;
    setAnchor(null);
    if (detached) showDefaultFloatingPlayer();
  }, [detached, showDefaultFloatingPlayer, side]);

  useEffect(() => {
    const shell = shellRef.current;
    if (!shell || detached || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      setOriginHeight(entry.borderBoxSize?.[0]?.blockSize ?? entry.contentRect.height);
    });
    observer.observe(shell);
    return () => observer.disconnect();
  }, [detached]);

  useEffect(() => {
    if (!anchor) return;
    const keepInViewport = () => setAnchor(current => current
      ? clampAnchor(current, launcherSize.width, launcherSize.height)
      : current);
    window.addEventListener("resize", keepInViewport);
    return () => window.removeEventListener("resize", keepInViewport);
  }, [anchor, launcherSize.height, launcherSize.width]);

  const shellClassName = [
    "floatingVideoShell",
    detached && floating.expanded && "isFloatingExpanded",
    detached && !floating.expanded && "isFloatingCollapsed",
    detached && floating.expanded && !anchor && `default-${side}`,
  ].filter(Boolean).join(" ");

  const panelStyle = useMemo(() => (
    detached && floating.expanded && anchor
      ? panelStyleFromAnchor(anchor, launcherSize.width, launcherSize.height)
      : undefined
  ), [anchor, detached, floating.expanded, launcherSize.height, launcherSize.width]);

  function handlePointerDown(event: ReactPointerEvent<HTMLButtonElement>) {
    const launcher = event.currentTarget;
    const rect = launcher.getBoundingClientRect();
    const current = anchor || { x: rect.left, y: rect.top };
    setAnchor(current);
    setLauncherSize({ width: rect.width, height: rect.height });
    dragRef.current = {
      pointerX: event.clientX,
      pointerY: event.clientY,
      anchorX: current.x,
      anchorY: current.y,
    };
    didDragRef.current = false;
    launcher.setPointerCapture(event.pointerId);
  }

  function handlePointerMove(event: ReactPointerEvent<HTMLButtonElement>) {
    if (!dragRef.current) return;
    const dx = event.clientX - dragRef.current.pointerX;
    const dy = event.clientY - dragRef.current.pointerY;
    if (Math.hypot(dx, dy) < 4 && !didDragRef.current) return;
    didDragRef.current = true;
    userMovedRef.current = true;
    setAnchor(clampAnchor({
      x: dragRef.current.anchorX + dx,
      y: dragRef.current.anchorY + dy,
    }, launcherSize.width, launcherSize.height));
  }

  function handlePointerUp(event: ReactPointerEvent<HTMLButtonElement>) {
    dragRef.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }

  function handleLauncherClick() {
    if (didDragRef.current) {
      didDragRef.current = false;
      return;
    }
    expandFromLauncher();
  }

  return <>
    <div
      ref={originRef}
      className={`videoPlayerOrigin${detached ? " hasDetachedPlayer" : ""}`}
      style={detached && originHeight > 0 ? { minHeight: originHeight } : undefined}
    >
      <div ref={shellRef} className={shellClassName} style={panelStyle}>
        <BilibiliPlayer
          bvid={bvid}
          page={page}
          duration={duration}
          startTime={startTime}
          autoplay={autoplay}
          reloadKey={reloadKey}
        />

        {detached && floating.expanded && <div className="floatingVideoBar">
          <span>定位 {formatPlayerTimestamp(startTime)}</span>
          <div className="floatingVideoControls">
            <button type="button" onClick={returnToOrigin} aria-label="返回视频原位">返回原位</button>
            <button type="button" onClick={collapseFloatingPlayer} aria-label="将悬浮视频缩略成按钮">缩略</button>
          </div>
        </div>}
      </div>
    </div>

    {detached && !floating.expanded && <button
      ref={launcherRef}
      type="button"
      className={`floatingVideoLauncher default-${side}${userMovedRef.current ? " wasMoved" : ""}`}
      style={anchor ? {
        left: anchor.x,
        top: anchor.y,
        right: "auto",
        bottom: "auto",
        width: launcherSize.width,
        height: launcherSize.height,
      } : undefined}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onPointerCancel={handlePointerUp}
      onClick={handleLauncherClick}
      aria-label={`展开悬浮视频，当前定位 ${formatPlayerTimestamp(startTime)}；可拖动`}
      title="拖动调整位置，点击展开视频"
    >
      <span aria-hidden="true">▶</span><strong>视频</strong>
    </button>}

    <span className="srOnly" aria-live="polite">
      {autoplay ? `已定位至 ${formatPlayerTimestamp(startTime)}` : ""}
    </span>
  </>;
});
