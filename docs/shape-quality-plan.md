# Shape Quality Improvement Plan

**Goal:** Raise `shape_fidelity` and `build_stability` raw scores from their current 2/10 and 1/10 baselines to ≥ 6/10 each by fixing the actual root causes identified in INV-7.

**Background:** Three tests in `test_image_pipeline.py` have been blocking developer-agent axis-change proposals for two consecutive harness runs. Investigation (INV-7) shows the tests are correct — the axis changes were wrong. The real problems are (a) rembg producing near-empty alpha masks server-side, (b) compact-tier downsampling losing 75% of the silhouette, and (c) no integration test catching rembg sparsity. See `docs/investigations/INV-7-test-constraint-and-shape-quality.md`.

---

<!-- autofix-applied: 2026-06-14 -->
### Step 1: Add rembg diagnostic logging and a minimum-fill guard

**Problem:** The server-side rembg call produces ~3 True voxels per layer (vs 117 locally) with no logging to confirm or diagnose the discrepancy. The pipeline silently produces a 1×1 column with no warning.

**Type:** code

**Issue:** #33

**Status:** DONE (2026-06-13)

**Flags:** (none)

**Files:** `src/brickomancer/services/image_pipeline.py`, `tests/test_image_pipeline.py`

**Produces:** Modified `src/brickomancer/services/image_pipeline.py`

**Changes:**
- In `_extrude_silhouette`, after computing `mask_zx`, log (via `logging.getLogger`) the fill percentage: `f"silhouette fill: {mask_zx.mean()*100:.1f}% ({mask_zx.sum()}/{mask_zx.size} studs)"`.
- Add a minimum-fill guard: if `mask_zx.sum() < 4`, fall back to a solid rectangle (`mask_zx[:] = True`) and log a warning — this prevents the downstream "1×1 column" failure mode when rembg returns a near-empty result.
- In `run()`, log the alpha channel fill % from the rembg output before passing to `_extrude_silhouette`.

**Done-when:** After a `/api/generate/from-image` call, the server log shows a silhouette-fill line; if rembg returns < 4 filled studs, the log shows "sparse rembg output — using solid fill fallback" and the build is a rectangle (not a 1-stud column).

**Integration test:** `tests/test_image_pipeline.py` — add `test_extrude_silhouette_sparse_falls_back_to_solid()` that calls `_extrude_silhouette` with a near-empty RGBA image (alpha=0 everywhere except 1 pixel) and asserts `result.sum() >= 4 * height_studs`.

---

<!-- autofix-applied: 2026-06-14 -->
### Step 2: Diagnose rembg server-side sparsity

**Problem:** Local rembg on `cartoon_star2.png` gives 25% fill; server gives ~1%. Unknown whether this is a model version issue, onnxruntime async-context issue, or the u2net model failing on yellow/white images.

**Type:** operator

**Issue:** #34

**Flags:** (none)

**Files:** `docs/investigations/INV-7-test-constraint-and-shape-quality.md`, `docs/investigations/INV-7-step2-verdict`

**Produces:** Findings added to INV-7 and a verdict file consumed by Step 3.

**Work:**
1. Start the server (set PATH first): `$env:PATH += ";C:\Tools\LPub3D"` then `uv run uvicorn --app-dir src brickomancer.main:app`.
2. POST a generate request with `cartoon_star2.png` and `height_studs=5`.
3. Check server stdout (after Step 1 is merged) for the `silhouette fill:` log line.
4. If fill < 5%: `echo SPARSE > docs/investigations/INV-7-step2-verdict` and add findings to INV-7.
5. If fill 20–30%: `echo OK > docs/investigations/INV-7-step2-verdict` and add findings to INV-7.
6. Record observed fill % and diagnosis in INV-7.

**Done-when:** `docs/investigations/INV-7-step2-verdict` exists and contains `SPARSE` or `OK`; observed fill % and diagnosis are recorded in `docs/investigations/INV-7-test-constraint-and-shape-quality.md`.

---

<!-- autofix-applied: 2026-06-14 -->
### Step 3: Switch rembg model from u2net to birefnet-general

**Problem:** The u2net model has poor foreground/background separation for bright cartoon subjects (yellow star) on white backgrounds because luminance contrast is low. `birefnet-general` is significantly more accurate on flat-color cartoon subjects.

**Type:** conditional

