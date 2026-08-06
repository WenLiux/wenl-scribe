import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);
  return worker.fetch(
    new Request("http://localhost/", { headers: { accept: "text/html" } }),
    { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

test("renders the WENL application shell", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);
  const html = await response.text();
  assert.match(html, /WENL SCRIBE/);
  assert.match(html, /wenl_logo2\.svg/);
  assert.doesNotMatch(html, /Your site is taking shape|Codex is working/);
});

test("keeps v0.4 evidence, recovery, and export controls in the UI", async () => {
  const [page, css] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
  ]);
  assert.match(page, /type TranscriptSegment/);
  assert.match(page, /type Claim/);
  assert.match(page, /\/cancel/);
  assert.match(page, /\/retry/);
  assert.match(page, /\/resummarize/);
  assert.match(page, /\/api\/download\/diagnostics/);
  assert.match(page, /result\.segments\.map/);
  assert.match(page, /item\.evidence/);
  assert.match(page, /<FloatingBilibiliPlayer/);
  assert.match(page, /handleTimestampClick\(claimTimestamp\(item\)\)/);
  assert.match(page, /handleTimestampClick\(segment\.start\)/);
  assert.match(page, /API_PROVIDER_OPTIONS/);
  assert.match(page, /服务商/);
  assert.match(page, /sensenova_compatible/);
  assert.match(page, /连接并自动选择模型/);
  assert.match(page, /连接并验证当前模型/);
  assert.match(page, /自动选择可用模型/);
  assert.match(page, /selection_mode/);
  assert.match(page, /discoverApiModels/);
  assert.match(page, /Gemini OpenAI 兼容文档/);
  assert.match(page, /SenseChat-5/);
  assert.match(page, /compatible-mode\/v2/);
  assert.match(page, /高级设置/);
  assert.match(css, /\.claimList/);
  assert.match(css, /\.segmentRow/);
  assert.match(css, /\.partialNotice/);
  assert.match(css, /\.bilibiliPlayer/);
  assert.match(css, /\.floatingVideoShell\.isFloatingExpanded/);
  assert.match(css, /\.floatingVideoBar/);
  assert.match(css, /\.floatingVideoLauncher/);
});

