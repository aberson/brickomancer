"""Image pipeline — rembg background removal, TripoSR mesh generation, voxelization.

Implemented in Step 4.
"""


def run_triposr(image_path: str) -> str:  # type: ignore[empty-body]
    """Remove background and run TripoSR inference to produce a watertight OBJ mesh.

    Args:
        image_path: Path to the input image.

    Returns:
        Path to the generated .obj mesh file.
    """
    ...


def voxelize(mesh_path: str, pitch: float, height_studs: int) -> object:  # type: ignore[empty-body]
    """Load a mesh, scale to height_studs, and voxelize it.

    Args:
        mesh_path: Path to the .obj mesh file.
        pitch: Voxel pitch in LDU (default 8.0).
        height_studs: Target height in LEGO studs.

    Returns:
        numpy.ndarray[bool] of shape (X, Y, Z).
    """
    ...


def run(image_path: str, height_studs: int = 10) -> object:  # type: ignore[empty-body]
    """Full image pipeline: rembg + TripoSR + voxelization.

    Args:
        image_path: Path to the input image.
        height_studs: Target height in LEGO studs.

    Returns:
        numpy.ndarray[bool] of shape (X, height_studs, Z).
    """
    ...
