"""Step 7 render UAT — prove the frozen BOM-only header actually renders.

Builds a small grid → packs → writes a .ldr via the production ldraw_writer →
renders a preview PNG (LDView) and an instruction PDF (LPub3D). This is the
in-window render check the pytest gate cannot do (it mocks the tools). It
specifically exercises the COVER_PAGE removal: before Step 7 the writer emitted
`0 !LPUB INSERT COVER_PAGE`, which CRASHES LPub3D 2.4.9 (no PDF).

Run from the project root in PowerShell with LPub3D on PATH:
    $env:PATH += ";C:\\Tools\\LPub3D"
    $env:PYTHONPATH = "src"
    uv run python scripts/step7_render_uat.py
"""

from __future__ import annotations

import os
import re
import sys
import tempfile

import numpy as np

from brickomancer.services import brick_packer
from brickomancer.services.instruction_service import generate_pdf
from brickomancer.services.ldraw_writer import write_ldr
from brickomancer.utils.subprocess_utils import run_ldview


def main() -> int:
    grid = np.ones((4, 3, 4), dtype=bool)  # 3 layers -> several steps -> multi-page PDF
    placements = brick_packer.pack(grid, color_id=15)
    print(f"packed {len(placements)} bricks from a 4x3x4 grid")

    tmp = tempfile.mkdtemp(prefix="step7_render_")
    ldr = os.path.join(tmp, "suggestion_0.ldr")
    write_ldr(placements, ldr, tier_name="standard")
    ldr_text = open(ldr, encoding="utf-8").read()
    assert "COVER_PAGE" not in ldr_text, "FAIL: writer emitted COVER_PAGE"
    assert "0 !LPUB INSERT BOM" in ldr_text, "FAIL: no BOM in .ldr"
    print(f"wrote {ldr} ({os.path.getsize(ldr)} bytes); BOM present, no COVER_PAGE")

    # --- LDView preview PNG ---
    png = os.path.join(tmp, "preview.png")
    run_ldview(ldr, png)
    png_size = os.path.getsize(png)
    assert png_size > 0, "FAIL: LDView produced an empty PNG"
    print(f"LDView PNG OK: {png} ({png_size} bytes)")

    # --- LPub3D instruction PDF (would CRASH if COVER_PAGE were present) ---
    pdf = generate_pdf(ldr, tmp)
    pdf_size = os.path.getsize(pdf)
    raw = open(pdf, "rb").read()
    page_count = len(re.findall(rb"/Type\s*/Page[^s]", raw))  # /Page objects, not /Pages
    assert pdf_size > 0, "FAIL: LPub3D produced an empty PDF (likely a crash)"
    print(f"LPub3D PDF OK: {pdf} ({pdf_size} bytes, ~{page_count} page objects)")
    if page_count < 2:
        print(f"WARN: expected a multi-page PDF, found ~{page_count} page object(s)")

    print("\nSTEP7_RENDER_UAT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
