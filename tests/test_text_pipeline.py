"""Tests for text_pipeline — llama-server extraction, primitive mesh building, voxelization.

All httpx calls are mocked — no real llama-server is needed.
"""

import json
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import trimesh

import brickomancer.services.text_pipeline as tp
from brickomancer.models.brick import ShapeParams
from brickomancer.services.text_pipeline import ServiceUnavailableError

# ---------------------------------------------------------------------------
# Helpers — fake llama-server response builder
# ---------------------------------------------------------------------------


def _make_llama_response(shape_dict: dict) -> dict:
    """Build a minimal llama-server JSON response containing *shape_dict* as content."""
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": json.dumps(shape_dict),
                }
            }
        ]
    }


def _make_llama_response_fenced(shape_dict: dict) -> dict:
    """Like _make_llama_response but wraps the JSON in markdown code fences."""
    content = "```json\n" + json.dumps(shape_dict) + "\n```"
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def cake_shape() -> dict:
    """Typical ShapeParams dict for 'big blue birthday cake'."""
    return {
        "archetype": "cylinder",
        "height_studs": 8,
        "radius_studs": 6,
        "width_studs": 0,
        "depth_studs": 0,
        "colors": ["blue", "white"],
    }


# ---------------------------------------------------------------------------
# Unit tests — _extract_json_text
# ---------------------------------------------------------------------------


def test_extract_json_text_plain() -> None:
    """_extract_json_text returns the original string if no fences present."""
    raw = '{"archetype": "box"}'
    assert tp._extract_json_text(raw) == '{"archetype": "box"}'


def test_extract_json_text_with_json_fence() -> None:
    """_extract_json_text strips ```json ... ``` fences."""
    raw = '```json\n{"archetype": "box"}\n```'
    assert tp._extract_json_text(raw) == '{"archetype": "box"}'


def test_extract_json_text_with_plain_fence() -> None:
    """_extract_json_text strips ``` ... ``` fences without language tag."""
    raw = '```\n{"archetype": "cylinder"}\n```'
    assert tp._extract_json_text(raw) == '{"archetype": "cylinder"}'


# ---------------------------------------------------------------------------
# Unit tests — _parse_shape_params
# ---------------------------------------------------------------------------


def test_parse_shape_params_valid() -> None:
    """_parse_shape_params parses a complete JSON string correctly."""
    data = {
        "archetype": "cylinder",
        "height_studs": 10,
        "radius_studs": 5,
        "width_studs": 0,
        "depth_studs": 0,
        "colors": ["red", "white"],
    }
    params = tp._parse_shape_params(json.dumps(data))
    assert params.archetype == "cylinder"
    assert params.height_studs == 10
    assert params.radius_studs == 5
    assert params.colors == ["red", "white"]


def test_parse_shape_params_unknown_archetype_falls_back_to_box() -> None:
    """_parse_shape_params replaces unknown archetypes with 'box'."""
    data = {"archetype": "pyramid", "height_studs": 8}
    params = tp._parse_shape_params(json.dumps(data))
    assert params.archetype == "box"


def test_parse_shape_params_defaults_for_missing_keys() -> None:
    """_parse_shape_params uses safe defaults when optional keys are missing."""
    params = tp._parse_shape_params('{"archetype": "box"}')
    assert params.height_studs >= 1
    assert params.radius_studs == 0
    assert params.colors == []


def test_parse_shape_params_negative_height_clamped_to_one() -> None:
    """_parse_shape_params clamps height_studs to at least 1."""
    data = {"archetype": "box", "height_studs": -5}
    params = tp._parse_shape_params(json.dumps(data))
    assert params.height_studs == 1


# ---------------------------------------------------------------------------
# Unit tests — _build_mesh (each archetype)
# ---------------------------------------------------------------------------


def test_build_mesh_cylinder() -> None:
    """_build_mesh returns a Trimesh for the cylinder archetype."""
    params = ShapeParams(archetype="cylinder", height_studs=8, radius_studs=4)
    mesh = tp._build_mesh(params)
    assert isinstance(mesh, trimesh.Trimesh)
    assert mesh.is_volume or mesh.vertices.shape[0] > 0


def test_build_mesh_box() -> None:
    """_build_mesh returns a Trimesh for the box archetype."""
    params = ShapeParams(archetype="box", height_studs=6, width_studs=4, depth_studs=4)
    mesh = tp._build_mesh(params)
    assert isinstance(mesh, trimesh.Trimesh)


def test_build_mesh_sphere() -> None:
    """_build_mesh returns a Trimesh for the sphere archetype."""
    params = ShapeParams(archetype="sphere", height_studs=6, radius_studs=3)
    mesh = tp._build_mesh(params)
    assert isinstance(mesh, trimesh.Trimesh)


