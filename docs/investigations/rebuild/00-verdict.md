# Rebuild Verdict

## What actually went wrong (verified at source)

Two independent ceilings were active at once, which is why effort produced motion but no progress.

### Ceiling 1 — the input representation fabricates depth (architectural)

The image path never recovered true 3D. `image_pipeline._extrude_silhouette`
([image_pipeline.py:163-235](../../../src/brickomancer/services/image_pipeline.py#L163-L235))
takes the 2D alpha silhouette and applies a **radial-dome height map**:

```python
center = np.mean(active_coords, axis=0)
distances = np.linalg.norm(active_coords - center, axis=1)
norm_distances = distances / max_dist
height = floor_layers + (max_layers - floor_layers) * (1.0 - norm_distances)
```

Height is tallest at the centroid and shortest at the edges. A star's points are at the
**edges**, so they get the **shortest columns and vanish under the camera**. The output was
an amorphous domed slab, never a recognizable star. No code tweak inside this function can
fix it — the third dimension simply isn't in the input.

### Ceiling 2 — the harness optimized the wrong thing (process)

The self-improvement loop committed a change if and only if **pytest still passed**
([applier.py:172-231](../../../tests/harness/applier.py#L172-L231)) — it never re-rendered
the build or re-scored the output before committing. Consequences, measured from
`scores.jsonl` (160 rows):

- `pdf_completeness` and `instruction_clarity` **crashed to 0 and stayed there for ~40
  committed iterations** (a broken LPub3D meta-command config passed pytest, which renders
  no PDF, so the damage persisted).
- ~30 commits of pure **whack-a-mole** on the same handful of LPub3D meta-commands
  (FADE_STEPS / HIGHLIGHT_STEP / COVER_PAGE / BOM added, removed, re-added, reordered).
- `avg_raw` never trended up — it sat in the 3.5–5.1 band the entire run. (`avg_normalized`
  is a constant 5.0 by construction: scores are z-scored within each iteration, so its
  "plateau" is a math artifact, not a measurement.)

The harness was also **scope-bounded to single-file surgical edits** — it could never
redesign the pipeline, so it could not have escaped Ceiling 1 even in principle.

## What to keep (it's most of the backend)

The mechanical, deterministic, well-tested parts of v1 are good and should survive verbatim
or lightly adapted. See [01-distillation.md](01-distillation.md) for the full inventory:

- **Brick packer** (masonry offset, connectivity repair, surface tiles) — keep the algorithm,
  upgrade the structural model.
- **LDraw writer** (coordinate conversion, step sequencing) — keep.
- **Color service** (KMeans in Lab + ΔE2000), **data service** (LDConfig > CSV priority,
  color-ID validity), **subprocess integration** (LDView/LPub3D/Claude flags + gotchas) — keep.
- **~95% of unit tests** — keep as the regression spine.
- **Reference data** (LDConfig.ldr, dimensions.csv, download_data.py) — keep.
- **INV-1..7 + master_plan.md** — keep as reference.

The **throwaway** is `image_pipeline._extrude_silhouette` (the silhouette+dome heuristic) and
the crude Llama-1B text→primitive path.

## What to build (the rebuild)

1. **Replace silhouette extrusion with a true single-image-to-3D model.** Primary:
   **TripoSG** (MIT, SDF→watertight by construction, ~8 GB) or **Hunyuan3D-2mini** (~5 GB,
   best Windows tooling, license fine for a US personal tool). Both produce real volumetric
   meshes that voxelize cleanly. See [03-better-approaches.md](03-better-approaches.md).
2. **Replace greedy+repair packing with a connectivity-graph packer** (a deterministic CPU
   subset of Luo et al. SIGGRAPH Asia 2015): connectivity-aware fill → graph analysis
   (components, articulation points, unsupported bricks) → targeted split/re-merge. Makes
   structural soundness a property the packer can *see*, not a post-hoc patch.
3. **Keep LDView + LPub3D, but freeze a known-good meta header** as a constant the harness is
   forbidden to edit. The toolchain was never the problem; the editable meta layer was.
4. **Redesign the harness to score rendered output with a regression gate.** Re-render and
   re-score after each change; commit only if the targeted dimension does not regress and
   avg does not drop. This single change would have prevented the 40-iteration sinkhole.
5. **Text path:** have a capable model emit a coarse 20³ voxel occupancy grid (sparse
   coordinate list, not a dense grid), feed the shared packer. **BrickGPT** (MIT, runs on the
   Llama-3.2-1B you already have, LDraw-native, 98.8% stable) is a proven fallback for its 21
   in-domain categories.

## Recommended end-to-end architecture

```
IMAGE: photo → rembg (keep) → TripoSG / Hunyuan3D-2mini (geometry-only) → watertight mesh →
       voxelize @ ~24-32 → connectivity-graph packer → ldraw_writer → LDView + LPub3D (frozen meta)

TEXT:  prompt → model emits 20³ voxel occupancy (sparse list) → same packer → same backend
       [fallback: BrickGPT weights for its 21 categories]

LOOP:  judge reads RENDERED output → propose change → pytest gate → re-render + re-score →
       regression gate → commit only on no-regression
```

The strength of this design is that the **hard creative step (3D front-end, swappable) is
cleanly separated from the mechanical packing + rendering (shared, deterministic, testable)**.
v1's mistake was treating it as one monolithic pipeline.

## Key risk to retire early

The single biggest delivery risk is **Windows + CUDA runnability of the chosen 3D model**.
TripoSG is Linux-first (needs a Windows runnability spike); Hunyuan3D-2mini has a turnkey
Windows-portable build and the lowest VRAM, making it the lower-risk first pick. **Decide this
with a one-day spike before committing the rest of the plan** (Phase 0 in the rebuild plan).
