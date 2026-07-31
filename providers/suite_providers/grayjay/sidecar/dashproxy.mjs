// Local media proxy for plugin-generated DASH manifests.
//
// This is how Grayjay actually plays YouTube, and it needs no
// UMP implementation of our own. A source's `generate()` returns a DASH
// manifest whose segment URLs point at `grayjay.internal`, and the
// source's `getRequestExecutor()` returns an executor that produces the
// bytes for each of those URLs — doing the UMP work inside the plugin's
// own session, which is exactly why it is not refused.
//
// So the host's job is only to be that `grayjay.internal`: serve the
// manifest with its URLs rewritten to a loopback address, and answer
// each segment request by calling the executor.
import { createServer } from "node:http";

/**
 * Serve one source's manifest and segments over loopback.
 * Returns `{ url, port, close }` where `url` is the .mpd for a player.
 */
export async function serveDash(source, { host = "127.0.0.1" } = {}) {
  const manifest = await source.generate();
  if (typeof manifest !== "string" || !manifest.includes("<MPD")) {
    throw new Error("plugin did not return a DASH manifest");
  }
  const executor = typeof source.getRequestExecutor === "function"
    ? source.getRequestExecutor() : null;
  if (!executor || typeof executor.executeRequest !== "function") {
    throw new Error("source has no request executor for segments");
  }

  let origin = null;   // filled once we know the port

  const server = createServer(async (req, res) => {
    const path = req.url || "/";
    try {
      if (path === "/manifest.mpd") {
        // Point the player back at us instead of grayjay.internal.
        const body = manifest.replaceAll("https://grayjay.internal", origin);
        res.writeHead(200, {
          "Content-Type": "application/dash+xml",
          "Content-Length": Buffer.byteLength(body),
        });
        res.end(body);
        return;
      }
      // Anything else is a media request: hand the executor the URL it
      // minted, in the form it expects.
      const internalUrl = "https://grayjay.internal" + path;
      const out = await executor.executeRequest(internalUrl, {});
      const bytes = toBuffer(out);
      if (!bytes) {
        res.writeHead(502).end("executor returned no data");
        return;
      }
      res.writeHead(200, {
        "Content-Type": "application/octet-stream",
        "Content-Length": bytes.length,
      });
      res.end(bytes);
    } catch (e) {
      res.writeHead(500).end(String(e?.message || e));
    }
  });

  await new Promise((resolve) => server.listen(0, host, resolve));
  const { port } = server.address();
  origin = `http://${host}:${port}`;
  return {
    port,
    url: `${origin}/manifest.mpd`,
    close: () => new Promise((r) => server.close(r)),
  };
}

/** Executors return bytes in several shapes; normalize to a Buffer. */
function toBuffer(out) {
  if (!out) return null;
  if (Buffer.isBuffer(out)) return out;
  if (out instanceof Uint8Array) return Buffer.from(out);
  if (out instanceof ArrayBuffer) return Buffer.from(new Uint8Array(out));
  if (out.buffer instanceof ArrayBuffer) {
    return Buffer.from(new Uint8Array(out.buffer, out.byteOffset ?? 0,
                                      out.byteLength ?? out.length));
  }
  if (typeof out === "string") return Buffer.from(out, "latin1");
  if (Array.isArray(out)) return Buffer.from(out);
  return null;
}