def test_build_mesh_cone() -> None:
    """_build_mesh returns a Trimesh for the cone archetype."""
    params = ShapeParams(archetype="cone", height_studs=8, radius_studs=4)
    mesh = tp._build_mesh(params)
    assert isinstance(mesh, trimesh.Trimesh)


def test_build_mesh_house() -> None:
    """_build_mesh returns a Trimesh for the house archetype (body + roof)."""
    params = ShapeParams(archetype="house", height_studs=10, width_studs=6, depth_studs=6)
    mesh = tp._build_mesh(params)
    assert isinstance(mesh, trimesh.Trimesh)
    # House should be taller than the body alone (body is 60% height)
    body_height = 10 * 0.6 * 0.0096
    y_extent = float(mesh.bounds[1][1] - mesh.bounds[0][1])
    assert y_extent > body_height, f"House mesh Y extent {y_extent} <= body height {body_height}"


def test_build_mesh_compound() -> None:
    """_build_mesh returns a Trimesh for the compound archetype (falls back to box)."""
    params = ShapeParams(
        archetype="compound", height_studs=8, radius_studs=3, width_studs=5, depth_studs=4
    )
    mesh = tp._build_mesh(params)
    assert isinstance(mesh, trimesh.Trimesh)


def test_build_mesh_default_archetype() -> None:
    """_build_mesh falls through to box for an unrecognised archetype string."""
    params = ShapeParams(archetype="unknown", height_studs=6, width_studs=4, depth_studs=4)
    mesh = tp._build_mesh(params)
    assert isinstance(mesh, trimesh.Trimesh)


# ---------------------------------------------------------------------------
# Unit tests — _voxelize
# ---------------------------------------------------------------------------


def test_voxelize_returns_bool_array() -> None:
    """_voxelize returns a numpy bool array with 3 dimensions."""
    mesh = trimesh.creation.box(extents=[0.05, 0.05, 0.05])
    result = tp._voxelize(mesh)
    assert isinstance(result, np.ndarray)
    assert result.dtype == bool
    assert result.ndim == 3


def test_voxelize_non_empty() -> None:
    """_voxelize produces at least one True voxel for a solid mesh."""
    mesh = trimesh.creation.box(extents=[0.1, 0.1, 0.1])
    result = tp._voxelize(mesh)
    assert result.any(), "Expected at least one filled voxel"


# ---------------------------------------------------------------------------
# Unit tests — parse_shape (mocked httpx)
# ---------------------------------------------------------------------------


def test_parse_shape_returns_shapeparams(cake_shape: dict) -> None:
    """parse_shape returns a ShapeParams when llama-server responds correctly."""
    fake_response = MagicMock()
    fake_response.json.return_value = _make_llama_response(cake_shape)
    fake_response.raise_for_status = MagicMock()

    with patch("brickomancer.services.text_pipeline.httpx.post", return_value=fake_response):
        result = tp.parse_shape("big blue birthday cake")

    assert isinstance(result, ShapeParams)
    assert result.archetype == "cylinder"
    assert result.height_studs == 8
    assert result.radius_studs == 6
    assert "blue" in result.colors


def test_parse_shape_handles_fenced_json(cake_shape: dict) -> None:
    """parse_shape correctly strips markdown code fences from the model output."""
    fake_response = MagicMock()
    fake_response.json.return_value = _make_llama_response_fenced(cake_shape)
    fake_response.raise_for_status = MagicMock()

    with patch("brickomancer.services.text_pipeline.httpx.post", return_value=fake_response):
        result = tp.parse_shape("birthday cake")

    assert result.archetype == "cylinder"


def test_parse_shape_raises_service_unavailable_on_connect_error() -> None:
    """parse_shape raises ServiceUnavailableError when llama-server is unreachable."""
    import httpx as _httpx

    with patch(
        "brickomancer.services.text_pipeline.httpx.post",
        side_effect=_httpx.ConnectError("Connection refused"),
    ):
        with pytest.raises(ServiceUnavailableError, match="llama-server is unreachable"):
            tp.parse_shape("a red castle")


def test_parse_shape_raises_service_unavailable_on_timeout() -> None:
    """parse_shape raises ServiceUnavailableError on httpx.TimeoutException."""
    import httpx as _httpx

    with patch(
        "brickomancer.services.text_pipeline.httpx.post",
        side_effect=_httpx.TimeoutException("timed out"),
    ):
        with pytest.raises(ServiceUnavailableError):
            tp.parse_shape("a tall skyscraper")


# ---------------------------------------------------------------------------
# Integration-style tests — run() with mocked httpx
# ---------------------------------------------------------------------------


