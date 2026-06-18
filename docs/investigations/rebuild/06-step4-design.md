# 06 — Step 4 design spec (in-volume bonding + split/re-merge + physics rollback)

**Status:** ✅ IMPLEMENTED 2026-06-18 (240 tests, 0 type errors, 0 lint; render-verified).
**Issue:** #53. **Depends on:** Step 3.

## What actually shipped (deltas from the spec below)

The spec's plan held up; a few things changed during implementation + a 3-agent adversarial review:

- **Hub solved by Z-EXTEND, not decompose.** The plus-star centre is a degree-4 hub on a 3-tall
  column; the spec's "spread hub bonds across distinct layers" can't fit 4 connections in 3 layers
  with 2-wide bonds. The fix that works: a `z_extend` strategy that grows an existing `(1,N)` z-brick
  to `(1,N+1)` to absorb a z-adjacent fragment WITHOUT consuming a layer (preserving the brick's span
  that holds the far arm). Strategy ranking: z-clean → z-extend → x-clean → z-decompose → x-decompose.
- **Strict-merge guard is load-bearing.** A primary bond must STRICTLY reduce the component count.
  Non-strict "no increase" let a decompose merge one pair while re-splitting another at net-zero,
  leaving the star a layer too tall. (`_bond_guards_ok(..., require_merge=True)`.)
- **Seam-reuse gate kept (not the symmetric-same-parity variant).** x-bonds rank below all z
  strategies, so on solid masonry grids a z-bond always wins and x-bonds never fire — the masonry ABAB
  seams are protected by the z-PREFERENCE itself. The gate is a secondary guard.
- **Tile pass is now 1-FOR-1 (adversarial-review BLOCKER).** Removing the cap-above merge exposed
  load-bearing wide bricks on the TOP surface; the old strip/unit tile-split severed those bonds
  (cube (7,2,3) → 4 components). Tiles now convert only when an exact `(w,l)` tile exists; otherwise
  the brick is kept (studs visible — a cosmetic cost, not a severed bond).
- **`(2,1)` render-VERIFIED in-session** (not just an operator hand-off): the matrix
  `0 0 1 0 1 0 -1 0 0` renders the `(2,1)` PERPENDICULAR to a known-correct `(1,2)`, confirming X-span.
  Re-runnable via `scripts/step4_render_uat.py`. (det=+1 / orthonormality is also a unit assertion.)
- **Phase D (CP-SAT) skipped** as the spec advised — no disconnected-layer case survives.
- **Known limitation:** minimum-depth slabs (Z=2) and Y=2,Z∈{5,9} keep +1/+2 height via the cap
  fallback (still 1 component + 0 unsupported). All THICK grids (Y≥3 ∧ Z≥3 — real voxelised objects)
  are zero-height. Documented + guarded by `TestStep4SolidGridRobustness`.

---

**(original build-ready spec follows)** — Produced by a 5-agent design workflow
(2026-06-17) and refined by an empirical investigation that REVERTED a partial Step-4 attempt.
**Feasibility:** hard-but-doable. **Depends on:** Step 3 (`9b6802d`, committed).

## What Step 4 must deliver

1. **Replace the cap-above `_merge_components` with IN-VOLUME bonding** so connectivity adds NO
   build-height layers above the input grid top, WHILE preserving the masonry-offset (ABAB) seams.
2. **Phase C:** targeted split/re-merge around articulation points (bounded ≤5 iterations) —
   eliminate cut vertices at arm tips.
3. **Physics-aware rollback** (BrickGPT-style): reject a bond that would create an unsupported or
   cut-vertex brick; backtrack.
4. **Phase D (CP-SAT/OR-Tools): SKIP for V1** (no disconnected-layer case in scope survives Phase C;
   avoids a ~50 MB native dependency; add later behind a graceful-import guard if ever needed).

Done-when: a star-with-thin-arm-tips packs with zero freestanding 1×1 stacks AND zero arm-tip cut
vertices; a no-cut-vertex regression test; AND `max(bp.y for bp in pack(grid)) == grid_top_index`
(zero added height) with 1 component + 0 unsupported; all salvaged + Step-3 tests stay green.

## The crux (empirically verified — DO NOT re-derive blind)

Fragments are **full-height 1×1 towers** (cube → 4 components: corner (0,0) + edge towers (2,4),(3,4)
+ spine; plus-star → 7: arm-tip towers + center). Two adjacent full-height towers can only be bonded
by REPLACING/MERGING bricks at a shared in-grid layer (both columns are occupied at every layer — no
free stud to add into).

- **Z-direction bonds (same x, z differs by 1) are clean and provably seam-neutral.** Replace the two
  1×1s at a shared layer with one `(1,2)` brick: its `x + width == x + 1`, identical to the 1×1s it
  replaces, so the masonry seam_set (`{bp.x + bp.width}`) is UNCHANGED by construction — no parity
  reasoning needed. Zero added height (bond sits at an existing layer).
