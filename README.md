# suite — shared design tokens + media providers

The cross-project foundation for the three shells: **zoetrope** (AR
glasses spatial shell), **couch** (10-foot TV shell), **hearth** (smart
display). Design rationale lives in the zoetrope repo:
`docs/16-suite-design-language.md` and `docs/17-zoetrope-ui-spec.md`.

## tokens/

One YAML source of truth (`tokens.yaml`) → generated, vendorable outputs
in `tokens/out/`:

- `tokens.css` — CSS custom properties (`--suite-*`) for web surfaces
  and GTK CSS.
- `tokens.py` — flat constants for the Python shells.

Regenerate with `python3 tokens/generate.py` (needs PyYAML). Angular
units (dmm) are first-class; px values are the 1080p/10-foot mapping.

## providers/

`suite_providers` — the backend-plugin abstraction, organized by media
kind, with stereo-3D awareness end to end:

- `models` — `StereoFormat` (matches stereoscope's probe slugs),
  `StereoHint` + `StereoConfidence` (none / name / server / probed),
  `StereoCapability` per backend, Watch Next `ResumeEntry` semantics,
  `VideoItem` / `PhotoItem`.
- `naming` — the shared filename rules (Kodi 3D flags + ripsaw's
  `.fsbs/.hsbs` outputs) and the Jellyfin `Video3DFormat` mapping.
- `provider` — `VideoLibrary` / `PhotoLibrary` interfaces (kid-mode
  rating cap is an interface obligation).
- `localfiles` — working reference implementation (ripsaw-style library
  walk, MPO/JPS/L-R-pair photos, `probe_upgrade()` via stereoscope).
- `jellyfin` / `plex` / `immich` — capability-documented stubs pending
  extraction from couch's implementations.

```sh
cd providers && python3 -m pytest tests/
```

### Plugin ecosystems

- `suite_providers/grayjay/` — runs **Grayjay** plugins (JavaScript;
  QuickJS in-process, or a Node sidecar for the heavier ones). Working
  for PeerTube and Odysee end to end; YouTube browses and searches.
- `suite_providers/kodi_research/` — a **research spike** (not shipped)
  proving Kodi video addons browse and resolve from plain Python with no
  Kodi installed. See its README for the plugin contract, the scope
  (broadcaster catalogues yes, Widevine never), and the licensing
  constraint that shapes any real implementation: ~26 of 177 official
  video addons are GPL-2.0-only, so a Kodi host module should itself be
  GPL-2.0-or-later and run addons out-of-process.

License: GPL-3.0-or-later (the Kodi host module, if built, should be
GPL-2.0-or-later — see `kodi_research/README.md`).
