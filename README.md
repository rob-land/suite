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

License: GPL-3.0-or-later.