- **X-direction bonds (same z, x differs by 1) are THE hard sub-problem.** They need a 2-wide-in-X
  spanning brick. There is **no `(2,1)` part** in `BRICK_PART_IDS`, and the orientation branch in
  `pack()` (~lines 806-808) is DEAD CODE (`BRICK_PART_IDS` only has `w<=l` keys, so `(ln,w)` is never
  found — no brick is ever rotated; every placed brick is width-along-X, length-along-Z).
- **MEASURED CONSEQUENCE (why a z-only attempt was reverted):** without `(2,1)`, x-adjacent bonds can
  be made neither in-volume NOR via a cheap `1×N` cap (a 1×N along X is `(N,1)` — also missing). They
  fall to 2×2 caps that overhang in Z and STACK at hubs. A z-only in-volume pass therefore leaves
  **cube +1 (unchanged), star +4→+3** — the cube edge-towers (2,4),(3,4) and the star east/west arms
  are x-adjacent and cannot be cheaply bonded. **The `(2,1)` part is REQUIRED for the real
  zero-height goal; it is inseparable from Step 4's value.**

## The required part-set + writer change (the render-sensitive piece)

To bond x-adjacent towers in-volume (and cheaply):

- `models/brick.py`: add `(2, 1) -> '3004'` to `BRICK_PART_IDS` (logical horizontal 1×2 — same
  physical LDraw part 3004 as `(1,2)`). Do **NOT** add `(2,1)` to `BRICK_TYPES` (keep the greedy fill
  unchanged; `(2,1)` is bond-only). **Gotcha:** adding `(2,1)` to `BRICK_PART_IDS` makes the dead
  orientation branch in `pack()` start firing in the greedy main loop → it would rotate `(1,2)->(2,1)`
  during normal fill, changing masonry output and possibly breaking the seam tests. **Mitigation:**
  either explicitly exclude `(2,1)` from the orientation expansion (keep it bond-only) OR delete the
  orientation branch and have the bonder construct `(2,1)` directly.
- `ldraw_writer.py`: `_brick_line`/`_to_ldu` must emit a **90° rotation matrix** for the `(2,1)` part
  so it renders as a 1×2-along-X. Current writer uses identity `1 0 0 0 1 0 0 0 1` always. The rotated
  matrix is approximately `0 0 1 0 1 0 -1 0 0` (verify the exact matrix + LDU centroid offset against
  LDraw conventions). **This is producer/consumer + render-sensitive: a wrong matrix renders a
  misplaced/overlapping brick, visible ONLY in an LDView render, not in unit tests.** Add a unit test
  asserting the `(2,1)` line has the documented matrix, AND require an **operator LDView render UAT**
  of the packed star to confirm visually. BOM grouping in `suggestion_service` is by `part_id` only,
  so 3004 reuse is automatically correct.

## Recommended algorithm (HYBRID, anchored on "merge-at-shared-layer with seam-reuse")

Replace `_merge_components` with `_bond_components_in_volume(placements, color_id, max_iterations=5)`,
run in the same pack() slot (after `_brace_thin_columns`, before `_apply_surface_tiles`):

1. base = list(placements); if empty or `max(bp.y)==0` return unchanged (flat builds; matches
   existing single-layer test). If `connected_component_count <= 1` return unchanged (idempotent).
2. Build per-column maps from base ONLY (so anchor heights never run away): `col_comps[(x,z)]`,
   `col_layers[(x,z)]`, component-adjacency with a representative `(studA, studB, direction)` bond.
3. anchor = component with most ground bricks (tie → largest). BFS spanning tree, deterministic via
   `sorted(neighbors)`.
4. For each tree edge, pick a shared layer L (in `col_layers[A] & col_layers[B]`) and `_make_bond_brick`:
   - **z-direction:** emit `(1,2)` covering both studs at L (seam-neutral by construction). Remove the
     two 1×1s, add the `(1,2)`.
   - **x-direction:** try a legal `(2,2)+` only if a fully-occupied 2×2 block of currently-placed studs
     covers both columns at L (true for cube interior, FALSE for star arms). Else emit a `(2,1)` bond
     at `(min(xA,xB), L, zA)`, GATED: only when `min(x)+2` is ALREADY in `seam_set(L)` (seam-reuse) AND
     applied to ALL same-parity shared layers so `seam_set(L)==seam_set(L±2)`. If neither holds, defer.
   - Wider anchor brick blocks a needed stud → decompose locally, re-cover the rest, but ONLY at
     `y > tested masonry layers` OR symmetrically across same-parity layers (keeps ABAB intact).
5. **Physics guard** around every candidate placement: tentatively apply, reject if
   `unsupported_bricks` count increases OR `articulation_points` count increases; try next layer; if
   all fail, defer the edge. (Guard wraps the bonding passes only — NOT the hot greedy loop, which
   already has the `_has_connection` gate; per-voxel graph rebuilds would be quadratic.)
