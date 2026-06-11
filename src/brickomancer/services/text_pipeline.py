"""Text pipeline — Llama shape extraction and primitive mesh voxelization.

Sends a text description to llama-server (llama.cpp OpenAI-compatible API),
extracts structured ShapeParams, builds a trimesh primitive, and voxelizes it.
"""

import json
import re

import httpx
import numpy as np
import trimesh
import trimesh.transformations as tf

from brickomancer.models.brick import ShapeParams

# ---------------------------------------------------------------------------
# Constants — single source of truth within this module
# ---------------------------------------------------------------------------

# 1 LEGO stud = 8 LDU = 9.6 mm = 0.0096 m (same value as image_pipeline;
# each module owns its constant to avoid cross-module coupling).
_STUD_METERS: float = 0.0096

_LLAMA_SERVER_URL: str = "http://localhost:8080/v1/chat/completions"

_EXTRACTION_SYSTEM_PROMPT: str = (
    "You are a JSON extraction assistant. "
    "Output ONLY a single JSON object with these keys: "
    "archetype (one of: cylinder, box, sphere, cone, house, compound), "
    "height_studs (int, 1-50), "
    "radius_studs (int, 0-30), "
    "width_studs (int, 0-50), "
    "depth_studs (int, 0-50), "
    "colors (list of color name strings). "
    "No markdown, no explanation, no extra text — just the JSON object."
)


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------


