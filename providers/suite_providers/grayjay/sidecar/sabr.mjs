// SABR/UMP playback bridge.
//
// YouTube no longer hands out plain progressive URLs: its sources are
// SABR sessions speaking UMP, where the server drives segment selection
// and audio+video arrive interleaved in one response. No ordinary player
// can consume that.
//
// LuanRT's `googlevideo` (MIT) implements the protocol and yields
// separate video and audio ReadableStreams. This module runs that
// session and republishes the two tracks over a loopback HTTP server, so
// mpv plays the video URL with the audio URL as `--audio-file`.
//
// Everything the session needs is on the source object the plugin
// returns (abrUrl, ustreamerConfig, the player response in options) plus
// the poToken the sidecar observes on the plugin's own player request.
//
// STATUS (2026-07-31): wired end to end and not yet playing. The session
// assembles correctly — 32 formats parse, config and clientInfo build,
// a 116-char poToken is captured — but googlevideo's segment fetches
// come back **403 Forbidden**. The likely cause is token binding:
// YouTube mints a poToken for the exact context that requested it
// (visitorData + client + video), so replaying the plugin's token from a
// separate session is refused. Grayjay avoids this because its native
// UMP player streams inside the plugin's own session.
//
// Next avenues, in order of promise:
//  1. Have the plugin drive playback — call its UMP/streaming path
//     directly rather than starting an independent session.
//  2. Mint our own poToken: the sidecar already executes the plugin's
//     botguard successfully, so the attestation machinery is present.
//  3. Match the session exactly (same visitorData, client id, and the
//     ustreamerConfig from the same player response as the abrUrl).
import { createServer } from "node:http";

let googlevideo = null;

async function load() {
  if (!googlevideo) {
    const [stream, utils] = await Promise.all([
      import("googlevideo/sabr-stream"),
      import("googlevideo/utils"),
    ]);
    googlevideo = { SabrStream: stream.SabrStream, ...utils };
  }
  return googlevideo;
}

export function sabrAvailable() {
  return load().then(() => true).catch(() => false);
}

/** Pull the streaming formats out of the plugin's player response. */
function formatsFrom(source, buildSabrFormat) {
  const player = source?.options?.playerData ?? source?.options?.player ?? {};
  const streaming = player.streamingData ?? {};
  const raw = [
    ...(streaming.adaptiveFormats ?? []),
    ...(streaming.formats ?? []),
  ];
  return raw.map((f) => buildSabrFormat(f)).filter(Boolean);
}

function poTokenFrom(source, session) {
  const bg = source?.bgData ?? {};
  // Prefer the token the plugin actually minted for this session (seen
  // on its own player request); the source object rarely carries one.
  return session?.poToken ?? bg.poToken ?? bg.potToken ?? bg.pot ?? source?.poToken;
}

// InnerTube client ids: WEB=1, MWEB=2, ANDROID=3, IOS=5, TVHTML5=7.
const CLIENT_IDS = { WEB: 1, MWEB: 2, ANDROID: 3, IOS: 5, TVHTML5: 7 };

function clientInfoFrom(source, session) {
  const bg = source?.bgData ?? {};
  return {
    clientName: CLIENT_IDS[bg.c] ?? 1,
    clientVersion: bg.cver ?? "2.20240000.00.00",
    osName: "X11",
    osVersion: "",
    visitorData: bg.visitorData ?? session?.visitorData,
  };
}

/**
 * Start a SABR session for `source` and serve its tracks on loopback.
 * Resolves with `{ videoUrl, audioUrl, port, close }`.
 */
export async function serveSabr(source, { host = "127.0.0.1", session } = {}) {
  const gv = await load();
  const formats = formatsFrom(source, gv.buildSabrFormat);
  if (!formats.length) {
    throw new Error("no streaming formats in the plugin's player response");
  }

  const streaming = (source?.options?.playerData ?? {}).streamingData ?? {};
  const sabr = new gv.SabrStream({
    serverAbrStreamingUrl:
      streaming.serverAbrStreamingUrl || source.abrUrl || source.url,
    videoPlaybackUstreamerConfig: source.ustreamerConfig,
    poToken: poTokenFrom(source, session),
    durationMs: (Number(source.duration) || 0) * 1000,
    formats,
    clientInfo: clientInfoFrom(source, session),
  });

  // Match the itag the caller picked; fall back to the library's own
  // quality selection when that format isn't offered as SABR.
  const wantItag = Number(source.itag) || undefined;
  const { videoStream, audioStream } = await sabr.start({
    videoFormat: (list) =>
      list.find((f) => f.itag === wantItag) ??
      list.filter((f) => f.mimeType?.startsWith("video/"))
          .sort((a, b) => (b.height ?? 0) - (a.height ?? 0))[0],
    audioFormat: (list) =>
      list.filter((f) => f.mimeType?.startsWith("audio/"))
          .sort((a, b) => (b.bitrate ?? 0) - (a.bitrate ?? 0))[0],
  });

  const tracks = { "/video": videoStream, "/audio": audioStream };
  const server = createServer(async (req, res) => {
    const track = tracks[(req.url || "").split("?")[0]];
    if (!track) {
      res.writeHead(404).end();
      return;
    }
    res.writeHead(200, {
      "Content-Type": "application/octet-stream",
      "Cache-Control": "no-store",
    });
    const reader = track.getReader();
    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        if (!res.write(Buffer.from(value))) {
          await new Promise((r) => res.once("drain", r));
        }
      }
    } catch {
      /* client went away mid-stream */
    } finally {
      try { reader.releaseLock(); } catch { /* already released */ }
      res.end();
    }
  });

  await new Promise((resolve) => server.listen(0, host, resolve));
  const { port } = server.address();
  return {
    port,
    videoUrl: `http://${host}:${port}/video`,
    audioUrl: `http://${host}:${port}/audio`,
    close: () => new Promise((r) => server.close(r)),
  };
}
