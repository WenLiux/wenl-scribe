const BVID_PATTERN = /^BV[0-9A-Za-z]{10}$/;

export function isValidBvid(value: unknown): value is string {
  return typeof value === "string" && BVID_PATTERN.test(value.trim());
}

export function normalizePage(value: unknown) {
  const page = Number.parseInt(String(value ?? "1"), 10);
  return Number.isFinite(page) && page > 0 ? page : 1;
}

export function normalizeSeconds(value: unknown, duration?: number | null) {
  const seconds = Math.max(0, Math.floor(Number(value) || 0));
  if (typeof duration !== "number" || !Number.isFinite(duration) || duration <= 0) return seconds;
  return Math.min(seconds, Math.max(0, Math.floor(duration)));
}

export function buildBilibiliEmbedUrl({
  bvid,
  page,
  seconds,
  autoplay,
}: {
  bvid: string;
  page?: number;
  seconds?: number;
  autoplay?: boolean;
}) {
  if (!isValidBvid(bvid)) return null;
  const params = new URLSearchParams({
    bvid: bvid.trim(),
    p: String(normalizePage(page)),
    t: String(normalizeSeconds(seconds)),
    poster: "1",
    autoplay: autoplay ? "1" : "0",
    danmaku: "0",
  });
  return `https://player.bilibili.com/player.html?${params.toString()}`;
}

export function buildBilibiliWatchUrl({
  bvid,
  page,
  seconds,
}: {
  bvid: string;
  page?: number;
  seconds?: number;
}) {
  if (!isValidBvid(bvid)) return null;
  const params = new URLSearchParams({
    p: String(normalizePage(page)),
    t: String(normalizeSeconds(seconds)),
  });
  return `https://www.bilibili.com/video/${bvid.trim()}?${params.toString()}`;
}

export function formatPlayerTimestamp(value: number) {
  const seconds = normalizeSeconds(value);
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  return h
    ? `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
    : `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}
