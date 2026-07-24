import assert from "node:assert/strict";
import test from "node:test";
import {
  buildBilibiliEmbedUrl,
  buildBilibiliWatchUrl,
  formatPlayerTimestamp,
  isValidBvid,
  normalizePage,
  normalizeSeconds,
} from "../app/components/video/bilibili.ts";

test("validates BV identifiers without accepting surrounding text", () => {
  assert.equal(isValidBvid("BV1xx411c7mD"), true);
  assert.equal(isValidBvid("BV1xx411c7m"), false);
  assert.equal(isValidBvid("【分享】BV1xx411c7mD"), false);
});

test("normalizes page and playback seconds", () => {
  assert.equal(normalizePage("2"), 2);
  assert.equal(normalizePage(0), 1);
  assert.equal(normalizePage("oops"), 1);
  assert.equal(normalizeSeconds(-9), 0);
  assert.equal(normalizeSeconds(81.9), 81);
  assert.equal(normalizeSeconds(500, 120.8), 120);
});

test("builds fixed-domain embed and fallback URLs", () => {
  const embed = buildBilibiliEmbedUrl({ bvid: "BV1xx411c7mD", page: 3, seconds: 75, autoplay: true });
  assert.equal(embed, "https://player.bilibili.com/player.html?bvid=BV1xx411c7mD&p=3&t=75&poster=1&autoplay=1&danmaku=0");
  assert.equal(buildBilibiliWatchUrl({ bvid: "BV1xx411c7mD", page: 3, seconds: 75 }), "https://www.bilibili.com/video/BV1xx411c7mD?p=3&t=75");
  assert.equal(buildBilibiliEmbedUrl({ bvid: "invalid" }), null);
});

test("formats edge timestamps", () => {
  assert.equal(formatPlayerTimestamp(0), "00:00");
  assert.equal(formatPlayerTimestamp(59), "00:59");
  assert.equal(formatPlayerTimestamp(60), "01:00");
  assert.equal(formatPlayerTimestamp(3600), "01:00:00");
});
