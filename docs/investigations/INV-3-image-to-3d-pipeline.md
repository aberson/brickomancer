# INV-3: Image → 3D Shape Pipeline

**Question:** Given a single photo of a real-world object (a birthday cake, a bear, a house), what's the best approach to extract enough 3D shape information to voxelize it at LEGO stud resolution (8mm per stud, 9.6mm per brick height)?

---

## Executive Summary

Five approaches evaluated for generating voxel-ready 3D geometry from a single photo. For V1 on a standard developer laptop: **manual shape parameterization** as the bootstrap (zero ML, CPU-only), with **TripoSR** as the first automated upgrade once a 6GB GPU is available. Gold standard with workstation GPU: TripoSR/SF3D + Depth Pro for scale calibration.

---

## Approach 1: Monocular Depth Estimation

**Models:** MiDaS, Depth Anything V2, ZoeDepth, Depth Pro (Apple)

**Output:** 2D depth map (H × W float array). From this, a front-facing point cloud can be back-projected using camera intrinsics.

**Relative vs. Metric Depth:**

| Model | Depth Type | Notes |
|---|---|---|
| MiDaS | Relative only | No physical scale |
| Depth Anything V2 | Relative (small) / metric (large) | pip-installable |
| ZoeDepth | Metric | Degrades outdoors (MAE 3.087m) |
| Depth Pro (Apple) | Metric, absolute scale | No EXIF/intrinsics needed; estimates focal length |

**Accuracy:** Depth Pro on Sun-RGBD: δ₁ = 0.89. Boundary F1 on Sintel: 0.409 vs 0.228 for Depth Anything V2 — roughly 1.8× sharper edges.

**Critical limitation for LEGO use:** Monocular depth gives only the **visible front surface**. The back half of a birthday cake is invisible. The resulting point cloud is a 2.5D shell, not a closed solid. The "Front2Back" problem: back geometry must be synthesized or mirrored.

**CPU viability:**
- Depth Anything V2 small (25M params): runs on CPU in a few seconds.
- Depth Pro: GPU strongly preferred (6GB VRAM, ~0.3s); CPU would take minutes.

**Verdict:** Best as a scale-calibration supplement. Alone, produces an incomplete front-surface shell — inadequate for solid voxelization.

---

## Approach 2: Object Recognition + Shape Template Matching

**Stack:** YOLOv8 (detection) → GroundingDINO (open-vocabulary) → SAM (segmentation) → shape archetype lookup → parameterized geometry

**How it works:**
1. Detect object class ("birthday cake", "teddy bear")
2. Map class to geometric primitive (cake → cylinder, house → box + prism)
3. Use bounding-box aspect ratio / depth estimate to scale the primitive
4. Voxelize the parameterized primitive

**Accuracy:**
- Detection: GroundingDINO + SAM achieves zero-shot detection with ~90% AP on COCO-style benchmarks for common objects
- Shape mapping: **rule-based and brittle**. A cake → cylinder is reasonable; a horse is not well-approximated by any single primitive
- Works well for structured, category-constrained objects (food, buildings, vehicles); fails for organic/irregular shapes

**CPU viability:**
- YOLOv8 nano/small: CPU-viable, <1s per image
- SAM ViT-B (base): ~5–10s on CPU
- Shape parameterization: pure Python math, negligible

**Verdict:** Works for structured objects (cakes, boxes, cups) entirely on CPU. Produces a closed solid. Fails for organic shapes without a rich archetype library.

---

## Approach 3: NeRF / Gaussian Splatting

**Single-image viability:** Standard NeRF and 3D Gaussian Splatting require 30+ images and SfM initialization (COLMAP). Not single-image methods.

Single-image variants (Zero123, Zero123++) are essentially generative models with prohibitive VRAM requirements (22GB on RTX 3090/4090). Zero123+ generates in ~20s on GPU.

**Verdict:** Not viable for V1 on a developer laptop. Multi-image requirement rules out the base approach. Single-image variants have prohibitive VRAM requirements (22GB). Skip for V1.

---

## Approach 4: Image-to-3D Generative Models

| Model | Inference Time | GPU VRAM | CPU? | Output |
|---|---|---|---|---|
| **Shap-E** (OpenAI) | Seconds on GPU; hours on CPU (tested: 3% done after 1h on Intel U-series) | CUDA required | Effectively no | PLY/OBJ mesh |
| **Zero123 / One-2-3-45** | 45s (One-2-3-45) | 22GB (RTX 3090/4090) | No | Textured mesh |
| **TripoSR** (Stability AI + Tripo AI, MIT) | 0.5s on A100; ~30-120s on CPU | 6GB VRAM (half-precision) | Technically yes, slow | OBJ/GLB mesh, up to 100K polygons |
| **SF3D** (TripoSR successor) | 2.3s on A100 | 9GB VRAM | No | OBJ/PLY, 120K polygons |

