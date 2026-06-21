# Brickomancer Rebuild Plan

Rebuild Brickomancer with a true-3D front-end, a structurally-aware brick packer, a frozen
instruction toolchain, and a self-improvement harness that scores rendered output. Distills the
proven-valuable v1 backend (packer algorithm, LDraw writer, color/data services, subprocess
integration, ~95% of unit tests) and replaces the two parts that capped quality: the
silhouette+dome image pipeline and the pytest-only harness gate.

Background investigation: [`docs/investigations/rebuild/`](../docs/investigations/rebuild/)
(README → 00-verdict → 01-distillation → 02-plateau-postmortem → 03-better-approaches).
v1 architecture reference: [`docs/master_plan.md`](../docs/master_plan.md).

## Why rebuild (one paragraph)

v1 plateaued at ~5/10 for 20+ harness iterations for two reasons, both verified at source:
(1) the image path **fabricated depth** via a radial-dome height heuristic
([image_pipeline.py:223-230](../src/brickomancer/services/image_pipeline.py#L223-L230)) that
put the tall mass in the center, so a star's edge points vanished; and (2) the harness committed
changes **gated only on pytest, never re-rendering**
([applier.py:172-231](../tests/harness/applier.py#L172-L231)), so broken output (PDF=0 for ~40
iterations) persisted and the loop oscillated. The mechanical backend is good; the rebuild swaps
the front-end representation, makes structure a packer constraint, and closes the feedback loop.

## Architecture decision

```
IMAGE: photo → rembg (keep) → 3D model (geometry-only) → watertight mesh → voxelize @ ~24-32 →
       connectivity-graph packer → ldraw_writer (keep) → LDView previews + LPub3D PDF (frozen meta)
TEXT:  prompt → Claude CLI emits sparse 20³ voxel occupancy → same packer → same backend
       [fallback: BrickGPT MIT weights for its 21 in-domain categories]
LOOP:  judge reads RENDERED output → propose 1-file change → pytest gate → re-render + re-score →
       regression gate → commit only on no-regression
```

The 3D front-end is **swappable behind a `Shaper` interface** that returns the existing
`(X, Y, Z)` bool voxel grid — so the rest of the pipeline (packer, writer, color, render) is
untouched and the existing tests keep protecting it.

### 3D model choice (resolved in Phase 0)

| Candidate | License | VRAM (geo-only) | Windows | Pick rationale |
|---|---|---|---|---|
| **Hunyuan3D-2mini** | Community (US-OK, <1M MAU) | ~5 GB | Turnkey WinPortable | **Lowest risk — default** |
| **TripoSG** | MIT | ~8 GB | Linux-first (effort) | Cleanest license; watertight by construction |
| TRELLIS v1 | MIT | 6-16 GB | 1-click installer | Easy fallback; mesh needs repair pass |

Phase 0 spikes the top two on the actual GPU and picks one. Default to Hunyuan3D-2mini unless the
spike shows TripoSG installs cleanly and renders better.

## Scope boundaries

- **Keep (do not rewrite):** `brick_packer.py` algorithm, `ldraw_writer.py`, `color_service.py`,
  `data_service.py`, `subprocess_utils.py`, `models/` contracts, `data/` reference files,
  `scripts/download_data.py`, and the unit tests for all of the above.
- **Replace:** `image_pipeline.py` (silhouette+dome → 3D model voxelizer), `text_pipeline.py`
  (Llama-1B primitive → sparse-voxel emitter), the harness `applier`/`judge` gate.
- **Out of scope for this rebuild:** multi-part/articulated builds, printed-face decoration,
  cloud 3D APIs, a job queue. (V1 stays synchronous + local + single-user.)

---

## Phase 0 — De-risk and decide (do this first)

### Step 0.1: 3D-model runnability spike
- **Problem:** Stand up Hunyuan3D-2mini (WinPortable) and TripoSG geometry-only on the actual
  Windows + CUDA GPU. For each: install, run on 3 fixture images (star, dog/animal, cake), export
  mesh, voxelize via `trimesh.voxelized(pitch).fill()` at ~24-32, and eyeball whether the voxel
  grid is recognizably the object (star has points, dog has legs). Record VRAM, wall-clock, and a
  pass/fail on "recognizable voxelization". Pick ONE model for the rebuild.
- **Type:** operator (spike — produces a decision + notes, not production code)
- **Issue:** #47
- **Produces:** `docs/investigations/rebuild/04-model-spike-result.md` (chosen model, VRAM,
  latency, sample voxel renders, install steps that worked)
- **Done when:** one model is chosen with evidence it voxelizes the star recognizably (points
  visible), and the install procedure is reproducible from the notes.
- **Depends on:** none
- **Status:** DONE (2026-06-17)

<!-- autofix-applied: 2026-06-16 -->
### Step 0.2-prep: Author the frozen LPub3D meta-header fixture
- **Problem:** Author a **minimal known-good LPub3D meta header** (BOM + step numbering, fixed
  values) as a fixture `.ldr`, plus a trivial known-good body `.ldr` (a few bricks) for the
  toolchain smoke. This is the artifact Step 0.2 validates and that Step 7/9 pin.
  **AMENDED 2026-06-17 (Step 0.2 finding):** the header is **BOM-only, NO COVER_PAGE** —
  `0 !LPUB INSERT COVER_PAGE` crashes LPub3D 2.4.9 (see 04-model-spike-result.md § Step 0.2).
- **Type:** code
- **Issue:** #48
- **Flags:** --reviewers code
- **Produces:** `tests/fixtures/lpub3d_meta_header.ldr` (frozen header), `tests/fixtures/toolchain_smoke.ldr`
- **Done when:** both fixtures parse as valid LDraw (no syntax error when opened by LDView); the
  meta header contains exactly the BOM + step-numbering commands and nothing else (NO COVER_PAGE,
  which crashes the renderer — render-verified in Step 0.2).
- **Depends on:** none
- **Status:** DONE (2026-06-17) — amended: BOM-only header (COVER_PAGE crashes LPub3D 2.4.9).

### Step 0.2: Toolchain + license confirmation
- **Problem:** Confirm LDView 4.7 + LPub3D 2.4.9 headless still produce a valid PNG + multi-page
  PDF from the Step 0.2-prep fixtures on this machine. Confirm the Phase-0-chosen 3D model's
  license is acceptable for a personal local tool.
- **Type:** operator
- **Issue:** #49
- **Produces:** a short license + toolchain note appended to `docs/investigations/rebuild/04-model-spike-result.md`
- **Done when:** `toolchain_smoke.ldr` → PNG via LDView and → multi-page PDF via LPub3D both
  succeed; the frozen meta header renders per-step parts pages + a BOM page; chosen-model license
  confirmed OK. **AMENDED 2026-06-17:** no cover page — COVER_PAGE crashes LPub3D 2.4.9
  (render-verified); frozen header is BOM-only.
- **Depends on:** Step 0.2-prep
- **Status:** DONE (2026-06-17)

---

## Phase 1 — Salvage and scaffold the clean base

### Step 1: Fresh scaffold + salvage proven modules
- **Problem:** Create the clean project skeleton (FastAPI + React, same as v1 §master_plan) and
  **copy in verbatim** the proven v1 modules and their tests: `models/brick.py`,
  `models/schemas.py`, `services/color_service.py`, `services/data_service.py`,
  `services/ldraw_writer.py`, `utils/subprocess_utils.py`, `utils/temp_dir.py`,
  `scripts/download_data.py`, `data/`, and `tests/test_color_service.py`,
  `tests/test_data_service.py`, `tests/test_instruction_service.py`,
  `tests/test_main.py`. Do NOT copy `image_pipeline.py`, `text_pipeline.py`, or the harness.
- **Type:** code
- **Issue:** #50
- **Flags:** --reviewers code
- **Produces:** scaffolded repo, salvaged modules, salvaged tests, `pyproject.toml`
- **Done when:** `uv run pytest -q --ignore=tests/integration` passes on the salvaged tests;
  `uv run mypy src` and `uv run ruff check .` clean; `GET /api/status` returns 200.
- **Depends on:** none
- **Status:** DONE (2026-06-17) — in-place clean; image/text pipelines + old harness removed,
  generate routes 503-stubbed (signatures preserved), harness refs archived to
  docs/rebuild_reference/. Tests 348→157 (intentional removal of 195 throwaway tests + 9 new).

### Step 2: Define the `Shaper` interface (the swap seam)
- **Problem:** Introduce `services/shaper.py` defining `Shaper.to_voxels(...) -> np.ndarray[bool,
  (X,Y,Z)]` — the single seam the front-ends implement. This is the integration point everything
  downstream depends on. **Voxel-grid contract (spell out inline so a fresh model can implement
  the Shaper without reverse-engineering):**
  - `np.ndarray`, `dtype=bool`, shape `(X, Y, Z)`.
  - `Y` is the vertical axis: `Y=0` is the ground layer, `Y` increases upward. `(0,0,0)` is the
    origin corner.
  - `True` = a brick occupies that voxel; `False` = empty.
  - Typical extent `X, Y, Z` each in `[2, 32]` for V1 shapes.
  - This is the **same convention v1 used** (verified: `brick_packer.py` docstring "shape (X,Y,Z)
    where True = occupied"; `BrickPlacement` fields `part_id, color_id, x, y, z, width, length`).
    The rebuild rewires `routers/generate.py:57` (from-image) and `:87` (from-text) to call a
    `Shaper` instead of `image_pipeline.run` / `text_pipeline.run` — those are the only two
    production call sites.
- **Type:** code
- **Issue:** #51
- **Flags:** --reviewers code
- **Produces:** `src/brickomancer/services/shaper.py`, `tests/test_shaper_contract.py`
- **Done when:** the interface is defined, a trivial stub implementation returns a valid grid, and
  a contract test asserts the grid shape/dtype/Y-up convention.
- **Depends on:** Step 1
- **Status:** DONE (2026-06-17) — `Shaper` ABC + no-arg `to_voxels()` (constructor-injected
  input/config, geometry-only seam), `validate_grid` enforcing footprint (X,Z ∈ [2,32]) vs height
  (Y ∈ [2,64]), asymmetric grounded `StubShaper`, grid-dim constants single-sourced in
  `models/brick.py` (packer now imports `MIN_GRID_DIM`). 27 contract tests incl. pack-integration.

---

## Phase 2 — Structurally-aware packer (shared by both front-ends, build before front-ends)

### Step 3: Connectivity-graph packer core
- **Problem:** Build `services/brick_packer.py` as a connectivity-graph packer (subset of Luo 2015,
  see 03-better-approaches §2): **Phase A** connectivity-aware greedy fill with masonry-by-parity
  (salvage v1's masonry pre-pass and brick-merge logic), **Phase B** graph analysis (connected
  components + articulation points + unsupported bricks via networkx/DFS). Keep v1's
  `BrickPlacement` output contract and surface-tile pass. **Grep all consumers of the placement
  list before changing its shape.**
- **Type:** code
- **Issue:** #52
- **Flags:** --reviewers code
- **Produces:** `src/brickomancer/services/brick_packer.py`, adapted `tests/test_brick_packer.py`
- **Done when:** a 5×5×5 cube and a star voxel grid both pack to a placement list where the graph
  has exactly one connected component and zero unsupported bricks; salvaged packer tests pass;
  the masonry-offset and connectivity-repair invariant tests pass.
- **Depends on:** Step 1
- **Status:** DONE (2026-06-17) — Phase B graph analysis (build_connectivity_graph,
  connected_component_count, unsupported_bricks, articulation_points) + `_merge_components`
  (spanning-tree, cap-above bonding). cube/star → 1 component + 0 unsupported; masonry seams
  preserved (caps sit above tested layers). KNOWN TRADEOFF deferred to Step 4: cap-above extends
  height (hub columns force ≥1 cap layer); Step 4 bonds in-volume to remove the height cost.

### Step 4: Targeted split/re-merge + physics-aware rollback + in-volume bonding
- **Problem:** Add **Phase C** (targeted split/re-merge around articulation points, bounded ≤5
  iterations widening on failure) and a **physics-aware rollback** (borrowed from BrickGPT:
  reject a placement that would create an unsupported/cut-vertex brick, backtrack). Optionally
  **Phase D** per-layer CP-SAT (OR-Tools) only when a layer stays disconnected. **Also (carried
  from Step 3 review): replace the cap-above component-merge with IN-VOLUME bonding so connectivity
  no longer extends build height** — bond fragment towers into the spine at shared in-grid layers
  (articulation-driven), preserving the masonry-offset seams. This removes the ~20% height
  overshoot the cap-above merge introduces on fragmented/hub-heavy shapes.
- **Type:** code
- **Issue:** #53
- **Flags:** --reviewers code
- **Produces:** updated `brick_packer.py`, new stability tests in `tests/test_brick_packer.py`
- **Done when:** a known-pathological grid (star with thin arm tips) packs with zero freestanding
  1×1 stacks and zero articulation points at arm tips; a regression test asserts no cut vertices;
  **the packed output adds no build-height layers beyond the input grid's top (in-volume bonding —
  no above-grid connectivity caps), while keeping 1 connected component + 0 unsupported.**
- **Status:** DONE (2026-06-18). In-volume bonding (`_bond_components_in_volume`) replaces the
  cap-above merge: cube, plus-star, and all masonry grids pack to ZERO added height, 1 component,
  0 unsupported, masonry ABAB seams preserved. New bond-only `(2,1)` part (LDraw 3004 rotated 90°
  about Y, matrix `0 0 1 0 1 0 -1 0 0`) — **render-verified** (renders ⊥ to the (1,2);
  `scripts/step4_render_uat.py`). Spanning-tree bond solver with strategy ranking (z-clean →
  z-extend → x-clean → z/x-decompose), each guarded (strict-merge, no float, no added height;
  x-bonds seam-gated). The plus-star degree-4 hub is solved via a z-extend that grows an existing
  `(1,N)` span to absorb a fragment without consuming a layer. Phase C (`_eliminate_arm_tip_articulations`)
  adds redundant z-bonds (cycles) to reduce cut vertices where geometry allows. Tile pass made
  1-for-1 (an adversarial review found the old strip-split severed top-layer bonds → multi-component).
  240 tests, 0 type errors, 0 lint. **Known limitation:** minimum-depth slabs (Z=2) and Y=2,Z∈{5,9}
  keep +1/+2 height via the cap fallback (still 1 component + 0 unsupported); all thick grids
  (Y≥3 ∧ Z≥3) are zero-height. CP-SAT/Phase D not needed (skipped per spec). See
  [`docs/investigations/rebuild/06-step4-design.md`](../docs/investigations/rebuild/06-step4-design.md).
- **Depends on:** Step 3

---

## Phase 3 — True-3D front-ends behind the seam

### Step 5: Image `Shaper` — 3D model voxelizer
- **Problem:** Implement `ImageShaper` using the Phase-0-chosen 3D model: `rembg` background
  removal (salvage) → 3D model geometry → `trimesh.voxelized(pitch, method='subdivide').fill()` →
  `(X,Y,Z)` grid. Replaces the silhouette+dome heuristic entirely. Graceful 503 if the model
  weights/GPU are unavailable. **Integration test must run through the production
  `/api/generate/from-image` entry point**, not the shaper in isolation.
- **Type:** code
- **Issue:** #54
- **Flags:** --reviewers code
- **Produces:** `src/brickomancer/services/image_shaper.py`, `tests/test_image_shaper.py`,
  integration test through the router
- **Done when:** `from-image` on the star fixture returns a voxel grid whose top-down silhouette
  has ≥4 distinct protrusions (star points survive); model-unavailable raises a clean 503.
- **Depends on:** Steps 0.1, 2, 3
- **Status:** DONE — automated scope (2026-06-19). `ImageShaper` (`services/image_shaper.py`)
  implements the seam: rembg → Hunyuan3D-2mini → `trimesh.voxelized(method="subdivide").fill()` →
  crop/clamp/pad into the contract → `validate_grid`. Wired through `/api/generate/from-image`;
  `ModelUnavailableError` (no torch / no CUDA / no `hy3dgen` / weights-load fail / degenerate mesh)
  → clean 503. `height_studs` is now the resolution knob (`ImageShaper(max_dim=...)`, clamped to
  `[2, 32]`) — the spike's `max_dim=28` packs ~66 s/tier (×3 tiers = unusable); `max_dim≈10` packs
  in <2 s. Integration test runs the model **mocked** through the router (`_generate_mesh` patched)
  plus a model-unavailable 503 test; 253 tests green, 0 type, 0 lint. Packer + `Shaper.to_voxels`
  signature untouched. **DEFERRED to an operator Test:** the literal done-when above (live
  star-survival, top-down ≥4 protrusions with the real model) — Hunyuan3D-2mini is not yet in the
  project venv (only the throwaway `C:\Tools\spike3d`); needs the 7.64 GB weight download first.

### Step 6: Text `Shaper` — sparse-voxel emitter
- **Problem:** Implement `TextShaper`: Claude CLI emits a **sparse 20³ voxel occupancy** (list of
  occupied coords, strict JSON schema, not a dense grid) → fill the `(X,Y,Z)` grid. Reuse the
  `claude -p` subprocess pattern from `subprocess_utils` (no `--image`, `CLAUDE_CODE_OAUTH_TOKEN`).
  Validate/clamp coords to grid bounds. **Fallback:** wire BrickGPT MIT weights for its 21
  in-domain categories if a category match is detected.
- **Type:** code
- **Issue:** #55
- **Flags:** --reviewers code
- **Produces:** `src/brickomancer/services/text_shaper.py`, `tests/test_text_shaper.py`
- **Done when:** `from-text "five-pointed star"` produces a grid that packs to a star-recognizable
  build; malformed model output is rejected/retried (mocked in unit tests); out-of-bounds coords
  are clamped.
- **Depends on:** Steps 2, 3
- **Status:** DONE — automated scope (2026-06-21). `TextShaper` (`services/text_shaper.py`) behind
  the seam: `claude -p` (`subprocess_utils.run_claude_text`, OAUTH, no GPU / no llama-server) emits a
  sparse 20³ voxel occupancy (strict JSON `{"voxels":[[x,y,z],…]}`) → parse + clamp OOB coords →
  fill → crop-to-bbox / edge-pad sub-2 → `validate_grid`. Malformed/empty output retried (3×, like
  `piece_detector`); a subprocess failure (no token / non-zero exit) is not retried; `TextShaperError`
  → clean 503. Wired through `/api/generate/from-text` (build color **defaulted** — text has no source
  image). Integration test runs the subprocess **mocked** through the router + unusable-output and
  CLI-unavailable 503 tests; 267 tests green, 0 type, 0 lint. Packer + `Shaper.to_voxels` untouched.
  The v1 Llama text path is fully retired. **Live Operator Test PASSED (2026-06-21, no GPU):**
  `from-text "five-pointed star"` → a recognizable 5-pointed star (unmistakable in the face-on
  projection; Claude stands it upright/thin, so top-down is its footprint), ~165 s/emit. The live
  test caught two real defects the mocked tests could not: (1) `subprocess.TimeoutExpired` is not a
  `RuntimeError`, so a timeout escaped `to_voxels` as an uncaught 500 instead of a 503; (2) the 60 s
  budget (copied from piece detection) was too tight for the larger voxel-JSON generation. Both
  fixed: `run_claude_text` timeout → 180 s, `to_voxels` now catches `TimeoutExpired` → 503, and the
  prompt asks for ~80-400 voxels.

### Step 7: Suggestion service + preview/instruction wiring
- **Problem:** Rebuild `suggestion_service` (3 tiers via the OR-pool downsample from
  shape-quality-plan Step 4, not stride-2) + color assignment (salvage `color_service`) + LDView
  previews + parts list. Wire `instruction_service` to LPub3D using the **frozen meta header
  fixture** from Step 0.2 — the meta header is a constant, never generated dynamically.
- **Type:** code
- **Issue:** #56
- **Flags:** --reviewers code
- **Produces:** `src/brickomancer/services/suggestion_service.py`, `instruction_service.py`,
  adapted tests
- **Done when:** `from-image` returns exactly 3 suggestions with distinct `parts_count`, each with
  a non-empty preview PNG and parts list; `/instructions` produces a multi-page PDF with per-step
  parts pages + a BOM page from the frozen header. **AMENDED 2026-06-17:** no cover page — the
  frozen header is BOM-only (COVER_PAGE crashes LPub3D 2.4.9; render-verified in Step 0.2).
- **Depends on:** Steps 5, 6
- **Status:** DONE — render-verified (2026-06-21). `suggestion_service` (already 3-tier with the
  OR-pool downsample) returns 3 tiers with distinct `parts_count`. **Real bug fixed:** `ldraw_writer`
  was still emitting `0 !LPUB INSERT COVER_PAGE` (Phase 0.2 froze the fixture + its test but never the
  production writer) — so every instruction PDF would have crashed LPub3D 2.4.9. The writer now emits
  the FROZEN BOM-only header (`_BOM_META` constant; no COVER_PAGE, no FADE_STEPS; BOM after the final
  `0 STEP`). New `tests/test_ldraw_writer.py` guards the producer output (constant present, no
  COVER_PAGE, BOM-only metas, BOM-after-last-step); 3 stale `TestWriteLdr` step-count tests updated
  (dropped the +1 cover-page step). **In-window REAL render (`scripts/step7_render_uat.py`):** LDView
  → 25 KB PNG; LPub3D → 267 KB ~3-page PDF with BOM, no crash. 273 tests, 0 type, 0 lint; packer +
  `Shaper.to_voxels` untouched. This is the exact pytest-vs-render blind spot — the mocked gate passed
  the COVER_PAGE writer; only the real render caught it.

### Step 8: Frontend + end-to-end smoke gate
- **Problem:** Port the v1 React 4-step wizard (it's fine) and wire it to the rebuilt routes. Add
  `tests/integration/test_smoke.py` exercising the full image and text paths against a live server
  with real services.
- **Type:** code
- **Issue:** #57
- **Flags:** --reviewers code
- **Produces:** `frontend/src/`, `tests/integration/test_smoke.py`
- **Done when:** `npm run build` clean; integration smoke passes with real services; image path
  completes in a reasonable wall-clock (record it).
- **Depends on:** Step 7
- **Status:** DONE — smoke-verified (2026-06-21). The v1 React 4-step wizard already calls only the
  current routes (`/from-image`, `/from-text`, `/instructions`) with matching request/response
  shapes; `npm run build` clean (tsc + vite, 36 modules, 621 ms). `tests/integration/test_smoke.py`
  rebuilt to exercise BOTH paths + instructions through the REAL services (TestClient, nothing
  mocked; retired the v1 TripoSR/llama-server guards), gated on `BRICKOMANCER_INTEGRATION=1` +
  per-path availability. **Live run PASSED:** from-text 73 s, from-image (real Hunyuan3D) **1019 s
  (~17 min)**, instructions PDF (real LPub3D, frozen BOM-only header) 9 s. 273 clean-gate tests, 0
  type, 0 lint; packer + `Shaper.to_voxels` untouched. **FINDING — image path ~17 min/request:**
  `ImageShaper._load_pipeline` runs `from_pretrained` (7.64 GB) on EVERY request (no cached pipeline)
  + rembg first-run + 3-tier pack + 3 LDView renders. Caching the loaded pipeline as a module
  singleton is the obvious fix (drops repeat requests toward inference-only ~100 s) — deferred as an
  ImageShaper perf follow-up (out of Step 8 scope; Step 8 = frontend + smoke).

---

## Phase 4 — Closed-loop quality harness (the loop redesign)

### Step 9: Render-scoring harness with regression gate
- **Problem:** Rebuild the harness loop so the commit gate is **rendered-output score
  regression**, not pytest alone (see 02-plateau-postmortem + 03 §4). After the applier writes a
  1-file change and pytest passes, **re-run the pipeline, re-render, and re-score** with the
  LLM-judge on the rendered PNG/PDF; commit ONLY if no dimension regresses below its committed
  baseline and avg does not drop, else revert. Hold a **fixed eval set** (star, dog, chair, heart).
  Add the frozen LPub3D meta header to `constraints_to_preserve` so the judge cannot edit it.
<!-- autofix-applied: 2026-06-16 -->
- **Type:** code
- **Issue:** #58
- **Flags:** --reviewers code
  <!-- Downgraded from --reviewers full per plan-review §24: the harness is a backend/CLI loop
       with no running UI for a runtime reviewer; gate behavior is verified by the Done-when tests. -->
- **Produces:** rebuilt `tests/harness/` (judge, applier with render-score gate, eval set),
  harness tests
- **Done when:** a **regression-gate test** exists that (a) feeds the applier a deliberately-bad
  change which blanks the rendered PDF and asserts it is **rejected/reverted** by the score gate
  (this is the explicit "real regression caught" exercise required by §15), (b) feeds a genuine
  improvement and asserts it is committed, and (c) asserts the frozen meta-header constant is in
  the judge's forbidden/`constraints_to_preserve` set. All three pass under `uv run pytest -q`.
- **Depends on:** Step 8

### Step 10: Calibration run
- **Problem:** Run the rebuilt harness for **5 iterations** on the eval set (extend to up to 20 if
  5 iterations leave the trend ambiguous) and confirm `avg_raw` trends **up** (the v1 failure mode
  was flat 3.5-5.1). Record the trajectory. This is the §15 end-to-end observation step: the full
  pipeline + harness runs unattended and is observed, not just unit-tested.
- **Type:** wait
  <!-- "wait" = long-running observation step; /build-phase halts intentionally so wall-clock
       waiting doesn't consume context (per build-phase halt contract #4). Resume in a fresh
       session via --resume after the run completes. This is operator-observed, not a code gate. -->
- **Issue:** #59
- **Produces:** `tests/harness/scores.jsonl` with the run's rows, a short results note in
  `docs/investigations/rebuild/05-calibration-result.md`
- **Done when (observation-based, not pass/fail):** the run completes and the results note records,
  with evidence from `scores.jsonl`: (a) the `avg_raw` trajectory across iterations, (b) whether
  any dimension hit 0 and for how many iterations, (c) whether any meta-command oscillation
  occurred. A flat or declining trend is itself a valid, ship-worthy finding (it means the gate or
  judge needs tuning) — the step is "see what actually happens", not "force avg_raw up".
- **Depends on:** Step 9

---

## Cross-cutting requirements (apply to every code step)

- **Grep all downstream consumers when changing a key/id/shape** (the `BrickPlacement` list, the
  voxel-grid contract, `suggestion_id`). Attach a per-call-site verdict to the PR. (workspace
  code-quality rule)
- **One source of truth for data-shape constants** (`BRICK_TYPES`, grid dims, LDU constants) —
  import, never re-declare. Regression-test with `is`, not just `==`.
- **New component → integration test through the production caller** (the silent-wiring rule). The
  shapers and packer must be reached end-to-end from the router, not just unit-tested.
- **Frozen-config-as-invariant** (workspace security rule "pair unsafe configs with startup
  checks"): the LPub3D meta header is a pinned constant + a test that fails if it drifts.
- **Packer tests use a stub `Shaper`.** Packer unit tests (Steps 3-4) build voxel grids directly
  (cube, cross, star) to isolate packer logic — they do NOT invoke a real 3D model. Only the Step 8
  integration smoke uses real `Shaper` implementations end-to-end.
- **Toolchain coverage.** Python: `uv sync` (install), `uv run uvicorn` (dev), `uv run pytest -q`
  (test), `uv run ruff check .` (lint), `uv run mypy src` (typecheck). Frontend: Node 20+ / npm 10+,
  `npm install` (install), `npm run dev` (dev), `npm run build` (build) — bootstrapped in Step 8.
  Inherited from `CLAUDE.md`; harness always runs pytest with `--ignore=tests/integration`.

## What this plan deliberately does NOT do

- Does not chase `reference_fidelity` against an artist's figurine reference (inherently capped —
  use a silhouette-style reference or accept it). See 02-plateau-postmortem.
- Does not adopt a monolithic 3D ILP packer (NP-hard in the connectivity constraint).
- Does not use the bare Llama-1B for unconstrained shape emission (the v1 text failure).
- Does not depend on cloud 3D APIs (local-first requirement).

## Pipeline to execute this plan

`/plan-review documentation/rebuild-plan.md` → `/plan-wrap` → `/repo-sync` → `/build-phase
--plan documentation/rebuild-plan.md`. Issue numbers are filled in by `/repo-sync`.
