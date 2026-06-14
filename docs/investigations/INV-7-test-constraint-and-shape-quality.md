# INV-7 — Test Constraints and Shape Quality Root Cause

**Date:** 2026-06-14  
**Trigger:** Harness run 5 — iters 3 and 5 both SKIPPED_REVERT due to the same 3 tests blocking proposed axis changes. shape_fidelity raw = 2/10 and build_stability raw = 1/10 across all 5 iterations.

---

## Tests under investigation

Three tests in `tests/test_image_pipeline.py` blocked both developer-agent attempts:

| Test | Line | Assertion |
|---|---|---|
| `test_extrude_silhouette_height_dimension` | 166 | `result.shape[1] == height_studs` |
| `test_run_returns_bool_array_shape` | 217 | `result.shape[1] == 8` |
| `test_run_default_height_studs_10` | 236 | `result.shape[1] == 10` |

All three assert that dimension 1 (Y) of the voxel array equals `height_studs`. The developer agents tried to change `_extrude_silhouette` to extrude along Z instead of Y so the star face appears in the XY (front-camera) plane. Both times the tests correctly rejected the change.

**Verdict: the tests are correct.** The (X, Y, Z) = (stud_x, layer_y, stud_z) array contract is the right convention for the entire downstream stack (brick_packer, ldraw_writer, suggestion_service). Changing the extrusion axis would flip the meaning of `height_studs` and break the coordinate system for the LDraw output. The developer agents made wrong architectural choices; the tests caught them.

---

## Actual root causes (tests are not the problem)

### Root cause 1 — rembg produces sparse alpha masks server-side

Locally, rembg on `cartoon_star2.png` (1254×1254 RGB, white background) produces:
- Alpha > 128: **24.9%** of pixels (star body)
- After `_extrude_silhouette` at height_studs=5: **117 True voxels per layer** in a 20×20 grid

But the actual server output for `suggestion_1.ldr` (standard tier, no downsampling) shows only **3 bricks per layer** — consistent with ~3–5 True voxels per layer, not 117.

The server-side rembg call is producing a radically sparser alpha mask than the local call. Likely causes:
- onnxruntime session state differs in the FastAPI async context vs direct Python call
- Different rembg model version or model weights cached on disk
- Memory pressure or timeout causing partial inference
- The u2net model struggles with yellow cartoon stars on white backgrounds — the yellow/white contrast is low in luminance

No debug logging exists to capture alpha channel stats during a live pipeline call, making this hypothesis hard to confirm or refute.

### Root cause 2 — compact-tier downsample (`grid[::2, :, ::2]`) aligns poorly with the star silhouette

Even if rembg were working correctly (117 True voxels/layer), the compact tier downsampling:

```python
def _downsample(grid: np.ndarray) -> np.ndarray:
    return grid[::2, :, ::2]
```

keeps only even-index studs (0, 2, 4, ..., 18) in X and Z. For a star centered at (10, 10) in a 20×20 grid, the star arms extend outward from the center. The even-indexed positions happen to miss many of the arm pixels, reducing fill from 117 to 28 voxels per layer — only 25% retention. For a non-centered star or an asymmetric shape, retention could be far lower.

With 28 True voxels in a 10×10 grid, pack() produces 7 bricks per layer (35 total). That is a valid star shape but at half the spatial resolution.

### Root cause 3 — single-stud-wide column geometry trips the connectivity check

When the rembg output is sparse (Root cause 1), the voxel grid may have isolated True voxels with no neighbors. The brick_packer connectivity check at line 294 (`if not _has_connection(candidate, below_fps): continue`) then skips all candidate bricks for layers y>0 except the one at the sparsest valid overlap position. The 1×1 fallback at line 311 fires but only at positions that actually passed the grid check — leaving at most 1 brick per layer if only 1 voxel per layer survived rembg.

This is not a bug in brick_packer — the connectivity check is doing its job. The root is rembg sparsity.

### Root cause 4 — developer agent has no visibility into the voxel grid state

The advisor reports contain rendered previews and LDR content, but no diagnostic about what the voxel grid looked like before packing. So the developer agent makes changes to `_extrude_silhouette` (silhouette plane, threshold, axis) without knowing whether the grid fed to the packer was dense or empty. Both axis-change attempts were plausible guesses at a symptom (column-shaped output) without access to the underlying data.

---

## What the tests DO and DO NOT constrain

**DO constrain:**
- Output array is 3-D bool
- `shape[1]` (Y) equals `height_studs`
- X > 0, Z > 0
- Correct behavior with RGB input (treated as fully opaque)

**DO NOT constrain:**
- The XZ silhouette shape (no test checks that a star image produces a star-shaped XZ mask)
- The fill density (all-True and 1-True both pass)
- The behavior when rembg produces a sparse alpha mask
- Whether the compact-tier downsample preserves the shape

There is no integration test covering the full `rembg → _extrude_silhouette → pack()` chain with a real star image and asserting that the resulting voxel count is above some minimum threshold.

---

## Validation of the above (reproducible commands)

```powershell
# Local rembg output is dense:
uv run python -c "
import sys; sys.path.insert(0, 'src')
from brickomancer.services import image_pipeline as ip
import numpy as np
img = ip._remove_background('docs/example_input_output/star/input_image/cartoon_star2.png')
alpha = np.array(img.split()[3])
vox = ip._extrude_silhouette(img, 5)
print(alpha.mean(), vox[:,0,:].sum())   # expect ~64, ~117
"
```

```powershell
# Compact downsample loses 75% of voxels:
uv run python -c "
import sys; sys.path.insert(0, 'src')
from brickomancer.services import image_pipeline as ip, suggestion_service as ss
import numpy as np
img = ip._remove_background('docs/example_input_output/star/input_image/cartoon_star2.png')
vox = ip._extrude_silhouette(img, 5)
ds = ss._downsample(vox)
print(vox[:,0,:].sum(), ds[:,0,:].sum())  # expect 117, 28
"
```