**Condition:** test -f docs/investigations/INV-7-step2-verdict && grep -qi "SPARSE" docs/investigations/INV-7-step2-verdict

**Issue:** #35

**Flags:** (none)

**Files:** `src/brickomancer/services/image_pipeline.py`, `tests/test_image_pipeline.py`

**Produces:** Modified `src/brickomancer/services/image_pipeline.py`

**Changes:**
- Add `from rembg import new_session as _rembg_new_session` inside the guarded `try` block (alongside the existing `from rembg import remove as _rembg_remove`).
- Add a module-level `_REMBG_SESSION = None` sentinel before `_REMBG_AVAILABLE`.
- In `_remove_background`, lazily initialise `_REMBG_SESSION` on first call: `if _REMBG_SESSION is None: _REMBG_SESSION = _rembg_new_session('birefnet-general')`. Then replace `_rembg_remove(input_bytes)` (line 73) with `_rembg_remove(input_bytes, session=_REMBG_SESSION)`.
- Update the ImportError message to reflect `birefnet-general`.
- Update `test_remove_background_returns_rgba_image` and `test_remove_background_raises_when_rembg_unavailable` in `tests/test_image_pipeline.py` — the mocks already target `_rembg_remove` and `_REMBG_AVAILABLE`, which remain unchanged. Add `test_remove_background_uses_birefnet_model()` that mocks `_rembg_new_session` and verifies `'birefnet-general'` is passed.
- Note: `birefnet-general` model is ~350 MB and downloads on first use via rembg's model cache. No manual download step needed; the server startup will trigger the download on first request if not cached.

**Done-when:** After a live server request, the `silhouette fill:` log line (from Step 1) shows ≥ 15% for both star images. The compact-tier LDR has > 10 bricks.

---

<!-- autofix-applied: 2026-06-14 -->
### Step 4: Replace stride-2 compact downsample with 2×2 OR-pooling

**Problem:** `grid[::2, :, ::2]` keeps even-indexed studs. For a 20×20 star silhouette centered at (10,10), the star arms often fall on odd indices, so downsampling can retain only 10–25% of star voxels rather than the expected 25% (pure random). The compact tier should preserve the SHAPE at lower resolution, not just subsample.

**Type:** code

**Issue:** #36

**Flags:** (none)

**Files:** `src/brickomancer/services/suggestion_service.py`, `tests/test_suggestion_service.py`

**Produces:** Modified `src/brickomancer/services/suggestion_service.py`

**Changes:**
- Replace `_downsample` with 2×2 OR-pooling (max-pool in XZ, preserve Y):
  ```python
  def _downsample(grid: np.ndarray) -> np.ndarray:
      X, Y, Z = grid.shape
      # Pad to even dimensions
      px = X % 2
      pz = Z % 2
      if px or pz:
          grid = np.pad(grid, ((0, px), (0, 0), (0, pz)), mode="edge")
      Xp, _, Zp = grid.shape
      # 2x2 OR-pool in XZ: True if any of the 4 source studs is True
      return grid.reshape(Xp // 2, 2, Y, Zp // 2, 2).any(axis=(1, 4))
  ```
  Result shape: `(ceil(X/2), Y, ceil(Z/2))`.
- Add `import numpy as np` if not already present (it is, via existing code).
- Add `test_compact_downsample_preserves_star_shape()` to `tests/test_suggestion_service.py` — create a synthetic 20×20 star-like mask (ring of True studs around center), downsample, assert ≥ 50% of True studs are retained and result shape is `(10, Y, 10)`.

**Done-when:** `_downsample` on a star-shaped 20×20 mask retains ≥ 50% of True voxels (verified by the new test). The compact LDR has > 10 bricks per layer when rembg is working.

---

<!-- autofix-applied: 2026-06-14 -->
### Step 5: Add a shape-fidelity integration test using the gold star dataset

**Problem:** No test catches a regression where the full pipeline (rembg → extrude → pack) produces a degenerate 1×1 column for the star images. The unit tests all use synthetic all-opaque images that can't expose rembg sparsity. A regression introduced in any step is invisible until a full harness run.

**Type:** code

**Issue:** #37

**Flags:** (none)

**Files:** `tests/integration/test_star_pipeline.py`, `CLAUDE.md`

**Produces:** New test `tests/integration/test_star_pipeline.py`

