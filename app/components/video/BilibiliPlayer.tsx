"use client";

import { useMemo, useState } from "react";
import {
  buildBilibiliEmbedUrl,
  buildBilibiliWatchUrl,
  formatPlayerTimestamp,
  normalizePage,
  normalizeSeconds,
} from "./bilibili";

type BilibiliPlayerProps = {
  bvid: string;
  page?: number;
  duration?: number | null;
  startTime?: number;
  autoplay?: boolean;
  reloadKey?: number;
};

function PlayerFrame({ src, reloadKey }: { src: string; reloadKey: number }) {
  const [loading, setLoading] = useState(true);
  return <div className="playerFrame">
    {loading && <div className="playerLoading" aria-live="polite"><i /><span>正在加载 B 站播放器…</span></div>}
    <iframe
      src={src}
      title="哔哩哔哩视频播放器"
      allow="autoplay; fullscreen; picture-in-picture"
      allowFullScreen
      loading="lazy"
      referrerPolicy="strict-origin-when-cross-origin"
      data-reload-key={reloadKey}
      onLoad={() => setLoading(false)}
    />
  </div>;
}

export function BilibiliPlayer({
  bvid,
  page = 1,
  duration,
  startTime = 0,
  autoplay = false,
  reloadKey = 0,
}: BilibiliPlayerProps) {
  const normalizedPage = normalizePage(page);
  const seconds = normalizeSeconds(startTime, duration);
  const embedUrl = useMemo(
    () => buildBilibiliEmbedUrl({ bvid, page: normalizedPage, seconds, autoplay }),
    [autoplay, bvid, normalizedPage, seconds],
  );
  const watchUrl = useMemo(
    () => buildBilibiliWatchUrl({ bvid, page: normalizedPage, seconds }),
    [bvid, normalizedPage, seconds],
  );

  if (!embedUrl || !watchUrl) {
    return <div className="playerUnavailable" role="status">
      <strong>当前任务无法加载播放器</strong>
      <span>视频 BV 号缺失或格式无效，逐字稿和总结仍可正常使用。</span>
    </div>;
  }

  return <section className="bilibiliPlayer" id="video-player" aria-label="哔哩哔哩视频播放器">
    <PlayerFrame
      key={`${bvid}-${normalizedPage}-${seconds}-${autoplay ? 1 : 0}-${reloadKey}`}
      src={embedUrl}
      reloadKey={reloadKey}
    />
    <div className="playerFoot">
      <span>{normalizedPage > 1 ? `第 ${normalizedPage} P · ` : ""}定位 {formatPlayerTimestamp(seconds)}</span>
      <a href={watchUrl} target="_blank" rel="noreferrer">在哔哩哔哩打开当前时间 ↗</a>
    </div>
  </section>;
}
