// Grayjay plugin sidecar: runs one plugin under Node's V8.
//
// Why a sidecar at all: the Python-embeddable engines can't run the
// heavier plugins. QuickJS rejects YouTube's bundled JSDOM outright and
// miscompiles its runtime-built signature decryptor; the STPyV8 wheel
// fails ICU init. Node's V8 runs the plugin unmodified — JSDOM included
// — and executes YouTube's botguard attestation successfully.
//
// Protocol: line-delimited JSON on stdin/stdout.
//   -> {"id":1,"method":"call","name":"getHome","args":[]}
//   <- {"id":1,"ok":true,"result":{...},"logs":[...]}
// Requests are handled one at a time; plugin calls are synchronous by
// design (see http-worker.mjs).
import { readFileSync } from "node:fs";
import { createInterface } from "node:readline";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";
import { Worker } from "node:worker_threads";

const HERE = dirname(fileURLToPath(import.meta.url));
const RESPONSE_LIMIT = 96 * 1024 * 1024;   // player JS alone is ~3 MB

const [, , configPath, scriptPath, preludePath] = process.argv;
const config = JSON.parse(readFileSync(configPath, "utf8"));
const pluginScript = readFileSync(scriptPath, "utf8");
const prelude = readFileSync(preludePath, "utf8");

// --- synchronous HTTP via a worker + Atomics --------------------------
const control = new SharedArrayBuffer(8);
const data = new SharedArrayBuffer(RESPONSE_LIMIT);
const ctl = new Int32Array(control);
const buf = new Uint8Array(data);
const decoder = new TextDecoder();

const worker = new Worker(join(HERE, "http-worker.mjs"), {
  workerData: { control, data, allowUrls: config.allowUrls || [] },
});
worker.unref();

function httpSync(request) {
  Atomics.store(ctl, 0, 0);
  Atomics.store(ctl, 1, 0);
  worker.postMessage(request);
  // Block this thread until the worker signals completion. The worker
  // is a real thread, so it keeps running while we wait.
  Atomics.wait(ctl, 0, 0);
  const length = Atomics.load(ctl, 1);
  return decoder.decode(buf.subarray(0, length));
}

// --- host bridges the prelude expects ---------------------------------
const logs = [];

// SABR sessions need the Proof-of-Origin token, and plugins don't put it
// on the source objects they return — but they do send it to YouTube in
// their own player requests, which pass through this bridge. Observing
// what already flows through the host is enough; no plugin change.
const session = { poToken: null, visitorData: null };
const PO_TOKEN_RE = /"poToken"\s*:\s*"([^"]{20,})"/;
const VISITOR_RE = /"visitorData"\s*:\s*"([^"]{20,})"/;

function observeSession(request) {
  const body = typeof request.body === "string" ? request.body : "";
  if (!body) return;
  const po = PO_TOKEN_RE.exec(body);
  if (po) session.poToken = po[1];
  const vd = VISITOR_RE.exec(body);
  if (vd) session.visitorData = vd[1];
}

globalThis.__host_http = (requestJson) => {
  const request = JSON.parse(requestJson);
  observeSession(request);
  if (process.env.GJ_TRACE_BIN && /videoplayback|googlevideo/.test(request.url || "")) {
    globalThis.__host_log(`[bin-trace] ${request.method} binary=${request.binary} ` +
      `bodyIsBase64=${request.bodyIsBase64} url=${String(request.url).slice(0, 60)}`);
  }
  const out = httpSync(request);
  if (process.env.GJ_TRACE_BIN && /videoplayback|googlevideo/.test(request.url || "")) {
    const p = JSON.parse(out);
    globalThis.__host_log(`[bin-trace] <- code=${p.code} bodyIsBase64=${p.bodyIsBase64} ` +
      `bodyType=${typeof p.body} len=${(p.body || "").length}`);
  }
  return out;
};
globalThis.__host_log = (message) => {
  logs.push(String(message).slice(0, 2000));
  if (logs.length > 200) logs.splice(0, logs.length - 200);
};
globalThis.__host_sleep = (ms) => {
  // Synchronous sleep: plugins use it for retry backoff mid-call.
  const until = Date.now() + Math.min(Number(ms) || 0, 5000);
  while (Date.now() < until) { /* spin */ }
};
globalThis.__host_uuid = () => crypto.randomUUID();
globalThis.__host_md5 = (s) =>
  createHash("md5").update(String(s), "utf8").digest("hex");
globalThis.__host_b64encode = (s) => Buffer.from(String(s), "utf8").toString("base64");
globalThis.__host_b64decode = (s) => Buffer.from(String(s), "base64").toString("utf8");
// Byte-exact variants for the binary transport: latin1 maps each byte
// to one code unit, so no UTF-8 re-encoding mangles the payload.
globalThis.__host_b64encode_raw = (s) =>
  Buffer.from(String(s), "latin1").toString("base64");
globalThis.__host_b64decode_raw = (s) =>
  Buffer.from(String(s), "base64").toString("latin1");
globalThis.__host_parse_url = (url, base) => {
  try {
    const u = base ? new URL(url, base) : new URL(url);
    return JSON.stringify({
      ok: true, href: u.href, protocol: u.protocol, hostname: u.hostname,
      port: u.port, host: u.host, origin: u.origin, pathname: u.pathname,
      search: u.search, hash: u.hash, username: u.username, password: u.password,
    });
  } catch {
    return JSON.stringify({ ok: false });
  }
};
import { createHash } from "node:crypto";

