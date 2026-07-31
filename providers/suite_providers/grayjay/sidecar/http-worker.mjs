// HTTP worker for the Grayjay sidecar.
//
// The Grayjay plugin API is synchronous (`http.GET(...)` returns a
// response object), but Node's fetch is async. So the main thread hands
// a request to this worker and blocks on Atomics.wait; the worker does
// the fetch and wakes it with the serialized response. That is the
// standard way to expose async I/O to synchronous JS, and it keeps the
// plugin running exactly as it would inside Grayjay.
//
// The worker also owns the cookie jar: YouTube's InnerTube endpoints
// gate on session cookies, so cookies must persist across requests the
// way Grayjay's HttpClient does.
import { parentPort, workerData } from "node:worker_threads";

const { control, data, allowUrls } = workerData;
const ctl = new Int32Array(control);
const buf = new Uint8Array(data);
const encoder = new TextEncoder();

const DEFAULT_UA =
  "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) " +
  "Chrome/124.0.0.0 Safari/537.36";

// --- cookie jar -------------------------------------------------------
/** host -> Map(name -> value). Coarse but matches how plugins use it. */
const jar = new Map();

function jarKey(host) {
  const parts = String(host).toLowerCase().split(".");
  return parts.length > 2 ? parts.slice(-2).join(".") : parts.join(".");
}

function storeCookies(host, setCookieValues) {
  if (!setCookieValues || !setCookieValues.length) return;
  const key = jarKey(host);
  const store = jar.get(key) || new Map();
  for (const raw of setCookieValues) {
    const [pair] = String(raw).split(";");
    const i = pair.indexOf("=");
    if (i > 0) store.set(pair.slice(0, i).trim(), pair.slice(i + 1).trim());
  }
  jar.set(key, store);
}

function cookieHeader(host) {
  const store = jar.get(jarKey(host));
  if (!store || !store.size) return null;
  return [...store].map(([k, v]) => `${k}=${v}`).join("; ");
}

// --- allowUrls --------------------------------------------------------
function hostAllowed(url) {
  try {
    const host = new URL(url).hostname.toLowerCase();
    return allowUrls.some((rule) => {
      // A leading dot is the cookie-domain spelling of "this domain and
      // its subdomains" — YouTube's config uses it for the media CDN
      // (".googlevideo.com"). Strip it, or the suffix test builds an
      // impossible "..googlevideo.com" and silently blocks playback.
      const r = String(rule).toLowerCase()
        .replace(/^https?:\/\//, "").split("/")[0].replace(/^\./, "");
      return r === "everywhere" || r === "*" || host === r || host.endsWith("." + r);
    });
  } catch {
    return false;
  }
}

function reply(payload) {
  const bytes = encoder.encode(JSON.stringify(payload));
  const n = Math.min(bytes.length, buf.length);
  buf.set(bytes.subarray(0, n));
  Atomics.store(ctl, 1, n);
  Atomics.store(ctl, 0, 1);
  Atomics.notify(ctl, 0);
}

parentPort.on("message", async (req) => {
  const url = req.url || "";
  if (!hostAllowed(url)) {
    reply({ code: 403, headers: {}, body: `blocked by allowUrls: ${url}`, url });
    return;
  }
  try {
    const headers = { "User-Agent": DEFAULT_UA, ...(req.headers || {}) };
    if (req.useCookies !== false) {
      const cookie = cookieHeader(new URL(url).hostname);
      if (cookie && !headers.Cookie && !headers.cookie) headers.Cookie = cookie;
    }
    // Binary bodies travel as base64 over the (text) bridge. UMP
    // streaming is binary in both directions, and reading those
    // responses as UTF-8 corrupts them beyond recovery.
    const body = req.bodyIsBase64
      ? Buffer.from(String(req.body || ""), "base64")
      : (req.body ?? undefined);
    if (req.bodyIsBase64 && !headers["Content-Type"] && !headers["content-type"]) {
      // fetch() would otherwise stamp text/plain;charset=UTF-8 on a
      // Buffer body, which servers expecting protobuf (YouTube's UMP
      // endpoints) reject outright.
      headers["Content-Type"] = "application/x-protobuf";
    }
    const res = await fetch(url, {
      method: req.method || "GET",
      headers,
      body,
      redirect: "follow",
    });
    const host = new URL(res.url || url).hostname;
    storeCookies(host, res.headers.getSetCookie?.() ?? []);
    const out = {};
    for (const [k, v] of res.headers) out[k.toLowerCase()] = v;
    if (req.binary) {
      const bytes = Buffer.from(await res.arrayBuffer());
      reply({ code: res.status, headers: out, bodyIsBase64: true,
              body: bytes.toString("base64"), url: res.url || url });
    } else {
      reply({ code: res.status, headers: out, body: await res.text(),
              url: res.url || url });
    }
  } catch (e) {
    // Surface the cause: fetch collapses everything into "fetch failed"
    // and the real reason (protocol, TLS, body type) hides underneath.
    const cause = e?.cause ? ` | cause: ${e.cause?.message || e.cause}` : "";
    reply({ code: 0, headers: {},
            body: `host request failed: ${e}${cause}`, url });
  }
});

// NB: error responses are returned as text even for binary requests, so
// a plugin inspecting a failure body sees a readable message rather than
// base64. Plugins branch on `typeof body`, which keeps that safe.