class ServiceUnavailableError(Exception):
    """Raised when llama-server is unreachable or times out."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _call_llama(description: str) -> dict:
    """Call llama-server and return the parsed JSON response body as a dict.

    Raises:
        ServiceUnavailableError: If the server is unreachable or times out.
    """
    payload = {
        "model": "local",
        "messages": [
            {"role": "system", "content": _EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": description},
        ],
        "temperature": 0.0,
        "max_tokens": 256,
    }
    try:
        response = httpx.post(_LLAMA_SERVER_URL, json=payload, timeout=30.0)
        response.raise_for_status()
        return response.json()  # type: ignore[no-any-return]
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        raise ServiceUnavailableError(
            f"llama-server is unreachable at {_LLAMA_SERVER_URL}: {exc}"
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise ServiceUnavailableError(
            f"llama-server returned HTTP {exc.response.status_code}"
        ) from exc


def _extract_json_text(content: str) -> str:
    """Strip markdown code fences (```json ... ```) from *content* if present."""
    # Match optional language tag after opening fence
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
    if fenced:
        return fenced.group(1).strip()
    return content.strip()


def _safe_int(value: object, default: int) -> int:
    """Convert *value* to int, returning *default* on any conversion failure.

    Handles strings like "10", "10.5", bare ints, and floats.
    """
    try:
        return int(float(str(value)))
    except (ValueError, TypeError):
        return default


def _parse_shape_params(raw_json: str) -> ShapeParams:
    """Parse *raw_json* into a ShapeParams, applying safe defaults for missing keys.

    Raises:
        ValueError: If *raw_json* is not valid JSON or has unexpected structure.
    """
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to parse llama output as JSON: {raw_json!r}") from exc
    archetype = str(data.get("archetype", "box")).lower()
    valid_archetypes = {"cylinder", "box", "sphere", "cone", "house", "compound"}
    if archetype not in valid_archetypes:
        archetype = "box"
    return ShapeParams(
        archetype=archetype,
        height_studs=max(1, _safe_int(data.get("height_studs", 10), 10)),
        radius_studs=max(0, _safe_int(data.get("radius_studs", 0), 0)),
        width_studs=max(1, _safe_int(data.get("width_studs", 0), 1)),
        depth_studs=max(1, _safe_int(data.get("depth_studs", 0), 1)),
        colors=[str(c) for c in data.get("colors", [])],
    )


def _ensure_positive(value: int, fallback: int) -> int:
    """Return *value* if positive, else *fallback*."""
    return value if value > 0 else fallback


def _build_mesh(params: ShapeParams) -> trimesh.Trimesh:
    """Build a trimesh primitive from *params*.

    Archetype dispatch:
    - cylinder  — trimesh.creation.cylinder
    - box       — trimesh.creation.box
    - sphere    — trimesh.creation.icosphere
    - cone      — trimesh.creation.cone
    - house     — box body (60% height) + cone roof (40%) concatenated
    - compound  — box using max(radius, width, depth) for lateral dims
    """
    h = params.height_studs
    r = _ensure_positive(params.radius_studs, h // 2 or 1)
    w = _ensure_positive(params.width_studs, h)
    d = _ensure_positive(params.depth_studs, h)

    archetype = params.archetype

    if archetype == "cylinder":
        return trimesh.creation.cylinder(
            radius=r * 0.008,
            height=h * _STUD_METERS,
        )

    if archetype == "sphere":
        return trimesh.creation.icosphere(radius=r * 0.008)

    if archetype == "cone":
        return trimesh.creation.cone(
            radius=r * 0.008,
            height=h * _STUD_METERS,
        )

    if archetype == "house":
        body_height = h * 0.6 * _STUD_METERS
        roof_height = h * 0.4 * _STUD_METERS
        roof_radius = w * 0.008 / 2.0

        body = trimesh.creation.box(extents=[w * 0.008, body_height, d * 0.008])
        # Center the body at origin; its top face is at body_height/2

        roof = trimesh.creation.cone(radius=roof_radius, height=roof_height)
        # trimesh.creation.cone places base at z=0, apex at z=height (Z-up).
        # Rotate -90° around X so the cone's height axis aligns with +Y (Y-up).
        rotation = tf.rotation_matrix(-np.pi / 2, [1, 0, 0])
        roof.apply_transform(rotation)
        # After rotation: base centre is at y=0, apex at y=roof_height.
        # Translate so the base (y=0 in cone-local) sits on top of the body (y=body_height/2).
        roof.apply_translation([0.0, body_height / 2.0, 0.0])

        combined: trimesh.Trimesh = trimesh.util.concatenate([body, roof])
        return combined

    if archetype == "compound":
        lateral = max(r, w, d)
        lateral = _ensure_positive(lateral, h)
        return trimesh.creation.box(extents=[lateral * 0.008, h * _STUD_METERS, lateral * 0.008])

    # Default / box
    return trimesh.creation.box(extents=[w * 0.008, h * _STUD_METERS, d * 0.008])


def _voxelize(mesh: trimesh.Trimesh, pitch: float = _STUD_METERS) -> np.ndarray:
    """Voxelize *mesh* and return a (X, Y, Z) bool numpy array.

    Uses method='subdivide' to avoid the optional rtree dependency.
    """
    voxels = mesh.voxelized(pitch=pitch, method="subdivide").fill()
    return np.asarray(voxels.matrix, dtype=bool)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_shape(description: str) -> ShapeParams:
    """Send *description* to llama-server and return a ShapeParams.

    Args:
        description: Natural language description of the object.

    Returns:
        ShapeParams with archetype, dimensions, and colors.

    Raises:
        ServiceUnavailableError: If llama-server is unreachable.
    """
    llama_response = _call_llama(description)
    # Extract the assistant's message content
    try:
        content: str = llama_response["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise ValueError(
            f"Unexpected llama-server response format: {list(llama_response.keys())}"
        ) from exc
    raw_json = _extract_json_text(content)
    return _parse_shape_params(raw_json)


def build_primitive_mesh(params: ShapeParams) -> trimesh.Trimesh:
    """Build a trimesh primitive from *params*.

    Args:
        params: ShapeParams with archetype and dimension fields.

    Returns:
        trimesh.Trimesh primitive mesh.
    """
    return _build_mesh(params)


def run(description: str) -> np.ndarray:
    """Full text pipeline: parse_shape + build_primitive_mesh + voxelization.

    Args:
        description: Natural language description of the object.

    Returns:
        numpy.ndarray[bool] of shape (X, Y, Z).

    Raises:
        ServiceUnavailableError: If llama-server is unreachable.
    """
    params = parse_shape(description)
    mesh = _build_mesh(params)
    return _voxelize(mesh)
