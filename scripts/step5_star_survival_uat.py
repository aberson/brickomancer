"""Operator UAT artifact for Phase 3 Step 5: does the star survive image->voxels?

Step 5's literal done-when -- "from-image on the star fixture returns a voxel grid
whose top-down silhouette has >= 4 distinct protrusions (star points survive)" -- is
the shape-fidelity guard the ImageShaper step exists for. v1's failure mode was the
opposite: the silhouette+dome path fabricated depth and smoothed features into a blob.
The rebuilt ImageShaper (rembg -> Hunyuan3D-2mini -> voxelize) is supposed to preserve
protrusions, but that is only verifiable by running the REAL model -- unit tests mock
`_generate_mesh` (no GPU), so nothing automated exercises star-survival. This script is
the in-window operator check, mirroring scripts/step4_render_uat.py and
scripts/step7_render_uat.py (which the pytest gate likewise cannot do).

Run (needs a CUDA GPU + Hunyuan3D weights; ~a few min, model load is cached process-wide):
    $env:PYTHONPATH = "src"                     # src-layout package (as scripts/step7 does)
    $env:PATH += ";C:\\Tools\\LPub3D"          # for the optional LDView render
    uv run python scripts/step5_star_survival_uat.py                # default star fixture
    uv run python scripts/step5_star_survival_uat.py --max-dim 24   # override voxel resolution

What it does:
  1. Runs the REAL `ImageShaper(fixture).to_voxels()` (503-clean message if no GPU/weights).
  2. Prints the top-down silhouette (project down the vertical Y axis) as ASCII.
  3. Prints an ADVISORY protrusion count (radial-signature runs; see `count_protrusions`).
  4. Packs + writes an .ldr and renders a top-down PNG (tmp/step5_star_topdown.png) so the
     operator can eyeball the actual brick build.

PASS is an OPERATOR judgment: the top-down silhouette / render must show >= 4 distinct
star points. The printed count is only an aid -- the orientation note in image_shaper.py
warns the mesh may need re-canonicalizing so features survive a top-down projection, which
is exactly the tuning this check is meant to surface. Exit code: 0 if the advisory count
>= 4, 2 if it is below (still eyeball the render), 3 if the model is unavailable.
"""

from __future__ import annotations

import argparse
import os
import sys

import numpy as np

_DEFAULT_IMAGE = os.path.join(
    "docs", "example_input_output", "star", "input_image", "cartoon_star.jpg"
)
_MIN_PROTRUSIONS = 4  # Step 5 done-when threshold
_OUT_LDR = os.path.join("tmp", "step5_star_survival.ldr")
_OUT_PNG = os.path.join("tmp", "step5_star_topdown.png")


def top_down_silhouette(grid: np.ndarray) -> np.ndarray:
    """Collapse an (X, Y, Z) occupancy grid down the vertical (Y) axis to an (X, Z) mask.

    Y (axis 1) is vertical per the ImageShaper orientation note, so ``any(axis=1)`` is the
    top-down silhouette a viewer looking straight down would see.
    """
    if grid.ndim != 3:
        raise ValueError(f"expected a 3-D (X, Y, Z) grid, got shape {grid.shape}")
    return grid.any(axis=1)


def count_protrusions(silhouette: np.ndarray, nbins: int = 72, margin: float = 0.25) -> int:
    """Advisory count of star-point-like protrusions in a 2-D silhouette.

    Method: from the silhouette centroid, take the max radius in each of ``nbins`` angular
    sectors (empty sectors -> 0). A protrusion is a *contiguous circular run* of sectors
    whose radius exceeds ``mean_radius * (1 + margin)`` -- i.e. a lobe that genuinely sticks
    out past the average, separated from the next lobe by a valley (or an empty sector).
    This distinguishes a many-pointed star (deep valleys between points) from the v1 blob/
    dome failure mode (near-constant radius -> nothing exceeds the margin -> 0), which is the
    exact regression this check guards. It is a rough aid, NOT a gate -- the operator's
    eyeball of the render is the real verdict.

    Assumes a *solid* (filled) silhouette, which ``ImageShaper`` produces (``.fill()``); a
    hollow skeleton with equal-length spokes reads as 0. Validated on synthetic filled shapes
    (4/5/6-point stars -> >= their point count; disk/square/empty -> 0); it can over-count at
    coarse resolution (a false-positive-safe direction for a ">= 4" threshold).
    """
    xs, zs = np.nonzero(silhouette)
    if xs.size == 0:
        return 0
    cx, cz = xs.mean(), zs.mean()
    ang = np.arctan2(zs - cz, xs - cx)  # [-pi, pi]
    rad = np.hypot(xs - cx, zs - cz)
    bins = ((ang + np.pi) / (2 * np.pi) * nbins).astype(int) % nbins

    prof = np.zeros(nbins)
    np.maximum.at(prof, bins, rad)  # max radius per angular sector

    occupied = prof[prof > 0]
    if occupied.size == 0:
        return 0
    threshold = occupied.mean() * (1.0 + margin)

    above = prof >= threshold
    if not above.any():
        return 0
    if above.all():
        return 1  # a full ring above threshold is a disk, not a star

    # Count contiguous circular runs of above-threshold sectors.
    empty = np.where(~above)[0]
    rolled = np.roll(above, -empty[0])  # rotate so index 0 is a gap -> no wrap-around run
    runs = 0
    prev = False
    for v in rolled:
        if v and not prev:
            runs += 1
        prev = v
    return runs