test("backend persists staged artifacts and exposes recovery endpoints", async () => {
  const [backend, adapters] = await Promise.all([
    readFile(new URL("../backend/server.py", import.meta.url), "utf8"),
    readFile(new URL("../backend/llm/adapters.py", import.meta.url), "utf8"),
  ]);
  for (const artifact of ["metadata.json", "status.json", "transcript.json", "summary.json", "transcript.md", "summary.md", "task.log"]) {
    assert.match(backend, new RegExp(artifact.replace(".", "\\.")));
  }
  assert.match(backend, /def atomic_write_json/);
  assert.match(backend, /def locate_evidence/);
  assert.match(backend, /def cancel_job/);
  assert.match(backend, /def retry_job/);
  assert.match(backend, /\/api\/download\/diagnostics/);
  assert.match(backend, /provider.*sensenova/);
  assert.match(backend, /API_PERMISSION_DENIED/);
  assert.match(backend, /商汤错误码 7/);
  assert.match(backend, /MODEL_PROBE_MAX_OUTPUT_TOKENS/);
  assert.match(backend, /selection_mode/);
  assert.match(backend, /probe_failure_message/);
  assert.match(adapters, /"response_format"/);
  assert.match(adapters, /chat-completions/);
  assert.match(adapters, /max_new_tokens/);
  assert.match(adapters, /choices/);
  assert.match(adapters, /message/);
  assert.match(adapters, /delta/);
  assert.match(adapters, /output_text/);
  assert.match(adapters, /sensenova_native/);
  assert.match(adapters, /"gemini_openai": \{"structured_output": "json_schema", "models": True/);
  assert.match(adapters, /normalize_models/);
  assert.match(adapters, /api\/tags/);
  assert.match(backend, /\/api\/config\/models/);
  assert.match(backend, /"platform": "bilibili"/);
  assert.match(backend, /def resolve_page/);
});

test("v0.5 player keeps fixed Bilibili origins and CSP", async () => {
  const [player, helper, config, proxy] = await Promise.all([
    readFile(new URL("../app/components/video/BilibiliPlayer.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/components/video/bilibili.ts", import.meta.url), "utf8"),
    readFile(new URL("../next.config.ts", import.meta.url), "utf8"),
    readFile(new URL("../proxy.ts", import.meta.url), "utf8"),
  ]);
  assert.match(player, /data-reload-key/);
  assert.match(player, /allowFullScreen/);
  assert.match(helper, /https:\/\/player\.bilibili\.com\/player\.html/);
  assert.match(helper, /https:\/\/www\.bilibili\.com\/video/);
  assert.match(config, /frame-src 'self' https:\/\/player\.bilibili\.com/);
  assert.match(proxy, /frame-src 'self' https:\/\/player\.bilibili\.com/);
});

test("floating player keeps one iframe while its draggable shell changes position", async () => {
  const [floatingPlayer, floatingHook, page, brand] = await Promise.all([
    readFile(new URL("../app/components/video/FloatingBilibiliPlayer.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/components/video/useFloatingPlayer.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/brand.ts", import.meta.url), "utf8"),
  ]);
  assert.match(floatingPlayer, /<BilibiliPlayer/);
  assert.equal((floatingPlayer.match(/<BilibiliPlayer/g) || []).length, 1);
  assert.match(floatingPlayer, /ResizeObserver/);
  assert.match(floatingPlayer, /isFloatingCollapsed/);
  assert.match(floatingPlayer, /onPointerMove/);
  assert.match(floatingPlayer, /panelStyleFromAnchor/);
  assert.match(floatingPlayer, /width: launcherSize\.width/);
  assert.match(floatingPlayer, /showForTimestamp/);
  assert.match(floatingPlayer, /<Icon name="play"/);
  assert.match(floatingPlayer, /className="floatingVideoBar"/);
  assert.match(floatingHook, /IntersectionObserver/);
  assert.match(floatingHook, /bounds\.bottom/);
  assert.match(floatingHook, /shortPageFallback/);
  assert.match(floatingHook, /atPageBottom/);
  assert.match(floatingHook, /preferredExpandedRef/);
  assert.match(floatingHook, /hasFloatingStateRef/);
  assert.match(floatingHook, /setExpanded\(preferredExpandedRef\.current\)/);
  assert.match(floatingHook, /requestAnimationFrame\(\(\) => \{\s+setExpanded\(autoExpand\)/);
  assert.match(floatingHook, /cancelAnimationFrame\(animationFrame\)/);
  assert.match(floatingHook, /passedAbove && !wasPastOrigin/);
  assert.match(page, /floatingPlayerRef\.current\?\.showForTimestamp/);
  assert.match(page, /locateVideo\(seconds\)/);
  assert.match(page, /side=\{active === "transcript" \? "right" : "left"\}/);
  assert.match(page, /<Icon name="arrow-left"/);
  assert.match(page, /<Icon name="arrow-right"/);
  assert.match(floatingPlayer, /将悬浮视频缩略成按钮/);
  assert.match(floatingPlayer, /<strong>视频<\/strong>/);
  assert.match(floatingPlayer, /default-\$\{side\}/);
  assert.match(brand, /所见所听，皆可留文/);
});

test("new transcription asks for a model and first-use limits", async () => {
  const page = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  assert.match(page, /DEFAULT_SETTINGS: Settings = \{ model: "small"/);
  assert.match(page, /关键使用限制/);
  assert.match(page, /以后再说/);
  assert.match(page, /confirmTranscription/);
  assert.match(page, /FIRST_USE_KEY/);
  assert.match(page, /autoExpandPlayer: true/);
  assert.match(page, /默认弹出悬浮窗/);
  assert.match(page, /autoExpand=\{settings\.autoExpandPlayer\}/);
});
