"""Download Rebrickable CSVs and LDConfig.ldr to data/."""

import gzip
import urllib.request
from pathlib import Path

# Repo root is one level above scripts/
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_REBRICKABLE = REPO_ROOT / "data" / "rebrickable"
DATA_LDRAW = REPO_ROOT / "data" / "ldraw"

# Minimal dimensions.csv — single source of truth for brick LDU sizes.
# Columns: part_num,x_size,y_size,z_size (LDU units)
DIMENSIONS_CSV_CONTENT = """\
part_num,x_size,y_size,z_size
3001,40,24,80
3002,40,24,60
3003,40,24,40
3004,20,24,40
3005,20,24,20
3010,20,24,80
3622,20,24,60
"""

# (url, dest_path, gunzip)
DOWNLOADS: list[tuple[str, Path, bool]] = [
    (
        "https://cdn.rebrickable.com/media/downloads/colors.csv.gz",
        DATA_REBRICKABLE / "colors.csv",
        True,
    ),
    (
        "https://cdn.rebrickable.com/media/downloads/parts.csv.gz",
        DATA_REBRICKABLE / "parts.csv",
        True,
    ),
    (
        "https://cdn.rebrickable.com/media/downloads/inventory_parts.csv.gz",
        DATA_REBRICKABLE / "inventory_parts.csv",
        True,
    ),
    # LDConfig.ldr is bundled in data/ldraw/ and committed to the repo.
    # The ldraw.org URL returns 403 as of 2026-06; skip network download if
    # already present.  If missing, try the LPub3D portable install as a local
    # fallback before hitting the network.
]

_LDCONFIG_LOCAL_FALLBACKS: list[Path] = [
    Path(r"C:\Tools\LPub3D\extras\LDConfig.ldr"),
    Path(r"C:\Program Files\LPub3D\extras\LDConfig.ldr"),
    Path(r"C:\Program Files (x86)\LPub3D\extras\LDConfig.ldr"),
]


def _download_file(url: str, dest: Path, gunzip: bool) -> None:
    """Download *url* to *dest*, decompressing gzip if requested."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {dest.name}...")
    with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310
        raw = response.read()
    if gunzip:
        raw = gzip.decompress(raw)
    dest.write_bytes(raw)
    print(f"  -> saved to {dest}")


def _write_dimensions_csv() -> None:
    """Write the static dimensions.csv (no download needed)."""
    dest = DATA_LDRAW / "dimensions.csv"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        print(f"Skipping dimensions.csv — already present at {dest}")
        return
    print("Writing dimensions.csv (static)...")
    dest.write_text(DIMENSIONS_CSV_CONTENT, encoding="utf-8")
    print(f"  -> saved to {dest}")


def _ensure_ldconfig(dest: Path) -> None:
    """Ensure LDConfig.ldr is present without hitting the network if possible."""
    if dest.exists():
        print(f"Skipping LDConfig.ldr — already present at {dest}")
        return
    for fallback in _LDCONFIG_LOCAL_FALLBACKS:
        if fallback.exists():
            import shutil
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(fallback, dest)
            print(f"  -> copied LDConfig.ldr from {fallback}")
            return
    # Last resort: try network (may return 403)
    try:
        _download_file("https://library.ldraw.org/library/official/LDConfig.ldr", dest, False)
    except Exception as exc:
        print(
            f"ERROR: could not obtain LDConfig.ldr ({exc}). "
            "Copy it manually from your LPub3D install's extras/ folder."
        )


def main() -> None:
    for url, dest, gunzip in DOWNLOADS:
        try:
            _download_file(url, dest, gunzip)
        except Exception as exc:
            print(f"ERROR downloading {dest.name}: {exc}")
    _ensure_ldconfig(DATA_LDRAW / "LDConfig.ldr")
    _write_dimensions_csv()
    print("Done.")


if __name__ == "__main__":
    main()
