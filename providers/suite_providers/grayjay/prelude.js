// Grayjay plugin runtime, host side (JS half).
//
// Plugins are written against Grayjay's globals (`http`, `bridge`,
// `utility`, the Platform* / *Pager classes). This prelude defines them
// on top of three synchronous Python callables the host installs:
//
//   __host_http(requestJson) -> responseJson
//   __host_log(message)
//   __host_sleep(ms)
//
// Everything else is plain JS so plugin scripts run unmodified.

// --- exceptions -------------------------------------------------------
class ScriptException extends Error {
    constructor(a, b) {
        super(b === undefined ? a : b);
        this.plugin_type = b === undefined ? "ScriptException" : a;
        this.message = b === undefined ? a : b;
    }
}
class TimeoutException extends ScriptException {}
class CriticalException extends ScriptException {}
class LoginRequiredException extends ScriptException {}
class UnavailableException extends ScriptException {}
class AgeException extends ScriptException {}

// --- value types ------------------------------------------------------
class Thumbnail {
    constructor(url, quality) { this.url = url; this.quality = quality || 0; }
}
class Thumbnails {
    constructor(sources) { this.sources = sources || []; }
}
class PlatformID {
    constructor(platform, value, pluginId, claimType, claimFieldType) {
        this.platform = platform; this.value = value; this.pluginId = pluginId;
        this.claimType = claimType || 0;
        this.claimFieldType = claimFieldType === undefined ? -1 : claimFieldType;
    }
}
class PlatformAuthorLink {
    constructor(id, name, url, thumbnail, subscribers) {
        this.id = id; this.name = name; this.url = url;
        this.thumbnail = thumbnail; this.subscribers = subscribers;
    }
}
function _assign(target, def) { Object.assign(target, def || {}); return target; }

class PlatformVideo { constructor(def) { _assign(this, def); this.contentType = 1; } }
class PlatformVideoDetails extends PlatformVideo {}
class PlatformContent { constructor(def) { _assign(this, def); } }
class PlatformPost { constructor(def) { _assign(this, def); this.contentType = 2; } }
class PlatformChannel { constructor(def) { _assign(this, def); } }
class PlatformPlaylist { constructor(def) { _assign(this, def); } }
class PlatformPlaylistDetails extends PlatformPlaylist {}
class PlatformNestedMediaContent { constructor(def) { _assign(this, def); } }
class PlatformPostDetails { constructor(def) { _assign(this, def); this.contentType = 2; } }
class PlatformArticle { constructor(def) { _assign(this, def); } }
class PlatformArticleDetails extends PlatformArticle {}
class PlatformLockedContent { constructor(def) { _assign(this, def); } }
class PlatformChannelDetails extends PlatformChannel {}
class PlatformLiveEvent { constructor(def) { _assign(this, def); } }
class Playlist { constructor(def) { _assign(this, def); } }
class Chapter { constructor(def) { _assign(this, def); } }
class Subtitle { constructor(def) { _assign(this, def); } }

// Descriptors accept either a def object ({videoSources: [...]}) or a
// bare array of sources — plugins use both spellings.
class VideoSourceDescriptor {
    constructor(def) {
        if (Array.isArray(def)) { this.videoSources = def; }
        else { _assign(this, def); }
    }
}
class MuxVideoSourceDescriptor extends VideoSourceDescriptor {
    constructor(def) { super(def); this.isUnMuxed = false; }
}
class UnMuxVideoSourceDescriptor extends VideoSourceDescriptor {
    constructor(a, b) {
        super(Array.isArray(a) ? { videoSources: a, audioSources: b } : a);
        this.isUnMuxed = true;
    }
}
class VideoUrlSource { constructor(def) { _assign(this, def); this.plugin_type = "VideoUrlSource"; } }
class AudioUrlSource { constructor(def) { _assign(this, def); this.plugin_type = "AudioUrlSource"; } }
class VideoUrlWidevineSource extends VideoUrlSource {}
class AudioUrlWidevineSource extends AudioUrlSource {}
class HLSSource { constructor(def) { _assign(this, def); this.plugin_type = "HLSSource"; } }
class DashSource { constructor(def) { _assign(this, def); this.plugin_type = "DashSource"; } }
class DashManifestRawSource { constructor(def) { _assign(this, def); this.plugin_type = "DashManifestRawSource"; } }
class DashManifestRawAudioSource extends DashManifestRawSource {}
class VideoUrlRangeSource extends VideoUrlSource {}
class AudioUrlRangeSource extends AudioUrlSource {}
class JSSource { constructor(def) { _assign(this, def); } }