def test_run_returns_bool_array(cake_shape: dict) -> None:
    """run('big blue birthday cake') with mocked httpx returns a numpy bool array."""
    fake_response = MagicMock()
    fake_response.json.return_value = _make_llama_response(cake_shape)
    fake_response.raise_for_status = MagicMock()

    with patch("brickomancer.services.text_pipeline.httpx.post", return_value=fake_response):
        result = tp.run("big blue birthday cake")

    assert isinstance(result, np.ndarray)
    assert result.dtype == bool
    assert result.ndim == 3
    assert result.any(), "Expected at least one filled voxel"


def test_run_raises_service_unavailable_when_server_unreachable() -> None:
    """run() raises ServiceUnavailableError when llama-server is unreachable."""
    import httpx as _httpx

    with patch(
        "brickomancer.services.text_pipeline.httpx.post",
        side_effect=_httpx.ConnectError("refused"),
    ):
        with pytest.raises(ServiceUnavailableError):
            tp.run("a green dragon")


def test_run_box_archetype_returns_valid_array() -> None:
    """run() produces a valid bool array for a box archetype response."""
    shape = {
        "archetype": "box",
        "height_studs": 6,
        "radius_studs": 0,
        "width_studs": 5,
        "depth_studs": 4,
        "colors": ["red"],
    }
    fake_response = MagicMock()
    fake_response.json.return_value = _make_llama_response(shape)
    fake_response.raise_for_status = MagicMock()

    with patch("brickomancer.services.text_pipeline.httpx.post", return_value=fake_response):
        result = tp.run("a red box")

    assert isinstance(result, np.ndarray)
    assert result.dtype == bool


def test_run_house_archetype_returns_valid_array() -> None:
    """run() produces a valid bool array for the house archetype."""
    shape = {
        "archetype": "house",
        "height_studs": 10,
        "radius_studs": 0,
        "width_studs": 8,
        "depth_studs": 6,
        "colors": ["tan", "red"],
    }
    fake_response = MagicMock()
    fake_response.json.return_value = _make_llama_response(shape)
    fake_response.raise_for_status = MagicMock()

    with patch("brickomancer.services.text_pipeline.httpx.post", return_value=fake_response):
        result = tp.run("a house")

    assert isinstance(result, np.ndarray)
    assert result.dtype == bool
    assert result.any()


def test_run_sphere_archetype_returns_valid_array() -> None:
    """run() produces a valid bool array for the sphere archetype."""
    shape = {
        "archetype": "sphere",
        "height_studs": 8,
        "radius_studs": 4,
        "width_studs": 0,
        "depth_studs": 0,
        "colors": ["orange"],
    }
    fake_response = MagicMock()
    fake_response.json.return_value = _make_llama_response(shape)
    fake_response.raise_for_status = MagicMock()

    with patch("brickomancer.services.text_pipeline.httpx.post", return_value=fake_response):
        result = tp.run("an orange ball")

    assert isinstance(result, np.ndarray)
    assert result.dtype == bool


# ---------------------------------------------------------------------------
# New tests addressing review findings
# ---------------------------------------------------------------------------


def test_call_llama_raises_service_unavailable_on_http_error() -> None:
    """_call_llama raises ServiceUnavailableError when raise_for_status() raises HTTPStatusError."""
    import httpx as _httpx

    fake_request = MagicMock()
    fake_response = MagicMock()
    fake_response.status_code = 500
    http_error = _httpx.HTTPStatusError(
        "Server error", request=fake_request, response=fake_response
    )
    fake_response.raise_for_status.side_effect = http_error

    with patch("brickomancer.services.text_pipeline.httpx.post", return_value=fake_response):
        with pytest.raises(ServiceUnavailableError, match="llama-server returned HTTP 500"):
            tp._call_llama("a red castle")


def test_parse_shape_raises_value_error_on_malformed_response() -> None:
    """parse_shape raises ValueError when llama response is missing 'choices' key."""
    fake_response = MagicMock()
    fake_response.json.return_value = {"unexpected": "keys"}
    fake_response.raise_for_status = MagicMock()

    with patch("brickomancer.services.text_pipeline.httpx.post", return_value=fake_response):
        with pytest.raises(ValueError, match="Unexpected llama-server response format"):
            tp.parse_shape("a red castle")


def test_parse_shape_params_non_numeric_height_falls_back_to_default() -> None:
    """_parse_shape_params handles non-numeric height_studs by using the default."""
    data = {"archetype": "box", "height_studs": "ten"}
    params = tp._parse_shape_params(json.dumps(data))
    assert params.height_studs >= 1


def test_parse_shape_params_negative_radius_clamped_to_zero() -> None:
    """_parse_shape_params clamps negative radius_studs to 0."""
    data = {"archetype": "cylinder", "height_studs": 5, "radius_studs": -3}
    params = tp._parse_shape_params(json.dumps(data))
    assert params.radius_studs == 0