6. **Phase B `_eliminate_arm_tip_articulations`** (≤5 iters, after bonding): for each arm-tip cut
   vertex (a brick whose every stud is a boundary voxel of its layer), add a redundant second bond at
   a same-layer cardinal neighbor → turns the connection path into a cycle so the vertex stops being a
   cut vertex. Each change passes the physics guard + the height invariant. NOTE: a literal 1-wide arm
   tip is inherently a leaf; "zero arm-tip cut vertices" should mean "no cut vertex whose removal
   ORPHANS an arm from the spine" (match `test_articulation_point_actually_disconnects` semantics) —
   align the test accordingly.
7. **Fallback for deferred edges:** keep the existing cap-above logic, renamed
   `_merge_components_cap_fallback`, invoked ONLY for edges Phase A deferred, modified to a `1×N` chain
   cap (max +1 layer). With `(2,1)` available this should rarely fire.

Assert directly: `max(bp.y for bp in result) == max_input_y` (height invariant) and 1 component +
0 unsupported.

## Functions to add/change (`brick_packer.py` unless noted)

- ADD `_bond_components_in_volume`, `_make_bond_brick`, `_seam_set(placements, layer)`,
  `_is_arm_tip_brick(bp, grid)`, `_eliminate_arm_tip_articulations`, `_physics_ok(before, after)`.
- RENAME `_merge_components` → `_merge_components_cap_fallback`; modify to a `1×N` chain cap (max +1
  layer); demote to deferred-edge-only.
- MODIFY pack() tail: `... _brace_thin_columns -> _bond_components_in_volume ->
  _eliminate_arm_tip_articulations -> _merge_components_cap_fallback (deferred only) ->
  _apply_surface_tiles`.
- `models/brick.py`: add `(2,1) -> '3004'` (bond-only; keep out of `BRICK_TYPES`; handle the dead
  orientation branch).
- `ldraw_writer.py`: 90° rotation matrix + LDU offset for `(2,1)` (producer/consumer; render UAT).

## New tests

- `test_star_zero_added_height` (`max(bp.y for pack(star)) == 2`); `test_cube_zero_added_height` (== 4).
- `test_star_no_arm_tip_cut_vertices`; `test_star_single_component_in_volume`; `test_star_zero_unsupported`.
- `test_z_bond_is_seam_neutral`; `test_x_bond_gated_on_seam_reuse`.
- `test_three_adjacent_towers_bond_no_height`; carry `test_non_adjacent_components_stay_separate`.
- `TestPhysicsRollback::test_guard_rejects_unsupported`, `::test_guard_rejects_new_cut_vertex`.
- `ldraw_writer::test_2x1_emits_rotated_matrix` (+ BOM counts it as 3004).
- Star arm-tip fixture: reuse `_plus_star()` (already canonical, today packs to y=6/27 artic points);
  optionally add `_plus_star_thin_arms()` (7×3×7, 2-stud arms) to stress multi-tower-per-arm bonding.

## Tests at risk + how to keep them green

- Masonry ABAB (6×4×4) + `test_masonry_abab_preserved_after_merge`: route all 6×4×4 bonds through the
  z-direction `(1,2)` path; NEVER fire the `(2,1)` x-bond on solid grids (the seam-reuse gate +
  "z-bond first" precedence ensures this). Solid grids are largely one component → few bonds.
- 6×2×4 even≠odd + 8×2×4 multi-stud-per-layer: z-bonds touch no x-seam; x-bonds gated to seam-reuse
  (cannot erase the even/odd difference); decomposition branch gated to y>tested or symmetric.
- `TestMergeComponents` (call `_merge_components` directly): repoint to `_bond_components_in_volume`;
  **replace `test_merge_caps_are_supported`'s `any(bp.y>1)` assertion (which asserted caps EXIST
  above) with the new contract `no brick above input max y`** — this is the intentional
  codifying-test-diff (caps above are exactly what Step 4 removes); flag it explicitly per the
  audit-wire-shape rule.

## Open risks

- The `(2,1)` rotation matrix/LDU offset is render-only-verifiable → operator LDView UAT required.
- If a star arm's `min(x)+2` is NOT in `seam_set(L)`, the x-bond is deferred (or use symmetric
  same-parity x-bond — the star has only 3 layers, parities {0,2}/{1}, so symmetric is feasible).
- Multi-arm hub (star center bonds 3 arms) risks a NEW cut vertex; spread hub bonds across distinct
  layers/parities; verify with `test_star_single_component`.

## Why a z-only attempt was reverted (so the next session doesn't repeat it)

A z-only in-volume pass (no `(2,1)`) was implemented, passed all 66 packer tests (seam-neutral
confirmed), but measured **cube +1 (unchanged), star +4→+3** — the height bug is dominated by
x-adjacent bonds, which z-only cannot touch. The operator chose to checkpoint and do the full
`(2,1)`-inclusive Step 4 (with render UAT) as one coherent fresh effort rather than commit a
half-measure. The z-only code is recoverable from this session's transcript if useful, but the
recommended path is the full HYBRID above.