// stdout is the RPC channel, so the plugin must never write to it —
// and these scripts are chatty (YouTube dumps whole HTTP responses).
// Installing this before the prelude means its "fill in what's missing"
// pass keeps these implementations rather than Node's stdout-backed
// console.
globalThis.console = {
  log: globalThis.__host_log, info: globalThis.__host_log,
  debug: globalThis.__host_log, warn: globalThis.__host_log,
  error: globalThis.__host_log, trace: globalThis.__host_log,
  exception: globalThis.__host_log,
  dir: (o) => globalThis.__host_log(JSON.stringify(o)),
  table: (o) => globalThis.__host_log(JSON.stringify(o)),
  clear: () => {}, group: () => {}, groupEnd: () => {},
  groupCollapsed: () => {}, time: () => {}, timeEnd: () => {},
  count: () => {}, firebug: false,
  assert: (cond, ...rest) => {
    if (!cond) globalThis.__host_log("assert failed: " + rest.join(" "));
  },
};

// --- load the plugin ---------------------------------------------------
// Sloppy mode via runInThisContext: plugins assign to top-level `this`
// (Grayjay runs them the same way). An ESM/strict eval throws
// "Cannot set properties of undefined" partway through YouTube's script.
vm.runInThisContext(prelude + "\n" + pluginScript, { filename: "plugin.js" });

function pluginContext() {
  return globalThis.source;
}

function reply(payload) {
  process.stdout.write(JSON.stringify(payload) + "\n");
}

// Sources whose methods must outlive the RPC hop. JSON marshalling
// drops functions, so a source that can build its own manifest
// (`generate()` — how YouTube's UMP sources stream) would arrive in
// Python as inert data. Keep the live object here and hand Python a
// handle it can call back with.
const liveSources = new Map();
let liveSeq = 0;

function marshal(value) {
  const seen = new WeakSet();
  const walk = (v) => {
    if (v === null || typeof v !== "object") {
      return typeof v === "function" ? undefined : v;
    }
    if (seen.has(v)) return undefined;      // plugins build cyclic contexts
    seen.add(v);
    if (Array.isArray(v)) return v.map(walk);
    const out = {};
    for (const key of Object.keys(v)) {
      const child = walk(v[key]);
      if (child !== undefined) out[key] = child;
    }
    if (typeof v.generate === "function") {
      const id = `live-${++liveSeq}`;
      liveSources.set(id, v);
      out.__liveId = id;
    }
    return out;
  };
  return walk(value ?? null) ?? null;
}

async function handle(msg) {
  const source = pluginContext();
  try {
    if (msg.method === "has") {
      return { ok: true, result: typeof source?.[msg.name] === "function" };
    }
    if (msg.method === "context") {
      globalThis.__set_plugin_context(
        JSON.stringify(msg.config ?? config), JSON.stringify(msg.settings ?? {}));
      return { ok: true, result: true };
    }
    if (msg.method === "sessionfull") {
      return { ok: true, result: { poToken: session.poToken,
                                   visitorData: session.visitorData } };
    }
    if (msg.method === "session") {
      return { ok: true, result: {
        poToken: session.poToken ? session.poToken.slice(0, 24) + "..." : null,
        poTokenLen: session.poToken ? session.poToken.length : 0,
        visitorData: !!session.visitorData } };
    }
    if (msg.method === "sabr") {
      // Republish a SABR/UMP source as loopback HTTP for a normal player.
      const { serveSabr } = await import("./sabr.mjs");
      const served = await serveSabr(msg.source, { session });
      sabrSessions.push(served);
      return { ok: true, result: { videoUrl: served.videoUrl,
                                   audioUrl: served.audioUrl,
                                   port: served.port } };
    }
    if (msg.method === "call") {
      const fn = source?.[msg.name];
      if (typeof fn !== "function") {
        return { ok: false, error: `plugin has no ${msg.name}` };
      }
      // Some newer paths (the YouTube session client) are async.
      const out = await fn.apply(source, msg.args || []);
      return { ok: true, result: marshal(out) };
    }
    if (msg.method === "generate") {
      // Ask the plugin to build a playable manifest for a source it
      // returned earlier. YouTube's UMP sources do their streaming right
      // here, inside the plugin's own session — which is exactly why
      // this path works where an independent SABR session is refused.
      const live = liveSources.get(msg.liveId);
      if (!live) return { ok: false, error: `unknown source ${msg.liveId}` };
      if (typeof live.generate !== "function") {
        return { ok: false, error: "source has no generate()" };
      }
      const dash = await live.generate();
      const modifier = typeof live.getRequestModifier === "function"
        ? marshal(live.getRequestModifier()) : null;
      return { ok: true, result: { dash: marshal(dash), modifier } };
    }
    return { ok: false, error: `unknown method ${msg.method}` };
  } catch (e) {
    return { ok: false, error: String(e?.stack || e) };
  }
}

// Live SABR servers, closed when the sidecar shuts down.
const sabrSessions = [];

const rl = createInterface({ input: process.stdin });
let queue = Promise.resolve();
rl.on("line", (line) => {
  if (!line.trim()) return;
  let msg;
  try {
    msg = JSON.parse(line);
  } catch {
    return;
  }
  // Serialize: one plugin call at a time, like a real JS runtime.
  queue = queue.then(async () => {
    const out = await handle(msg);
    const taken = logs.splice(0, logs.length);
    reply({ id: msg.id, ...out, logs: taken });
  });
});
rl.on("close", async () => {
  await Promise.allSettled(sabrSessions.map((s) => s.close()));
  process.exit(0);
});

reply({ id: 0, ok: true, result: "ready", logs: [] });
