# Package-level license notices

This directory keeps the exact license and copyright files shipped with the
runtime dependencies (as opposed to the generic license texts in `../LICENSES/`).

- `python/` — every Python package installed in the production backend image
- `frontend/` — Vue, Pinia, Vue Router, and Inter

These files were copied from the installed package metadata (`.dist-info/licenses/`,
`LICENSE`, `COPYING`, or `NOTICE`). If a package had no separate license file, the
file records its declared license and upstream project URL.

For components without a package-level file here (aria2, Caddy, nginx, Alpine
packages), see `../THIRD_PARTY_NOTICES.md` and `../LICENSES/`.
