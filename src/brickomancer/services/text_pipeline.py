"""Text pipeline — Llama shape extraction and primitive mesh voxelization.

Implemented in Step 5.
"""


def parse_shape(description: str) -> object:  # type: ignore[empty-body]
    """Send a description to llama-server and extract structured ShapeParams.

    Args:
        description: Natural language description of the object.

    Returns:
        ShapeParams with archetype, dimensions, and colors.

    Raises:
        ServiceUnavailableError: If llama-server is unreachable.
    """
    ...


def build_primitive_mesh(params: object) -> str:  # type: ignore[empty-body]
    """Build a trimesh primitive from ShapeParams and write to a temp OBJ file.

    Args:
        params: ShapeParams with archetype and dimension fields.

    Returns:
        Path to the generated .obj mesh file.
    """
    ...


def run(description: str, height_studs: int = 10) -> object:  # type: ignore[empty-body]
    """Full text pipeline: parse_shape + build_primitive_mesh + voxelization.

    Args:
        description: Natural language description of the object.
        height_studs: Target height in LEGO studs.

    Returns:
        numpy.ndarray[bool] of shape (X, height_studs, Z).
    """
    ...