**Changes:**
- Create `tests/integration/test_star_pipeline.py` (alongside existing `test_smoke.py`).
- Gate on env var: `pytest.importorskip` pattern or `@pytest.mark.skipif(not os.getenv("BRICKOMANCER_INTEGRATION"), reason="set BRICKOMANCER_INTEGRATION=1 to run")`.
- `brick_packer.pack(voxel_grid, color_id)` returns `list[BrickPlacement]`. `BrickPlacement` shape (from `src/brickomancer/models/brick.py`):
  | field | type | note |
  |---|---|---|
  | `part_id` | str | LDraw part filename |
  | `color_id` | int | LDraw color ID |
  | `x` | int | stud X position |
  | `y` | int | brick layer (vertical) |
  | `z` | int | stud Z position |
  | `width` | int | brick width in studs |
  | `length` | int | brick length in studs |
- Test: `test_star_compact_produces_star_shape()` — calls `image_pipeline.run()` on `docs/example_input_output/star/input_image/cartoon_star2.png` with `height_studs=5`, then `suggestion_service._downsample()`, then `placements = brick_packer.pack(voxels)`. Asserts:
  - `voxels.sum() >= 50` (not a nearly empty grid)
  - `len(placements) >= 10` (not a 1×1 column)
  - `len(set((b.x, b.z) for b in placements)) >= 5` (bricks at ≥ 5 distinct XZ positions)
- Note: requires onnxruntime installed (same as existing integration smoke tests). Excluded from default `uv run pytest -q --ignore=tests/integration` gate.
- Update `CLAUDE.md` **pytest note** section to mention `BRICKOMANCER_INTEGRATION=1 uv run pytest tests/integration/` as the integration gate command.

**Done-when:** `BRICKOMANCER_INTEGRATION=1 uv run pytest tests/integration/test_star_pipeline.py -v` passes.

---

<!-- autofix-applied: 2026-06-14 -->
### Step 6: Clarify the axis contract in the developer-agent prompt to stop axis-change regressions

**Problem:** In two consecutive harness runs (iters 3 and 5), the developer agent proposed changing the extrusion axis from Y to Z. Both times the tests correctly rejected the change. The agent spent 10–15 minutes per iteration on a wrong approach because the advisor feedback ("tall narrow column") sounds like an axis problem, but the real issue is sparse voxels.

**Type:** code

**Issue:** #38

**Flags:** (none)

**Files:** `tests/harness/run_harness.py`

**Produces:** Modified `tests/harness/run_harness.py` (developer agent prompt)

**Changes:**
- Locate the developer agent prompt in `developer_agent()` at line 561 (the `f"Do not add explanatory comments..."` f-string line).
- Append a new f-string segment immediately after that line:
  ```python
  f"\n\nAXIS CONVENTION — DO NOT CHANGE:\n"
  f"  voxel_grid shape is (X, Y, Z) where Y is the vertical build axis (brick layers).\n"
  f"  _extrude_silhouette MUST return (footprint_x, height_studs, footprint_z).\n"
  f"  Any change that makes shape[1] != height_studs will fail three existing tests.\n"
  f"  The 'tall narrow column' symptom is caused by a sparse voxel grid from rembg,\n"
  f"  NOT by the wrong axis — do not attempt axis changes.\n"
  ```

**Done-when:** A harness run where `shape_fidelity` is selected does NOT attempt an axis change. Verified by checking that no `change_summary` in `scores.jsonl` mentions "axis", "XY plane", "Z axis", or "extrude along Z".

---

## Dependency order

```
Step 1 (logging + guard) → Step 2 (operator: observe live server)
                                    │
                    ┌───────────────┴───────────────┐
           Step 3 (model switch)          Step 4 (downsample fix)
           (conditional: SPARSE)          (always runs)
                    └───────────────┬───────────────┘
                             Step 5 (integration test)
                             Step 6 (prompt fix) ← independent, can run any time
```

Step 6 is independent — run it before the next harness iteration to prevent another wasted axis-change attempt.

---

## Success criteria

| Metric | Current | Target |
|---|---|---|
| shape_fidelity raw | 2/10 | ≥ 6/10 |
| build_stability raw | 1/10 | ≥ 5/10 |
| Compact tier bricks/layer | 1 | ≥ 7 |
| Developer-agent axis-change attempts | 2 in run 5 | 0 in run 6 |
| Harness SKIPPED_REVERT due to these 3 tests | 2 in run 5 | 0 in run 6 |
