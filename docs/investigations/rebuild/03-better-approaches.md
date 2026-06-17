# Better Technical Approaches (2026 Research)

Current (2025-2026) options for each pipeline stage, given a Windows 11 + consumer CUDA GPU, a
Claude subscription (zero-marginal-cost vision/reasoning via the `claude` CLI), and a local
llama.cpp server. Every model/tool is tagged **PROVEN** (available, runs locally today) or
**RISKY** (research-y / install or license caveat). License notes assume a personal,
non-revenue tool.

## 1. Object → 3D shape (the core failure)

Voxelization is forgiving (you discard texture and downsample to ~24-32), so the bar is **true
volumetric occupancy + a clean/watertight mesh**, not a clean PBR asset. Run every candidate in
**geometry-only** mode to cut VRAM. **Prefer SDF/TSDF generators** (watertight by construction)
over Flexicubes/O-Voxel ones (can emit open shells that voxelize hollow).

| Model | License | VRAM (geo-only) | Watertight | Windows | Tag |
|---|---|---|---|---|---|
| **TripoSG** (VAST/Tripo) | **MIT** | ~8 GB | **Yes (SDF→UDF→marching cubes)** | Effort (Linux-first) | **PROVEN — top pick** |
| **Hunyuan3D-2mini** (Tencent) | Community (US-OK; excl. EU/UK/KR; <1M MAU) | **~5 GB** | Yes | **Yes (WinPortable, 2GP)** | **PROVEN — lowest risk** |
| **Hunyuan3D-2.1** | Community (same) | ~10 GB | Yes | Yes | PROVEN (better quality) |
| **Hi3DGen / Stable3DGen** (ByteDance) | **MIT** | ~16 GB | Yes | Possible | PROVEN (best detail) |
| **SPAR3D** (Stability) | Stability Community (<$1M rev) | 6–10.5 GB | "Complete structure"; point-cloud back-completion; editable intermediate | Experimental | PROVEN (targets the "missing back" failure directly) |
| **Direct3D-S2** (DreamTech) | **MIT** | 10 GB@512 / 24 GB@1024 | Trained watertight; `remove_interior` knob | **Risky (torchsparse build → use WSL2)** | RISKY (best topology) |
| **Step1X-3D** (StepFun) | **Apache-2.0** (cleanest) | ~27 GB | **Yes (TSDF)** | Linux | RISKY (high VRAM) |
| **TRELLIS v1** (Microsoft) | **MIT** | 6–16 GB | Not guaranteed (Flexicubes) | **Yes (1-click installer)** | PROVEN (easy on-ramp; needs repair pass) |
| **TripoSR** (v1 baseline) | MIT | ~6 GB | **No — holes, non-manifold, thin-part breakage** | Yes | **OBSOLETE — retire** |
| TRELLIS.2 (4B) | MIT | 24 GB | **No (open-surface by design)** | Linux only | Wrong tool for solid voxels |
| InstantMesh / CraftsMan3D | Apache / ambiguous | ~24 GB / ~8-12 GB | Partial / unevaluated | — / WSL2 | Frozen/dormant — fallback only |
| Meshy / Rodin / Luma / Kaedim | — | — | — | **Cloud-only** | Disqualified (not local) |

**Recommendation:** **TripoSG** (cleanest license, watertight by construction) is the strongest
fit; **Hunyuan3D-2mini** is the lowest-risk first pick (~5 GB, turnkey Windows build). Pick one
via a Phase-0 spike on the actual GPU. **TripoSR (the v1 baseline) is obsolete** — its
hole-prone output is the exact thing that fights a voxelizer; the field (Tripo included) moved on.

### LLM-as-designer — useful component, not the primary generator
No published system has a VLM emit a clean voxel grid *from a photo*. Frontier VLM spatial
reasoning peaks ~57% on comprehensive benchmarks (OmniSpatial) and is *worst* at geometric
reasoning/occupancy/counting — the exact primitives a voxel grid needs. Minecraft-schematic work
(T2BM, APT) only works with a deterministic validity/repair layer downstream. **Keep geometric
reconstruction as the spine; use the VLM only as an advisory/judge layer** (which the harness
already does well) or an optional soft "shape hint" prior the geometry can override.

## 2. Voxel → bricks (packing / legolization)

v1's greedy-largest-first + bolt-on-repair is the **canonical documented failure mode**: greedy
optimizes each brick locally, but **stability is a global graph property** — a repair pass
operating on raw geometry literally cannot *see* that a 1×1 stack is a cut vertex.

**Reference algorithm — Legolization (Luo et al., SIGGRAPH Asia 2015):** build a connectivity
graph (nodes = bricks, edges = stud connections), require a single connected component, run a
stability analysis to find the **weakest region**, then **split/re-merge bricks in that region's
neighborhood**, iterating and widening the neighborhood on repeated failure.

**Recommended packer — a deterministic, CPU, few-seconds subset:**
- **Phase A — connectivity-aware greedy fill** (not largest-first): vectorized numpy merge, but
  **alternate merge orientation/anchor by layer parity** so seams stagger *during* placement
  (English-bond masonry — enforced, not repaired). (v1 already has the masonry pre-pass — keep it.)
- **Phase B — connectivity-graph analysis** (the rung v1 lacks): one DFS for connected
  components + **articulation points** (cut vertices = the freestanding-1×1 pathology) +
  unsupported bricks. O(V+E), milliseconds, `networkx` or ~40 lines.
- **Phase C — targeted split/re-merge** around weak nodes only; bounded iterations (≤5), widening
  on failure.