class RatingLikes { constructor(likes) { this.likes = likes; this.type = 1; } }
class RatingLikesDislikes {
    constructor(likes, dislikes) { this.likes = likes; this.dislikes = dislikes; this.type = 2; }
}
class RatingScaler { constructor(value) { this.value = value; this.type = 3; } }
class Comment { constructor(def) { _assign(this, def); } }

// --- pagers -----------------------------------------------------------
class Pager {
    constructor(results, hasMore, context) {
        this.results = results || [];
        this.hasMore = !!hasMore;
        this.context = context;
    }
    hasMorePagers() { return this.hasMore; }
    nextPage() { return this; }
}
class VideoPager extends Pager {}
class ChannelPager extends Pager {}
class CommentPager extends Pager {}
class PlaylistPager extends Pager {}
class ContentPager extends Pager {}
class LiveEventPager extends Pager {}

class ResultCapabilities {
    constructor(types, sorts, filters) {
        this.types = types || []; this.sorts = sorts || []; this.filters = filters || [];
    }
}
class FilterGroup {
    constructor(name, filters, isMultiSelect, id) {
        this.name = name; this.filters = filters; this.isMultiSelect = isMultiSelect; this.id = id;
    }
}
class FilterCapability {
    constructor(name, value, id) { this.name = name; this.value = value; this.id = id; }
}

// --- http bridge ------------------------------------------------------
class HttpResponse {
    constructor(raw) {
        this.code = raw.code; this.headers = raw.headers || {};
        this.body = raw.body; this.url = raw.url;
    }
    isOk() { return this.code >= 200 && this.code < 300; }
}

// Base64 helpers for the binary transport (the RPC channel is text).
function _bytesToB64(bytes) {
    let s = "";
    for (let i = 0; i < bytes.length; i++) { s += String.fromCharCode(bytes[i]); }
    return __host_b64encode_raw ? __host_b64encode_raw(s) : btoa(s);
}
function _b64ToBytes(b64) {
    const s = __host_b64decode_raw ? __host_b64decode_raw(b64) : atob(b64);
    const out = new Uint8Array(s.length);
    for (let i = 0; i < s.length; i++) { out[i] = s.charCodeAt(i) & 0xff; }
    return out;
}

/**
 * `binary` is Grayjay's 5th http argument: the request body is raw bytes
 * and the response body must come back as bytes, not text. YouTube's UMP
 * streaming uses it for everything, and decoding those responses as
 * UTF-8 silently corrupts them.
 */
function _request(method, url, body, headers, useAuth, binary) {
    const isBytes = body && typeof body === "object" &&
                    typeof body.length === "number" &&
                    typeof body !== "string";
    const raw = __host_http(JSON.stringify({
        method: method, url: url,
        body: isBytes ? _bytesToB64(body) : (body === undefined ? null : body),
        bodyIsBase64: !!isBytes,
        headers: headers || {}, useAuth: !!useAuth,
        binary: !!binary,
    }));
    const parsed = JSON.parse(raw);
    if (parsed.bodyIsBase64) { parsed.body = _b64ToBytes(parsed.body || ""); }
    return new HttpResponse(parsed);
}

class HttpClient {
    constructor(useAuth) { this._useAuth = !!useAuth; this._headers = {}; }
    setDefaultHeaders(h) { this._headers = h || {}; return this; }
    setDoUpdateCookies() { return this; }
    setDoApplyCookies() { return this; }
    setDoAllowNewCookies() { return this; }
    clearCookies() { return this; }
    GET(url, headers, useAuth, binary) {
        return _request("GET", url, undefined,
                        Object.assign({}, this._headers, headers || {}),
                        useAuth === undefined ? this._useAuth : useAuth, binary);
    }
    POST(url, body, headers, useAuth, binary) {
        return _request("POST", url, body,
                        Object.assign({}, this._headers, headers || {}),
                        useAuth === undefined ? this._useAuth : useAuth, binary);
    }
    request(method, url, headers, useAuth, binary) {
        return _request(method, url, undefined,
                        Object.assign({}, this._headers, headers || {}),
                        useAuth, binary);
    }
    requestWithBody(method, url, body, headers, useAuth, binary) {
        return _request(method, url, body,
                        Object.assign({}, this._headers, headers || {}),
                        useAuth, binary);
    }
    // Plugins fetch these to reuse the host's identity; we have none.
    static fromAuth() { return new HttpClient(true); }
}