**TripoSR details (the practical pick):**
- Open source, MIT license. `pip install` from GitHub or HuggingFace.
- On RTX 4050 6GB: confirmed fits in VRAM at half-precision.
- Input requirement: clean subject image; **background removal required** for best results (use `rembg` library, CPU-viable).
- Generates a **closed watertight mesh**, including inferred back geometry. This is the key advantage over depth estimation.
- Real-world limitations: struggles with occlusion, highly complex shapes, poor lighting.
- Quality: on OmniObject3D: CD 0.102, FS 0.677. Clean geometric objects (mugs, cakes) come out well; furry animals and irregular shapes degrade. At LEGO stud resolution (8mm voxels), fine surface detail loss is acceptable.

**End-to-end pipeline with TripoSR:**
```
Input photo
  → rembg (background removal, CPU, pip install rembg)
  → TripoSR (3D mesh, OBJ)
  → trimesh.load() + mesh.voxelized(pitch=0.008)  # 8mm pitch
  → brick packing
```

**Verdict:** Best automated single-image path. On 6GB laptop GPU: 0.5–2s end-to-end. On CPU only: 2–10 minutes per image. Produces a closed mesh ready for trimesh voxelization.

---

## Approach 5: Manual Shape Parameterization (CPU Fallback)

**How it works:** User selects a shape archetype from a menu (cylinder, box, sphere, L-shape, composite) and provides or confirms key dimensions. AI assists by estimating aspect ratio from the image bounding box.

**Accuracy:** Exactly what the user specifies. Highly accurate for symmetric, regular objects. Underfits for organic shapes.

**Compute:** Zero ML inference required. Pure Python geometry. Runs on any hardware in milliseconds.

```python
import trimesh
mesh = trimesh.creation.cylinder(radius=0.05, height=0.08)  # 10cm diameter cake, 8cm tall
voxels = mesh.voxelized(pitch=0.008)
```

**Verdict:** Only fully CPU-viable approach that is correct by construction. Appropriate for V1 as a fallback or user-override mode.

---

## Ranked Recommendations

### V1 — Standard Developer Laptop (CPU-only or integrated GPU)

**Tier 1: Implement first**
**Approach 5 (manual parameterization)** — zero ML, millisecond runtime, correct geometry for regular objects. Unblocks brick packing pipeline end-to-end.

**Tier 2: Add next (still CPU-viable)**
**Approach 2 (YOLOv8 + shape template)** — adds automated category→archetype mapping. YOLOv8-nano (CPU, ~1s) + curated archetype map for 10 most common LEGO subject types.

**Tier 3: Add when 6GB discrete GPU available (confirmed for this project via void_furnace substrate)**
**Approach 4 (TripoSR)** — replaces archetype lookup for arbitrary objects. Run rembg (CPU) first. Produces closed mesh for trimesh voxelization. Handles organic shapes without manual intervention.

### Gold Standard — Workstation GPU (8GB+ VRAM)

**Primary:** TripoSR (fast, open-source, 6GB VRAM) or SF3D (better geometry, 9GB VRAM)

**Scale calibration:** Depth Pro (Apple) — run in parallel to get metric depth map; use estimated focal length + metric scale to correctly size the TripoSR mesh before voxelization.

```
Input photo
  → rembg (background removal)
  → [parallel] TripoSR (closed mesh) + Depth Pro (metric scale reference)
  → Scale TripoSR mesh to Depth Pro's estimated object depth
  → trimesh.voxelized(pitch=0.008)
  → brick packing
```

---

## Key Implementation Notes

1. **Voxelization pitch:** `trimesh.voxelized(pitch=0.008)` = 8mm/stud. For plate height use 0.0032m (3.2mm). For brick height use 0.0096m (9.6mm).
2. **Background removal is mandatory** for TripoSR. Use `rembg` (`pip install rembg`), CPU-viable, ~1–2s per image.
3. **Scale is the hardest problem** with generative models: TripoSR doesn't know if it's reconstructing a 10cm cake or a 3m cake. Ask user to confirm height in studs.
4. **Shap-E is not viable on CPU.** Tested externally: 3% of render after 1 hour on Intel 8th Gen. Skip unless CUDA GPU available.

---

## Sources

- [Depth Pro paper (arXiv 2410.02073)](https://arxiv.org/html/2410.02073v1)
- [Depth Anything V2 PyPI](https://pypi.org/project/depth-anything-v2/)
- [TripoSR paper (arXiv 2403.02151)](https://arxiv.org/pdf/2403.02151)
- [TripoSR: Stability AI announcement](https://stability.ai/news-updates/triposr-3d-generation)
- [Shap-E GitHub (openai/shap-e)](https://github.com/openai/shap-e)
- [Shap-E CPU performance (Tom's Hardware)](https://www.tomshardware.com/news/openai-shap-e-creates-3d-models)
- [Zero123++ GitHub](https://github.com/SUDO-AI-3D/zero123plus)
- [Image2Lego paper (ar5iv)](https://ar5iv.labs.arxiv.org/html/2108.08477)
- [brickalize GitHub](https://github.com/CreativeMindstorms/brickalize)
- [Front2Back paper (arXiv 1912.10589)](https://arxiv.org/pdf/1912.10589)
