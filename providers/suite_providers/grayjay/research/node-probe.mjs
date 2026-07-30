// Decisive probe: can Node's V8 run the unmodified YouTube plugin all
// the way to stream sources? HTTP is done natively (sync via curl) so
// there are no cross-language callbacks at all.
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const dir = process.argv[2];
const config = JSON.parse(readFileSync(`${dir}/YoutubeConfig.json`, "utf8"));
const script = readFileSync(`${dir}/YoutubeScript.js`, "utf8");
const prelude = readFileSync(process.argv[3], "utf8");

const allow = (config.allowUrls || []).map(s => s.toLowerCase());
function hostAllowed(u) {
  try {
    const h = new URL(u).hostname.toLowerCase();
    return allow.some(r => r === "everywhere" || h === r || h.endsWith("." + r));
  } catch { return false; }
}

globalThis.__host_http = (reqJson) => {
  const r = JSON.parse(reqJson);
  if (!hostAllowed(r.url)) {
    return JSON.stringify({ code: 403, headers: {}, body: "blocked", url: r.url });
  }
  // Separate files for body and headers: with -L there are multiple
  // header blocks, so splitting one combined stream corrupts the body.
  const bodyFile = `/tmp/gjprobe-body-${process.pid}`;
  const headFile = `/tmp/gjprobe-head-${process.pid}`;
  // Shared cookie jar: YouTube gates the watch page behind consent/
  // session cookies, and Grayjay's HttpClient persists them per client.
  const jar = `/tmp/gjprobe-jar-${process.pid}`;
  const args = ["-s", "-L", "--compressed", "--max-time", "30",
                "-c", jar, "-b", jar,
                "-o", bodyFile, "-D", headFile, "-w", "%{http_code}",
                "-X", r.method || "GET"];
  for (const [k, v] of Object.entries(r.headers || {})) args.push("-H", `${k}: ${v}`);
  if (r.body) args.push("--data-binary", String(r.body));
  args.push(r.url);
  try {
    const code = parseInt(execFileSync("curl", args).toString().trim(), 10);
    const body = readFileSync(bodyFile, "utf8");
    const headers = {};
    // Keep only the final response's headers.
    const blocks = readFileSync(headFile, "utf8").split(/\r?\n\r?\n/).filter(Boolean);
    for (const line of (blocks[blocks.length - 1] || "").split(/\r?\n/).slice(1)) {
      const i = line.indexOf(":");
      if (i > 0) headers[line.slice(0, i).toLowerCase()] = line.slice(i + 1).trim();
    }
    if (process.env.GJ_TRACE && /watch|player|youtubei/.test(r.url)) {
      console.error(`[trace] ${code} ${r.method || "GET"} ${r.url.slice(0, 90)} len=${body.length} head=${JSON.stringify(body.slice(0, 120))}`);
    }
    return JSON.stringify({ code, headers, body, url: r.url });
  } catch (e) {
    return JSON.stringify({ code: 0, headers: {}, body: String(e), url: r.url });
  }
};
const logs = [];
globalThis.__host_log = (m) => { logs.push(String(m).slice(0, 200)); };
globalThis.__host_sleep = () => {};
globalThis.__host_uuid = () => crypto.randomUUID();
globalThis.__host_md5 = (s) =>
  execFileSync("md5sum", { input: Buffer.from(s, "utf8") }).toString().split(" ")[0];
globalThis.__host_b64encode = (s) => Buffer.from(s, "utf8").toString("base64");
globalThis.__host_b64decode = (s) => Buffer.from(s, "base64").toString("utf8");
globalThis.__host_parse_url = (u, base) => {
  try {
    const x = base ? new URL(u, base) : new URL(u);
    return JSON.stringify({ ok: true, href: x.href, protocol: x.protocol,
      hostname: x.hostname, port: x.port, host: x.host, origin: x.origin,
      pathname: x.pathname, search: x.search, hash: x.hash,
      username: x.username, password: x.password });
  } catch { return JSON.stringify({ ok: false }); }
};

// Node already provides URL/URLSearchParams/console/timers, so strip the
// prelude's shims for those and keep the Grayjay runtime classes.
const trimmed = prelude
  .replace(/\/\/ --- WHATWG URL[\s\S]*?\/\/ --- timers/, "// --- timers")
  .replace(/let __timer_seq[\s\S]*?function queueMicrotask\(fn\)[^\n]*\n/, "")
  .replace(/const console = \{[\s\S]*?\n\};/, "");

// Plugins are sloppy-mode scripts that expect top-level `this` to be
// the global object (Grayjay runs them that way). runInThisContext gives
// exactly that, unlike an ES-module eval where `this` is undefined.
const t0 = Date.now();
vm.runInThisContext(trimmed + "\n" + script, { filename: "plugin.js" });
const source = globalThis.source;
console.log(`loaded unmodified plugin v${config.version} in ${Date.now() - t0}ms`);
source.enable(config, {}, "");
console.log("enable() ok");

const found = source.search("blender open movie", null, null, null);
const results = found.results || [];
console.log(`search -> ${results.length} results`);
if (results.length) {
  const t1 = Date.now();
  const details = await (source.getVideoDetails
    ? source.getVideoDetails(results[0].url)
    : source.getContentDetails(results[0].url));
  const d = details.video || {};
  const srcs = d.videoSources || Object.values(d).filter(x => x && x.url);
  console.log(`details in ${Date.now() - t1}ms: "${details.name}"`);
  console.log(`SOURCES: ${srcs.length}`);
  for (const s of srcs.slice(0, 6)) {
    console.log(`  - ${(s.constructor?.name || "?").padEnd(18)} ${String(s.name || "").slice(0,20).padEnd(22)} ${String(s.url || "").slice(0, 60)}`);
  }
}
console.log("logs:", logs.slice(-3));
