# Kodi addon host — research spike

Not shipped. A 398-line proof that Kodi video addons can be browsed and
resolved from plain Python with no Kodi installed, kept as the starting
point if we add Kodi as a second plugin ecosystem alongside Grayjay.

```sh
python minihost.py "plugin://plugin.video.fosdem/"
```

It emits either a directory listing or a resolved stream, as JSON.

## What the spike established

Verified end to end against addons fetched from the official Omega repo:

- **plugin.video.fosdem** — browse → year → day → room → resolved
  `https://video.fosdem.org/2024/.../*.mp4` (HTTP 200).
- **plugin.video.svtplay** — browse → **search** → resolved HLS
  (`hls-ts-avc.m3u8`).

Roughly **36%** of randomly sampled non-InputStream addons browsed
successfully at 398 lines; a mature host should reach **~55–65%**. The
residue is addon rot (`import imp`, `HTMLParser.unescape`, stale
scrapers) that fails in real Kodi on a modern distro too.

## The contract, in brief

Kodi invokes an addon's entry script with
`sys.argv = [plugin://id/path, handle, ?query, resume:false]`; the addon
calls `xbmcplugin.addDirectoryItem(...)` per row then `endOfDirectory`,
and playback is a second invocation ending in `setResolvedUrl`.
Stateless re-invocation per URL — so a host is mostly a module shim plus
a loader.

Details worth not rediscovering:

- Entry point comes from `addon.xml`'s `pluginsource library=`; it is
  **not** always `default.py`, and the entry script's *directory* must be
  on `sys.path`.
- Dependencies are just other addons: recurse `<requires>`, add each
  `xbmc.python.module` library dir to `sys.path`. The common ones
  (requests, beautifulsoup4, routing, dateutil, six) are pure Python.
- Some addons implement **search via `xbmc.Keyboard()`**, and some
  bypass `setResolvedUrl` for `xbmc.Player().play(...)` — intercept
  both. A pre-primed answer queue makes dialogs non-blocking.
- A JSON-RPC stub is mandatory: `plugin.video.youtube` calls
  `Application.GetProperties` at *import* time.
- Shim parameter *names* must match Kodi's — addons call by keyword.
- Parse addon XML with `defusedxml`; it comes off the network.

## Licensing — the real constraint

Kodi itself is GPL-2.0-**or-later**, so the API poses no problem. But of
177 official `plugin.video.*` addons, **~26 are GPL-2.0-only** —
including `plugin.video.youtube` — which is one-way incompatible with a
GPL-3.0 host when addons run in-process (they become a combined work).

Mitigations, best first: license the Kodi host module GPL-2.0-or-later
to match Kodi; run addons **out-of-process** (mere aggregation — also
what we want for crash containment and `sys.argv` safety); and never
bundle addons, fetching them at runtime from `mirrors.kodi.tv` exactly
as we do Grayjay plugins.

Also: "Kodi" is a registered trademark — don't name anything `kodi*`
user-facing, and keep any addon store separate from a real Kodi profile.

## Scope

Works: public-broadcaster catalogues (ARD/ZDF/SVT/Arte/NRK/CBC/RTVE),
conference and archive addons (FOSDEM, media.ccc.de, Archive.org),
simple API scrapers.

Won't: **Widevine** (no CDM in mpv/ffmpeg — hard stop), skinned
`WindowXML` addons, and `xbmc.Player`-callback addons without mpv IPC
heartbeats. Non-DRM `inputstream.adaptive` *is* translatable — it's a
manifest URL plus headers, which ffmpeg already handles.

## Effort

Cheaper than the Grayjay host: addons are already Python, already
synchronous, and the plugin contract is ~15 functions wide — no JS
engine, prelude, or sidecar. Estimate ~1 week for a solid host
(2d shim+loader, 1d settings/localization/vfs/JSON-RPC, 1d subprocess
isolation and the bounded resolve loop, 1–2d mapping to
`MediaProvider`/`StreamInfo`).

The ongoing cost is addon rot, not the host. Note also that yt-dlp
covers the big sites better — Kodi's unique value is regional
broadcaster **catalogues and browse structure**, not stream extraction.