class BatchBuilder {
    constructor() { this._ops = []; }
    GET(url, headers, useAuth, binary) { this._ops.push(["GET", url, undefined, headers, useAuth, binary]); return this; }
    POST(url, body, headers, useAuth, binary) { this._ops.push(["POST", url, body, headers, useAuth, binary]); return this; }
    request(method, url, headers, useAuth) { this._ops.push([method, url, undefined, headers, useAuth]); return this; }
    requestWithBody(method, url, body, headers, useAuth) {
        this._ops.push([method, url, body, headers, useAuth]); return this;
    }
    clientGET(client, url, headers, useAuth) { return this.GET(url, headers, useAuth); }
    clientPOST(client, url, body, headers, useAuth) { return this.POST(url, body, headers, useAuth); }
    // A no-op slot that keeps result indices aligned when a plugin
    // conditionally skips a request in a batch. Plugins feature-detect
    // it (`!!batch.DUMMY`) to decide whether the host is modern enough
    // for their newer code paths, so it must exist.
    DUMMY() { this._ops.push(null); return this; }
    execute() {
        // Sequential is correct-if-slow; the host may parallelize later.
        return this._ops.map(o => o === null
            ? new HttpResponse({ code: 0, headers: {}, body: "", url: "" })
            : _request(o[0], o[1], o[2], o[3], o[4], o[5]));
    }
}

const http = {
    GET: (url, headers, useAuth, binary) =>
        _request("GET", url, undefined, headers, useAuth, binary),
    POST: (url, body, headers, useAuth, binary) =>
        _request("POST", url, body, headers, useAuth, binary),
    request: (method, url, headers, useAuth, binary) =>
        _request(method, url, undefined, headers, useAuth, binary),
    requestWithBody: (method, url, body, headers, useAuth, binary) =>
        _request(method, url, body, headers, useAuth, binary),
    newClient: (useAuth) => new HttpClient(useAuth),
    getDefaultClient: (useAuth) => new HttpClient(useAuth),
    batch: () => new BatchBuilder(),
    socket: () => { throw new ScriptException("websockets unsupported"); },
};

// --- bridge / utility -------------------------------------------------
const bridge = {
    log: (m) => __host_log(typeof m === "string" ? m : JSON.stringify(m)),
    sleep: (ms) => __host_sleep(ms),
    toast: (m) => __host_log("[toast] " + m),
    isLoggedIn: () => false,
    hasPackage: (p) => ["Http", "Utilities", "DOMParser"].indexOf(p) >= 0,
    buildPlatform: () => "suite",
    buildSpecVersion: () => 1,
    buildVersion: () => 1,
    buildFlavor: () => "suite",
    getHardwareCodecs: () => [],
    // A property, not a method — plugins do `bridge.supportedFeatures ?? []`
    // and then `.indexOf(...)` on it.
    supportedFeatures: [],
    devSubmit: () => {},
    throwTimeout: () => { throw new TimeoutException("timeout"); },
};
const packageBridge = bridge;
const log = bridge.log;