- **Phase D (optional)** — scoped **per-layer CP-SAT** (OR-Tools) only if a layer stays
  disconnected. Per-layer polyomino tiling is tractable in sub-second; a **monolithic 3D ILP with
  global connectivity is NP-hard in the part that matters — do not do it.**

Objective: **structure first** (single component, no floaters, minimize articulation points,
masonry offset) then **fidelity** (shape coverage, larger bricks on visible faces, Lab color match).

Also worth borrowing: **BrickGPT's physics-aware rollback** — prune unstable placements *during*
packing rather than repairing after. Most transferable idea from the LEGO-generative literature;
directly targets `build_stability`.

Existing libraries (brickalize GPL-3.0, Londogard img2lego) have no permissive, structurally-
connected packer — mine them for the numpy merge trick and LDraw color handling, don't depend.

## 3. Instruction generation toolchain — keep LDView + LPub3D

Both shipped fresh releases in the last 12 months; nothing else is a mature, free,
Windows-headless instruction-PDF generator. The oscillation was a **meta-command authoring
problem, not a tool problem.**

- **LDView 4.7** (2026-02, dual GPLv2/MIT) — headless PNG snapshots. Already called correctly. **Keep.**
- **LPub3D 2.4.9** (2025-10, GPLv3) — the reference instruction-PDF tool. Invocation
  `LPub3D -x -pe pdf <ldr>` is the battle-tested path. **Keep — but its stateful `0 !LPUB` meta
  layer is the fragile part.**
- Rejected alternatives: Bricklink Studio (instruction export is **GUI-only**), Blender+LDraw
  (rebuilds LPub3D's engine), custom three.js (needs headless browser + no PDF pagination).
  **LeoCAD CLI** is a good *fallback* (per-step PNGs via `--from/--to`, `--fade-steps`,
  `--highlight`) but produces no paginated book — assemble PNGs into a PDF via reportlab if LPub3D regresses.

**The real fix — correct division of labor:**
1. **Your generator owns step *content*** (which bricks in which `0 STEP`). Keep `ldraw_writer`'s
   Y-layer-first sequencing authoritative.
2. **LPub3D owns only layout/pagination** (BOM, cover page, callouts).
3. **Freeze a minimal known-good meta header** as a constant the harness is **forbidden to edit**
   (add to the judge's `constraints_to_preserve`). This removes the oscillation surface.

## 4. The self-improvement loop (design principle)

v1 committed gated only on pytest, never re-rendering — so the judge optimized a proxy that
didn't measure the artifact. The correct shape:

1. **Score the rendered artifact, not the code.** The judge looks at the actual rendered PNG/PDF.
   Pytest passing is a *gate*, not the *objective*.
2. **Hold a fixed eval set** of reference inputs (star, dog, chair, heart) with rendered outputs.
3. **Regression gate on the score.** A change merges only if the aggregate rendered-output score
   does not regress on any dimension below its committed baseline. This is what stops oscillation.
4. **Pin non-improvable surfaces** (the LPub3D meta header) in `constraints_to_preserve`.
5. **Revert on regression, commit only on no-regression/improvement.** Keep the existing structured
   change-brief + pytest gate; **add the rendered-score regression gate as the real merge criterion.**

The loop already has judge → apply → pytest → commit/revert. The missing rung is
**re-render + re-score + regression-gate-on-score** between pytest and commit.

## 5. Text path

LLMs *can* emit a small, **sparse** brick/voxel list reliably for simple iconic shapes — never a
dense grid (32³ = 32,768 cells is infeasible/unreliable as text output; every working system uses
a sparse coordinate list or a learned VQ-VAE codec). Two options:

- **Hybrid (recommended):** Claude CLI emits a coarse 20³ voxel occupancy as a **sparse coordinate
  list** (zero marginal cost, no GPU) → shared packer. Separates the hard spatial step from
  mechanical packing and sidesteps brick-only limits (you keep tiles/slopes).
- **BrickGPT** (CMU, ICCV 2025, **MIT** code+weights) — fine-tuned **Llama-3.2-1B** (the exact
  model you already run), **outputs `.ldr` natively**, physics-aware rollback → 98.8% stable.
  **PROVEN fallback** for its **21 ShapeNet categories** (chairs, tables, vehicles…). Limits: 20³
  grid, 8 brick types, no tiles/slopes, official path is GPU/transformers + Gurobi for the
  accurate stability check. Use it directly for in-domain prompts; use the Claude-hybrid for
  everything else.
- **Do NOT** use the bare local Llama-1B for unconstrained shape emission — that was the v1 text failure.

## Source pointers (key claims)

- TripoSG (MIT, SDF→watertight): github.com/VAST-AI-Research/TripoSG · arxiv 2502.06608
- Hunyuan3D-2.1 / 2mini: github.com/Tencent-Hunyuan/Hunyuan3D-2.1 · WinPortable + 2GP forks
- SPAR3D (back-completion): stability.ai/news-updates/stable-point-aware-3d · arxiv 2501.04689
- Direct3D-S2 (MIT, native SDF): github.com/DreamTechAI/Direct3D-S2 · arxiv 2505.17412
- Legolization: cs.columbia.edu/~yonghao/siga15/luo-Legolization.pdf
- BrickGPT (MIT, Llama-1B, LDraw-native): arxiv 2505.05469 · github.com/AvaLovelace1/BrickGPT
- VLM spatial-reasoning ceiling: OmniSpatial arxiv 2506.03135 · qizekun.github.io/omnispatial
- LDView 4.7 / LPub3D 2.4.9 release pages; LeoCAD CLI: leocad.org/docs/cli.html