def ascii_silhouette(silhouette: np.ndarray) -> str:
    """Render the (X, Z) silhouette as '#'/'.' text (rows = Z, cols = X)."""
    lines = []
    for z in range(silhouette.shape[1]):
        lines.append("".join("#" if silhouette[x, z] else "." for x in range(silhouette.shape[0])))
    return "\n".join(lines)


def _render_topdown(grid: np.ndarray) -> str | None:
    """Pack the grid, write an .ldr, and render a top-down PNG. Returns the PNG path or None."""
    import subprocess

    from brickomancer.services.brick_packer import pack
    from brickomancer.services.ldraw_writer import write_ldr
    from brickomancer.utils.subprocess_utils import _find_ldraw_dir

    placements = pack(grid, color_id=15)
    os.makedirs("tmp", exist_ok=True)
    out = write_ldr(placements, _OUT_LDR, tier_name="step5-uat")
    print(f"Wrote {out} ({len(placements)} bricks)")

    ldraw_dir = _find_ldraw_dir()
    cmd = [
        r"C:\Tools\LPub3D\3rdParty\ldview-4.5\bin\LDView64.exe",
        out,
        f"-SaveSnapshot={_OUT_PNG}",
        "-SaveWidth=700",
        "-SaveHeight=700",
        "-DefaultLatLong=90,0",  # straight down -> top-down plan view
        "-AutoCrop=1",
    ]
    if ldraw_dir:
        cmd.append(f"-LDrawDir={ldraw_dir}")
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"(top-down render skipped: {exc})")
        return None
    return _OUT_PNG if os.path.exists(_OUT_PNG) else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Step 5 star-survival operator UAT.")
    parser.add_argument("--image", default=_DEFAULT_IMAGE, help="input star image")
    parser.add_argument("--max-dim", type=int, default=None, help="voxel resolution knob")
    parser.add_argument("--no-render", action="store_true", help="skip the LDView top-down render")
    args = parser.parse_args(argv)

    if not os.path.exists(args.image):
        print(f"FAIL: input image not found: {args.image}")
        return 3

    from brickomancer.services.image_shaper import ImageShaper, ModelUnavailableError

    kwargs = {} if args.max_dim is None else {"max_dim": args.max_dim}
    shaper = ImageShaper(args.image, **kwargs)
    try:
        grid = shaper.to_voxels()
    except ModelUnavailableError as exc:
        print(f"MODEL UNAVAILABLE (needs CUDA GPU + Hunyuan3D weights): {exc}")
        return 3

    silhouette = top_down_silhouette(grid)
    count = count_protrusions(silhouette)

    print(f"\nInput: {args.image}   grid: {grid.shape} (X, Y, Z)")
    print("Top-down silhouette (rows = Z, cols = X):\n")
    print(ascii_silhouette(silhouette))
    print(f"\nAdvisory protrusion count: {count}  (Step 5 done-when: >= {_MIN_PROTRUSIONS})")

    if not args.no_render:
        png = _render_topdown(grid)
        if png:
            print(f"Rendered top-down brick view: {png}")
            print(f"  <-- OPERATOR: eyeball >= {_MIN_PROTRUSIONS} star points in that render")

    verdict = "PASS (advisory)" if count >= _MIN_PROTRUSIONS else "REVIEW (advisory < threshold)"
    print(f"\nSTEP5_STAR_SURVIVAL: {verdict} -- final PASS is the operator's eyeball.")
    return 0 if count >= _MIN_PROTRUSIONS else 2


if __name__ == "__main__":
    sys.exit(main())