// Plugins reach for the full console surface (clear/assert/trace/table
// and friends), and a missing method is a hard TypeError mid-extraction
// rather than a degraded log line — so implement all of it.
const __console = (typeof console !== "undefined" && console) ? console : {};
const __hostConsole = {
    log: bridge.log,
    info: bridge.log,
    debug: bridge.log,
    warn: bridge.log,
    error: bridge.log,
    exception: bridge.log,
    trace: bridge.log,
    dir: (o) => bridge.log(JSON.stringify(o)),
    table: (o) => bridge.log(JSON.stringify(o)),
    clear: () => {},
    group: () => {}, groupEnd: () => {}, groupCollapsed: () => {},
    time: () => {}, timeEnd: () => {}, count: () => {},
    firebug: false,
    assert: (cond, ...rest) => {
        if (!cond) { bridge.log("assert failed: " + rest.join(" ")); }
    },
};
// Fill only what the host engine lacks; plugins call clear/assert/
// trace/table and a missing one is a hard TypeError mid-extraction.
for (const k of Object.keys(__hostConsole)) {
    if (typeof __console[k] === "undefined") { __console[k] = __hostConsole[k]; }
}
globalThis.console = __console;

// Grayjay's "Utilities" package. md5String matters more than it looks:
// the YouTube plugin hashes YouTube's player JS and asks FUTO's remote
// solver for the matching signature-decryption solution, which is how it
// avoids executing player code locally.
const utility = {
    md5String: (s) => __host_md5(String(s)),
    toBase64: (s) => __host_b64encode(String(s)),
    fromBase64: (s) => __host_b64decode(String(s)),
    randomUUID: () => __host_uuid(),
    fromNow: (s) => 0,
    toHumanNumber: (n) => String(n),
};
const packageUtilities = utility;

// --- WHATWG URL -------------------------------------------------------
// QuickJS ships no URL/URLSearchParams; plugins use both freely.
// Parsing is delegated to Python's urllib so it matches the host's own
// view of a URL (the same view allowUrls is enforced against).
if (typeof URLSearchParams === "undefined") {
class URLSearchParams {
    constructor(init) {
        this._p = [];
        if (typeof init === "string") {
            init.replace(/^\?/, "").split("&").filter(Boolean).forEach(kv => {
                const i = kv.indexOf("=");
                const k = i < 0 ? kv : kv.slice(0, i);
                const v = i < 0 ? "" : kv.slice(i + 1);
                this._p.push([decodeURIComponent(k.replace(/\+/g, " ")),
                              decodeURIComponent(v.replace(/\+/g, " "))]);
            });
        } else if (init && typeof init === "object") {
            Object.keys(init).forEach(k => this._p.push([k, String(init[k])]));
        }
    }
    append(k, v) { this._p.push([k, String(v)]); }
    set(k, v) { this.delete(k); this.append(k, v); }
    get(k) { const e = this._p.find(p => p[0] === k); return e ? e[1] : null; }
    getAll(k) { return this._p.filter(p => p[0] === k).map(p => p[1]); }
    has(k) { return this._p.some(p => p[0] === k); }
    delete(k) { this._p = this._p.filter(p => p[0] !== k); }
    forEach(fn) { this._p.forEach(p => fn(p[1], p[0], this)); }
    keys() { return this._p.map(p => p[0]); }
    values() { return this._p.map(p => p[1]); }
    entries() { return this._p.map(p => [p[0], p[1]]); }
    toString() {
        return this._p.map(p => encodeURIComponent(p[0]) + "=" +
                                encodeURIComponent(p[1])).join("&");
    }
}

globalThis.URLSearchParams = URLSearchParams;
}

if (typeof URL === "undefined") {
class URL {
    constructor(url, base) {
        const parsed = JSON.parse(__host_parse_url(String(url),
                                                   base ? String(base) : ""));
        if (!parsed.ok) { throw new TypeError("Invalid URL: " + url); }
        this.href = parsed.href;
        this.protocol = parsed.protocol;
        this.hostname = parsed.hostname;
        this.port = parsed.port;
        this.host = parsed.host;
        this.origin = parsed.origin;
        this.pathname = parsed.pathname;
        this.search = parsed.search;
        this.hash = parsed.hash;
        this.username = parsed.username;
        this.password = parsed.password;
        this.searchParams = new URLSearchParams(parsed.search);
    }
    toString() { return this.href; }
    toJSON() { return this.href; }
}
globalThis.URL = URL;
}

