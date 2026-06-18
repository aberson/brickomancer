"""Operator UAT artifact for Phase 2 Step 4: render the (2,1) bond brick.

The bond-only (2,1) brick (LDraw part 3004 rotated 90 deg about Y) renders correctly
ONLY if its matrix + centroid are right -- and that is verifiable only by an actual
render, not by unit tests (which merely string-match the matrix). This script packs the
canonical plus-star, RECOLOURS the (2,1) x-bonds bright red, and writes an .ldr so the
operator can render it and confirm each red brick spans TWO studs along X (bridging two
arm columns) and is NOT misplaced, overlapping, or floating.

Run (writes the .ldr AND renders two PNGs via the project's configured LDView):
    uv run python scripts/step4_render_uat.py

It emits tmp/step4_star_uat.png (isometric) and tmp/step4_star_topdown.png (plan view).
Open both. PASS criteria (visual):
  - Every RED brick is a 1x2 lying flat, bridging two adjacent columns of the star's
    east-west (x) arm -- i.e. PERPENDICULAR to the white z-arm bonds. (The decisive
    check: a correct 90-deg rotation makes the (2,1) x-bonds run across the x-arm,
    not along the z-arm.)
  - No red brick is shifted half a stud, overlapping a neighbour, or hanging in air.
  - The star reads as ONE solid plus-cross at its input height (3 layers), no stray caps.

This was verified in-session (2026-06-18): the (2,1) renders perpendicular to a
known-correct (1,2), confirming the matrix. Re-run it after any change to the (2,1)
matrix or _to_ldu.
"""

import os
import subprocess

import numpy as np

from brickomancer.models.brick import BrickPlacement
from brickomancer.services.brick_packer import pack
from brickomancer.services.ldraw_writer import write_ldr
from brickomancer.utils.subprocess_utils import _find_ldraw_dir, run_ldview

_RED = 4
_OUT = os.path.join("tmp", "step4_star_uat.ldr")


def _plus_star() -> np.ndarray:
    grid = np.zeros((5, 3, 5), dtype=bool)
    grid[2, :, :] = True
    grid[:, :, 2] = True
    return grid


def main() -> None:
    placements = pack(_plus_star(), color_id=15)
    n_bonds = 0
    highlighted: list[BrickPlacement] = []
    for bp in placements:
        if (bp.width, bp.length) == (2, 1):
            n_bonds += 1
            highlighted.append(
                BrickPlacement(bp.part_id, _RED, bp.x, bp.y, bp.z, bp.width, bp.length)
            )
        else:
            highlighted.append(bp)

    os.makedirs("tmp", exist_ok=True)
    out = write_ldr(highlighted, _OUT, tier_name="step4-uat")
    print(f"Wrote {out}")
    print(f"(2,1) x-bonds highlighted RED: {n_bonds}")
    print(f"max layer (must be 2 = input top): {max(bp.y for bp in placements)}")

    # Isometric view via the project's configured LDView (passes -LDrawDir; a bare
    # invocation without the parts library renders an all-black PNG).
    iso_png = os.path.join("tmp", "step4_star_uat.png")
    run_ldview(out, iso_png)
    print(f"Rendered isometric: {iso_png}")

    # Top-down plan view (clearest for the x-arm vs z-arm perpendicularity check).
    top_png = os.path.join("tmp", "step4_star_topdown.png")
    ldraw_dir = _find_ldraw_dir()
    cmd = [
        r"C:\Tools\LPub3D\3rdParty\ldview-4.5\bin\LDView64.exe",
        out,
        f"-SaveSnapshot={top_png}",
        "-SaveWidth=700",
        "-SaveHeight=700",
        "-DefaultLatLong=90,0",
        "-AutoCrop=1",
    ]
    if ldraw_dir:
        cmd.append(f"-LDrawDir={ldraw_dir}")
    subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    print(f"Rendered top-down: {top_png}")


if __name__ == "__main__":
    main()
