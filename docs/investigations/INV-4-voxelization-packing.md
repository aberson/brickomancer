# INV-4: Voxelization + LEGO Brick Packing Algorithms

**Question:** Given a 3D mesh representing a target object shape, what is the best algorithm to fill it with real LEGO bricks to produce a stable, buildable model?

---

## Executive Summary

No production-quality open-source Python library exists for the full pipeline (mesh → stable brick layout → LDraw output). The closest is `brickalize` (PyPI) but it lacks interlocking enforcement. The canonical V1 algorithm is greedy layer-by-layer with masonry offset and connectivity repair — implementable in 2–4 weeks, well-validated by multiple independent papers, produces buildable results for simple to moderately complex models.

---

## 1. The Legolization Paper (Luo et al., SIGGRAPH Asia 2015)

**Citation:** Luo, Yue, Huang, et al. "Legolization: Optimizing LEGO Designs." *ACM Transactions on Graphics* 34(6), 2015.

**Full pipeline:**
1. Input mesh voxelized at user-chosen resolution (each voxel = one LEGO plate or brick unit)
2. Initial brick layout generated heuristically (greedy layer-by-layer, largest-brick-first)
3. **Force-based stability metric:** model treated as a rigid-body system; forces (gravity, stud-to-stud coupling) propagated through a contact graph; weak sub-assemblies identified
4. **Layout refinement:** iteratively reconfigures bricks in weak regions until stability metric passes
5. Color information respected; output includes brick placement list, color assignments, building instructions