// --- timers -----------------------------------------------------------
// QuickJS has no event loop and the Grayjay API is synchronous, so
// timers run inline: setTimeout sleeps (capped) then invokes, which
// matches how plugins use it (deferring/retry backoff inside one call).
// setInterval would never terminate, so it registers and never fires.
let __timer_seq = 1;
if (typeof setTimeout === "undefined") {
function setTimeout(fn, ms) {
    const id = __timer_seq++;
    if (typeof fn === "function") {
        if (ms > 0) { __host_sleep(Math.min(ms, 2000)); }
        try { fn(); } catch (e) { bridge.log("setTimeout callback: " + e); }
    }
    return id;
}
function clearTimeout(id) {}
function setInterval(fn, ms) { return __timer_seq++; }
function clearInterval(id) {}
globalThis.setTimeout = setTimeout;
globalThis.clearTimeout = clearTimeout;
globalThis.setInterval = setInterval;
globalThis.clearInterval = clearInterval;
}
if (typeof queueMicrotask === "undefined") {
    globalThis.queueMicrotask = function (fn) {
        try { fn(); } catch (e) { bridge.log("" + e); }
    };
}

// --- host classes plugins subclass -------------------------------------
// Grayjay exposes these for playback progress reporting and per-request
// header rewriting; plugins extend them. We keep the shapes and let the
// consumer (GrayjayProvider) read the fields it cares about.
class PlaybackTracker {
    constructor(interval) { this.nextRequest = interval || 10000; }
    setProgress(seconds) {}
    onConcluded() {}
    onInit(seconds) {}
}
class RequestModifier {
    constructor(def) { Object.assign(this, def || {}); }
    modifyRequest(url, headers) { return { url: url, headers: headers }; }
}

// --- the globals plugins assign onto -----------------------------------
// Grayjay predefines an empty `source` (plugins do `source.getHome = ...`)
// plus the config/settings globals the scripts read at load time.
var source = {};
// The host fills these before any source.* call: plugins read
// plugin.config.constants (e.g. a PeerTube instance baseUrl) and
// plugin.settings directly, not just the enable() arguments.
var plugin = { config: {}, settings: {}, state: {} };
function __set_plugin_context(configJson, settingsJson) {
    plugin.config = JSON.parse(configJson);
    plugin.settings = JSON.parse(settingsJson);
    if (!plugin.config.constants) { plugin.config.constants = {}; }
    return true;
}
var IS_TESTING = false;
var Type = {
    Source: { Video: "VIDEO", Audio: "AUDIO", Subtitle: "SUBTITLE" },
    Feed: { Videos: "VIDEOS", Streams: "STREAMS", Mixed: "MIXED",
            Live: "LIVE", Posts: "POSTS", Playlists: "PLAYLISTS",
            Subscriptions: "SUBSCRIPTIONS" },
    Order: { Chronological: "CHRONOLOGICAL", Views: "VIEWS" },
    Date: { LastHour: "LAST_HOUR", Today: "TODAY", LastWeek: "LAST_WEEK",
            LastMonth: "LAST_MONTH", LastYear: "LAST_YEAR" },
    Duration: { Short: "SHORT", Medium: "MEDIUM", Long: "LONG" },
    Text: { RAW: 0, HTML: 1, MARKUP: 2 },
    Chapter: { NORMAL: 0, SKIPPABLE: 1, SKIP: 2, SKIPONCE: 3 },
};
const Language = {
    UNKNOWN: "Unknown", ENGLISH: "en", SPANISH: "es", FRENCH: "fr",
    GERMAN: "de", ITALIAN: "it", PORTUGUESE: "pt", RUSSIAN: "ru",
    JAPANESE: "ja", KOREAN: "ko", CHINESE: "zh", ARABIC: "ar",
    HINDI: "hi", DUTCH: "nl", POLISH: "pl", TURKISH: "tr",
};

// --- plugin lifecycle helpers the host calls --------------------------
// `source` is defined by the plugin script itself; these wrappers make
// results JSON-marshallable and errors legible.
function __call_source(method, argsJson) {
    const args = JSON.parse(argsJson || "[]");
    if (typeof source === "undefined" || typeof source[method] !== "function") {
        throw new ScriptException("plugin has no " + method);
    }
    const out = source[method].apply(source, args);
    return JSON.stringify(out === undefined ? null : out, (k, v) =>
        (typeof v === "function" ? undefined : v));
}
function __has_source_method(method) {
    return typeof source !== "undefined" && typeof source[method] === "function";
}
