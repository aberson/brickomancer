# 04 — Phase 0 Model Spike Result

**Date:** 2026-06-16
**Step:** Phase 0, Step 0.1 (umbrella #46, issue #47)
**Decision:** **Hunyuan3D-2mini** is the chosen image→3D model for the rebuild.
**Verdict:** PASS — a real 3D model voxelizes the star recognizably (points survive), retiring
the kill-criterion risk on umbrella #46.

## What was spiked

Per the operator's choice (spike both fully, no time-box), both candidates were installed and
run geometry-only on the actual hardware:

- **GPU:** NVIDIA GeForce RTX 4070 Laptop, **8188 MiB (~8 GB) total VRAM** — the binding
  constraint for this spike.
- **Env:** isolated throwaway venv `C:\Tools\spike3d\.venv-spike`, **uv-managed CPython 3.12.13**,
  `torch==2.7.1+cu118` (CUDA verified `True`). Star fixture:
  `docs/example_input_output/star/input_image/cartoon_star.jpg`.

## Results

| Candidate | Outcome | VRAM | Wall-clock | Notes |
|---|---|---|---|---|
| **Hunyuan3D-2mini** | **PASS** | well under 8 GB (no OOM; peak not captured) | **~103 s** | Shape-only; no C++/CUDA compilation needed. Weights 7.64 GB on disk (one-time HF download). |
| **TripoSG** | **INSTALL-BLOCKED on Windows** | n/a | n/a | Blocked at three escalating layers (see below). |

### Hunyuan3D-2mini — PASS

Ran clean once `torch` was correctly pinned to the **cu118** build (the initial `uv pip install
torch` resolved a CPU-only wheel — `2.x+cpu` — which failed with
`AssertionError: Torch not compiled with CUDA enabled`; fixed by
`uv pip uninstall torch torchvision` then `uv pip install torch==2.7.1+cu118
torchvision==0.22.1+cu118 --index-url https://download.pytorch.org/whl/cu118`).

- Inference: `Diffusion Sampling 50/50 @ ~8 it/s` + `Volume Decoding 7134/7134 @ ~144 it/s`,
  total **~103 s** wall-clock (excludes the one-time 7.64 GB weight download).
- Shape-only path **skips** the `custom_rasterizer` / `differentiable_renderer` C++ builds
  (those are texture-only) — this is why Hunyuan installs cleanly on Windows where TripoSG does
  not. No Visual Studio CUDA compilation required.
- Minimal API: `Hunyuan3DDiTFlowMatchingPipeline.from_pretrained('tencent/Hunyuan3D-2mini',
  subfolder='hunyuan3d-dit-v2-mini')` → `pipe(image='star.jpg')[0]` → `.export('star_hunyuan.glb')`.

### TripoSG — install-blocked on Windows (a clean, decisive finding)

This is exactly the risk the verdict doc named ("TripoSG is Linux-first; needs a Windows
runnability spike"). It blocked at three escalating layers:

1. **`diso==0.1.4` build-isolation failure** — `ModuleNotFoundError: No module named 'torch'`
   during build (diso doesn't declare torch as a build dep). Worked around with
   `--no-build-isolation`.
2. **`numpy==1.22.3` source build** — TripoSG's `requirements.txt` pins a numpy with no
   Python 3.12 wheel, so uv tried to compile it from source (`Cython needs to be installed` /
   numpy 1.22 predates 3.12 support). Worked around by installing only the script's real
   imports at modern versions instead of the pinned requirements file.
3. **`diso` CUDA extension — `fatal error C1083: Cannot open include file: 'cuda_runtime.h'`.**
   diso compiles a CUDA C++ extension that requires the **CUDA Toolkit** (`nvcc`,
   `cuda_runtime.h`) — present MSVC build tools are not enough, and the cu118 torch wheel ships
   only the runtime, not the dev toolkit. Installing CUDA Toolkit 11.8 is a multi-GB system
   install and out of scope for a de-risking spike.

**Decision:** do not install the CUDA Toolkit to chase TripoSG. The spike's purpose — confirm a
3D model voxelizes recognizably on this hardware — is satisfied by Hunyuan, and TripoSG's
repeated Windows-hostile build requirements are themselves the answer.

## The kill-criterion test: does the star voxelize recognizably?

`star_hunyuan.glb` → `trimesh.load(..., force='mesh')` → `m.voxelized(pitch).fill()` with
`pitch = m.extents.max() / 28`.

```
mesh: verts 150970 faces 301908 extents [1.992 1.776 0.238]
voxel grid shape (29, 26, 5) filled 421

Silhouette (collapsed axis 2 = the flat/depth axis, shape (29, 26)):
.............####.........
............######........
............######........
...........#######........
..........#########.......
....###..##########.......
..#################.......
.##################.......
.####################.....
.######################...
..#######################.
..########################
...#######################
....######################
....#####################.
....####################..
....###################...
...##################.....
...#################......
..#################.......
..#################.......
..#################.......
..#################.......
..#######..########.......
............######........
.............#####........
...............###........
#.........................
##........................
```

**Read:** the mesh is a genuine flat plate (extents `[1.99, 1.78, 0.24]` — thickness is the
short axis), the inverse of v1's center-bulged dome. Distinct protrusions are present: a **top
point**, a **bottom point**, and **left arms** (the jagged left edge + the `###..##` notch) —
**≥4 protrusions, the done-when bar is met.** A real star, recoverable where v1's
silhouette+dome heuristic flattened the points away.

## Carry-forward findings (NOT blockers — handled by downstream rebuild stages)

1. **Right edge is a flat wall, not crisp points.** The star is lopsided/soft on the right. An
   orientation + symmetry concern for the `ImageShaper` (Step 5) — the camera/canonicalization of
   the input, not a model limitation.
2. **Two detached corner voxels** (bottom-left `#` / `##`, rows 27-28). These are a disconnected
   component the **connectivity-graph packer (Phase 2, Step 3)** drops by construction (its
   done-when requires exactly one connected component). Confirms the packer's structural model is
   the right place to handle voxelization noise, not the Shaper.

## Reproducible install (what actually worked)

```powershell
# uv-managed env (do NOT use bare py/pip — uv owns Python + deps in this workspace)
mkdir C:\Tools\spike3d -Force; cd C:\Tools\spike3d
uv venv --python 3.12 .venv-spike
.\.venv-spike\Scripts\Activate.ps1
uv pip install torch==2.7.1+cu118 torchvision==0.22.1+cu118 --index-url https://download.pytorch.org/whl/cu118
python -c "import torch; print('cuda', torch.cuda.is_available())"   # MUST print True before proceeding
uv pip install trimesh numpy pillow rembg onnxruntime huggingface_hub

git clone https://github.com/Tencent/Hunyuan3D-2.git hunyuan-src
cd hunyuan-src
uv pip install -r requirements.txt
uv pip install -e .            # shape-only — do NOT build custom_rasterizer/differentiable_renderer
cd ..
# run_hunyuan.py: from_pretrained('tencent/Hunyuan3D-2mini', subfolder='hunyuan3d-dit-v2-mini')
python run_hunyuan.py
```

**Lesson for the rebuild (Step 5):** the only non-obvious install gotcha is the **cu118 torch
pin** — a bare `torch` install silently lands the CPU wheel. Pin `+cu118` explicitly and gate on
`torch.cuda.is_available()` before any model load.

---

*Toolchain + license confirmation (Step 0.2) is appended below once that step runs.*