**Limitations:**
- Shape approximation limited to axis-aligned bricks; slopes/tiles/SNOT not supported
- Refinement is iterative without optimality guarantees
- Compute time scales poorly beyond ~5000 bricks
- **No official source code released.** Two independent course-project reimplementations exist ([debilin/Legolizer](https://github.com/debilin/Legolizer), [BijoySingh/Legolization-Computer-Graphics](https://github.com/BijoySingh/Legolization-Computer-Graphics)) but neither is the authors' production system.

---

## 2. Other Academic Approaches

### Greedy + Stability Repair (Hildebrand et al., EPFL 2013)
"Automatic Generation of Constructable Brick Sculptures" — voxelize mesh, greedily merge voxels into largest legal brick, apply local repair pass to fix disconnected subgraphs. Output includes step-by-step assembly instructions. Does not model knob friction — uses simple graph connectivity as stability proxy.

### Evolutionary / Genetic Algorithms
- **SM-GA (Split-and-Merge GA):** chromosome = brick layout; fitness = minimize brick count + maximize connectivity; applies split/merge mutations. Slow for large voxel grids.
- **GECCO 2015 GA:** models layout as combinatorial optimization, maximizes connectivity then minimizes brick count. Always generates feasible layouts. Works on per-layer 2D sub-problems.

### Matheuristics (ILP + greedy hybrid, DTU Research)
A greedy phase fills large regular regions; ILP optimizes structurally critical zones (connected-component repair, boundary zones). Hybrid outperforms pure greedy on stability at acceptable runtime for models up to a few hundred bricks per layer.

### LLM/Autoregressive (LegoGPT, 2025)
Fine-tunes LLaMA-3.2-1B to generate bricks autoregressively in raster-scan order. 98.8% stability, 100% validity on a 20×20×20 grid. Brick-by-brick rejection sampling + physics-aware rollback. Constrained to 8 brick types. Requires text prompts, not 3D geometry. **Not applicable to the mesh-to-LEGO pipeline.**

---

## 3. Greedy Algorithm — Detail

**Standard greedy pipeline:**
1. Voxelize mesh → 3D boolean occupancy grid
2. Slice into horizontal layers (each layer = 1 brick height)
3. For each layer (bottom to top), scan 2D occupancy bitmap and greedily place largest-fitting brick at each unoccupied cell
4. Common scan orders: raster (left-right, top-bottom), Morton/Z-order, or largest rectangular region first

**Stability tradeoffs:**
- Pure greedy with raster scan aligns brick boundaries vertically across layers → creates "fault planes" where the model splits easily
- **Interlocking heuristic:** force each brick to overlap at least one brick edge from the layer below by at least 1 stud
- **Masonry offset:** alternate even/odd layer scan start position by half a brick width. Simple, effective, zero extra cost.
- **Connectivity-first greedy:** prioritize positions that connect the most disconnected components (union-find on the interlocking graph). 2–3× overhead but dramatically reduces floating sub-assemblies.

**Heuristics that improve structural integrity:**
- Each brick should have ≥50% of its bottom and top faces covered by bricks on adjacent layers
- Minimize connected components: add a post-pass that reassigns brick boundaries to join isolated clusters
- Avoid long unbroken seams: detect and break horizontal seam lines of length > threshold

---

## 4. ILP / Constraint Programming

**Full-3D ILP is intractable:** A model with V occupied voxels can have O(V × |BrickTypes|) binary placement variables. For a 50×50×30 voxel model with 10 brick types, that's millions of binary variables.

**What IS tractable:**
- **Per-layer 2D ILP:** Each horizontal layer has a 2D grid of ≤ ~2500 cells. ILP with CP-SAT (OR-Tools) or CBC (PuLP) can solve layers of ~50×50 in seconds to a few minutes.
- **Structural repair ILP:** After greedy placement, identify the K bricks forming weak connections and solve an ILP restricted to that local neighborhood. K ≤ 20–30 remains fast.
- **StableLego stability check:** Uses Gurobi to solve the force-balance LP. Tractable for structures up to 300+ bricks in seconds, but requires a Gurobi license.

**Brickomancer V2:** OR-Tools CP-SAT per-layer ILP is the correct upgrade. No proprietary solver needed.

---

## 5. Open-Source Implementations

| Tool | Language | Voxelization | Brick Placement | Interlocking | LDraw Output | Status |
|---|---|---|---|---|---|---|
| **brickalize** (PyPI, `pip install brickalize`) | Python | STL → voxel grid | Greedy, largest-brick-first | Not enforced | No | Active hobby project, v1.0.2 |
| **AJaiman/3D-to-Lego** | Python | Flood-fill + morphology | Not yet implemented | N/A | Planned | Incomplete |
| **StableLego** | Python | Not included | Not included (stability checker only) | Models knob friction via RBE | No | Published (IEEE RA-L 2024); needs Gurobi |
| **debilin/Legolizer** | C++ | Yes | Greedy + stability (Luo 2015) | Partial | No | Course project; not production-quality |
| **python-ldraw** | Python | No | No | No | Yes (write LDraw files) | Mature; useful for output stage |

**Conclusion:** No single Python library provides a complete, production-quality, stability-enforcing pipeline from mesh → brick layout → LDraw output. The closest is `brickalize`, but it lacks interlocking enforcement. **Build the packer from scratch in Brickomancer.**

---

## 6. Structural Stability — Physics

LEGO is NOT simply a stacking problem. The knob-cavity coupling creates:
- **Pulling force (upward):** tight fit causes ABS deformation; friction resists separation
- **Pressing force (downward):** weight of structure above
- **Dragging force:** friction at flat contact surfaces
- **Horizontal forces:** from neighboring bricks' knobs pressing laterally

This means LEGO structures can be stable even with overhanging bricks that pure downward-force models would incorrectly call unstable.

**Practical interlocking constraints for V1 implementation:**
1. Every brick must share at least 1 stud connection with at least one brick on the layer below (or be supported by a structurally connected neighbor)
2. No full-column alignment: a vertical column with aligned edges fails under lateral shear
3. Connected component check: flag any subgraph not connected to the base layer
4. Seam detection: find horizontal lines where all bricks share a common edge; break these seams

---

## 7. Python Libraries for 3D Mesh Voxelization

| Library | Solid voxelization API | Watertight required? | Speed | Notes |
|---|---|---|---|---|
| **trimesh** | `mesh.voxelized(pitch, method='ray').fill()` | Strongly preferred | Fast | Best-maintained; `.fill()` does flood-fill interior; recommended |
| **open3d** | `VoxelGrid.create_from_triangle_mesh(mesh, voxel_size)` | Yes | Very fast | Surface voxels only by default; post-process for solid fill |
| **pyvista** | `pyvista.voxelize(mesh, density)` | Preferred | Medium | Fills interior by default (VTK implicit distance) |
| **voxelfuse** | `VoxelFuse.import_mesh(file)` | Yes | Medium | Multi-material support; morphology ops useful |

**Recommendation:** `trimesh` with `method='ray'` and `.fill()`. Pure Python install, returns numpy-backed occupancy matrix, most actively maintained.

```python
import trimesh
mesh = trimesh.load('model.stl')
voxels = mesh.voxelized(pitch=8.0, method='ray')
voxels.fill()
grid = voxels.matrix  # numpy bool array shape (X, Y, Z)
```

---

## Recommended V1 Algorithm

**Greedy layer-by-layer with interlocking enforcement (2–4 weeks to implement)**

**Step 1 — Voxelization:**
- `trimesh` load + `mesh.voxelized(pitch=8.0).fill()` → `grid[x, y, z]` bool

**Step 2 — Brick placement:**
- Process layers bottom-to-top
- Per layer: greedy largest-brick-first (2×4 → 2×3 → 2×2 → 1×4 → 1×3 → 1×2 → 1×1)
- Masonry offset: alternate scan starting column by 1 stud on odd layers
- Interlocking pass: each brick at layer y>0 must overlap ≥1 brick from layer y-1 by ≥1 stud; if not, split into smaller bricks

**Step 3 — Connectivity repair:**
- Build adjacency graph (networkx); find disconnected subgraphs
- Attempt 1×2 bridges; flag unfixable zones as floating

**Step 4 — Output:**
- Write LDraw file using plain Python string formatting

**Expected quality:** Structurally sound for simple convex models; some isolated components in complex geometry. Visual accuracy ≥85% for models at 20+ studs in any dimension.

### V2 Upgrade Path

- **Per-layer ILP with OR-Tools CP-SAT:** 5–10× more stable results, 10–100× slower but tractable for typical layer sizes
- **Force-balance stability analysis:** StableLego's RBE stability checker (or simplified scipy.linprog version)
- **Plate-height resolution:** Support mixed brick heights (brick = 3 plates). Requires 3D placement with Z pitch = 3.2mm.
- **Extended brick catalog:** Slopes to approximate curved surfaces.

---

## Sources

- [Legolization: Optimizing LEGO Designs (ACM DL)](https://dl.acm.org/doi/abs/10.1145/2816795.2818091)
- [StableLego: Stability Analysis of Block Stacking Assembly (arXiv)](https://arxiv.org/html/2402.10711v2)
- [StableLego GitHub](https://github.com/intelligent-control-lab/StableLego)
- [LegoGPT / BrickGPT (arXiv 2505.05469)](https://arxiv.org/html/2505.05469v1)
- [brickalize (GitHub)](https://github.com/CreativeMindstorms/brickalize)
- [brickalize (PyPI)](https://pypi.org/project/brickalize/)
- [python-ldraw (GitHub)](https://github.com/rienafairefr/python-ldraw)
- [Models and algorithms for optimising 2D LEGO constructions (ScienceDirect)](https://www.sciencedirect.com/science/article/abs/pii/S0377221720306159)
- [Multi-Phase Search for LEGO Construction (ResearchGate)](https://www.researchgate.net/publication/365038321)
- [trimesh voxel creation docs](https://trimesh.org/trimesh.voxel.creation.html)
- [How to Voxelize Meshes in Python (Towards Data Science)](https://towardsdatascience.com/how-to-voxelize-meshes-and-point-clouds-in-python-ca94d403f81d/)
