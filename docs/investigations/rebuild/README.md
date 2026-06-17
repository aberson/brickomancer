# Brickomancer Rebuild Investigation

Investigation conducted 2026-06-16 to decide how to rebuild Brickomancer with a stronger
model and a cleaner architecture, distilling the proven-valuable artifacts from the v1
codebase (built largely by an older model) before starting over.

**Decision drivers (from the owner):** output-quality plateau (the harness stalled at ~5/10
average for 20+ iterations), fresh-start hygiene (cruft from many harness iterations), and
code clarity. The rebuild is **open to rethinking the technical approach**.

## Documents

| Doc | What it covers |
|---|---|
| [00-verdict.md](00-verdict.md) | The one-page conclusion: what failed, what to keep, what to build. Read this first. |
| [01-distillation.md](01-distillation.md) | Inventory of everything worth keeping from v1: contracts, tests, hard-won fixes, reference data, docs. |
| [02-plateau-postmortem.md](02-plateau-postmortem.md) | Root-cause diagnosis of why the quality harness plateaued. Two ceilings: representation and feedback loop. |
| [03-better-approaches.md](03-better-approaches.md) | 2026 technical-approach research: image→3D models, voxel→brick packing, instruction toolchain, the harness redesign. |
| [04-model-spike-result.md](04-model-spike-result.md) | Phase 0 spike result: **Hunyuan3D-2mini chosen** (TripoSG install-blocked on Windows); star voxelizes recognizably (points survive) — kill-criterion risk retired. |

The build-ready plan produced from this investigation lives at
[`documentation/rebuild-plan.md`](../../../documentation/rebuild-plan.md).

## The verdict in one sentence

The v1 pipeline plateaued because it **fabricated depth instead of recovering it** (a
radial-dome height heuristic that put the tall mass in the center, so a star's points
vanished) and **packed bricks without a structural model** (greedy + bolt-on repair), while
the self-improvement harness **committed changes gated only on pytest and never re-rendered
the output** — so broken builds sailed through and the loop oscillated. Every one of those
has a proven 2026 replacement, and the brick-packer / LDraw writer / color service / data
service / subprocess integration and ~95% of the unit tests are worth keeping as-is.
