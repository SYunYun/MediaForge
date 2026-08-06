# MediaForge — Agent-native media stack toolbox

**Hunt module: a Cardigann-format indexer interpreter + search/pick/add pipeline
that replaces the Prowlarr position in an agent-native way.**

Mediaforge exists because the big media components (Jellyfin/qBittorrent/Prowlarr)
are muscle we don't need to rebuild — but the *thin* parts worth owning are the
ones whose value lives in community-maintained definitions. We stand on those
definitions and rewrite the thin shell as agent-native code.

## Design tenets

1. **Tools for agents differ from tools for humans.** Agents retry, time out, and
   restart from scratch — every write must be idempotent, every error loud.
2. **Path mapping / configuration is derived, never memorized.** No guessing,
   no human memory as the source of truth.
3. **Taste stays with the human.** The machine hunts, scores, and feeds; naming
   and final selection belong to the owner.

## Quick start

```bash
pip install mediaforge-ctl

mediaforge indexers update          # pull community indexer definitions
mediaforge search "inside job"      # multi-indexer search, scored & sorted
mediaforge pick "inside job" --index 3   # pick by rank
mediaforge add <magnet|infohash>    # idempotent qbit feed (infohash dedup)
mediaforge config show              # ~/.config/mediaforge/config.yaml
```

All commands emit JSON with `--json` — the same surface an agent uses.

## Architecture

```
mediaforge
├── cardigann/   # Go-template-subset renderer + filter pipeline + definition engine
├── hunt/        # search orchestration + health scoring (seeders/size bands/groups)
└── feed/        # idempotent qbit client (5.x quirks built in)
```

Definitions are **not** bundled: fetched from the Jackett community repo on
first use and cached under `~/.cache/mediaforge/indexers/`.

## Roadmap — 完全体（the full form）

**Endgame: one daemon replaces the whole arr stack.** `hunt → get → organize → subs`,
all agent-native. The final media stack is just **MediaForge + Jellyfin**.

```
mediaforged   (resident daemon · FastAPI on localhost · systemd user)
├── hunt      ✅ Cardigann interpreter + search/pick/add + scoring — 116 tests
├── subs      ⬜ subtitle engine (SubHD pipeline, bilingual synthesis, alignment, QA)
├── get       ⬜ embedded libtorrent session — dual backend: libtorrent | qbit
└── organize  ⬜ hardlink import + naming + Jellyfin refresh (ports from media-ctl)

mediaforge (CLI) = thin client talking to the daemon over localhost
```

- [x] hunt: Cardigann interpreter (subset) — 66 tests
- [x] hunt: search/pick/add CLI + scoring + idempotent qbit feed — 116 tests
- [ ] subs: agent-native subtitle engine — core already battle-tested scripts
      (SubHD pipeline, bilingual synthesis, alignment, QA)
- [ ] get: daemon + embedded libtorrent session (`--engine libtorrent|qbit`);
      switches after the 174G seeding debt clears
- [ ] organize: hardlink import + Sxx parsing + idempotent inode dedup +
      Jellyfin refresh (generalizes media-ctl intake/hook)
- [ ] hunt+: more HTML indexers, proxy-aware retry, torrent health diagnostics

Daemon invariants: idempotent writes · derived (never memorized) config ·
everything JSON self-describing (OpenAPI) · taste stays with the human —
selection, naming, and collector-grade subtitle calls are human decisions.

## Known gaps (honest)

- Go-regexp `\p{...}` unicode classes not supported by Python `re` — the filter
  is skipped with a warning (e.g. TPB's CJK-normalization filter).
- Sites behind Cloudflare Turnstile (1337x, EZTV, KAT) are unusable from scripts;
  mirror rotation is the practical answer, not headless-browser heroics.
- Login/captcha-protected indexers are out of scope for v0.1.

See `docs/pitfalls.md` for the war stories behind the design decisions.
