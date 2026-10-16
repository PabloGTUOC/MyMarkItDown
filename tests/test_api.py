"""Tests for FastAPI endpoints and API behaviors."""

import asyncio
import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from app.config import Settings, get_settings
from app.converter import CONVERTER_VERSION, ConverterService
from app.main import app

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def client() -> TestClient:
    """Create a TestClient instance."""
    return TestClient(app)


def test_healthz(client: TestClient) -> None:
    """Ensure healthz endpoint returns 200 OK."""
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_formats(client: TestClient) -> None:
    """Ensure /api/formats returns the allowed extensions list."""
    response = client.get("/api/formats")
    assert response.status_code == 200
    formats = response.json()
    assert isinstance(formats, list)
    assert ".pdf" in formats
    assert ".docx" in formats
    assert ".xlsx" in formats
    assert ".csv" in formats
    assert ".zip" not in formats
    assert ".jpg" not in formats


@pytest.mark.parametrize(
    ("filename", "expected_content"),
    [
        ("sample.pdf", "Hello PDF Document"),
        ("sample.docx", "Hello DOCX Document"),
        ("sample.xlsx", "Alice"),
        ("sample.pptx", "Hello Presentation"),
        ("sample.csv", "Alice"),
        ("sample.html", "Sample Title"),
    ],
)
def test_each_supported_type_converts(
    client: TestClient,
    filename: str,
    expected_content: str,
) -> None:
    """Ensure each supported document fixture converts successfully."""
    file_path = FIXTURES_DIR / filename
    with open(file_path, "rb") as f:
        response = client.post(
            "/api/convert",
            files={
                "file": (
                    "sample.pdf" if filename == "sample.pdf" else filename,
                    f,
                    "application/octet-stream",
                )
            },
        )
    assert response.status_code == 200, f"Failed for {filename}: {response.text}"
    assert expected_content in response.text
    # Default frontmatter is enabled
    assert f"source_file: {filename}" in response.text
    assert f"converter: markitdown {CONVERTER_VERSION}" in response.text


def test_image_rejected(client: TestClient) -> None:
    """Ensure image files (photo.jpg) are rejected with 415 and image_rejected code."""
    file_path = FIXTURES_DIR / "photo.jpg"
    with open(file_path, "rb") as f:
        response = client.post(
            "/api/convert",
            files={"file": ("photo.jpg", f, "image/jpeg")},
        )
    assert response.status_code == 415
    data = response.json()
    assert data["error"] == "image_rejected"


def test_renamed_jpeg_rejected(client: TestClient) -> None:
    """Ensure disguised JPEG (fake.pdf) is rejected via magic byte sniffing."""
    file_path = FIXTURES_DIR / "fake.pdf"
    with open(file_path, "rb") as f:
        response = client.post(
            "/api/convert",
            files={"file": ("fake.pdf", f, "application/pdf")},
        )
    assert response.status_code == 415
    data = response.json()
    assert data["error"] == "image_rejected"


def test_oversize_rejected_early_via_content_length_header(client: TestClient) -> None:
    """Ensure Content-Length > max_upload_bytes is rejected early by middleware with 413."""
    tiny_settings = Settings(max_upload_mb=1)  # 1 MB = 1,048,576 bytes
    app.dependency_overrides[get_settings] = lambda: tiny_settings
    try:
        # Declare 5 MB in Content-Length header with small payload
        response = client.post(
            "/api/convert",
            headers={"Content-Length": "5242880"},
            content=b"dummy body",
        )
        assert response.status_code == 413
        data = response.json()
        assert data["error"] == "too_large"
        assert "5242880" in data["detail"]
    finally:
        app.dependency_overrides.pop(get_settings, None)


def test_oversize_rejected_via_streaming_check(client: TestClient) -> None:
    """Ensure streaming upload exceeding MAX_UPLOAD_MB is rejected with 413 and too_large code."""
    tiny_settings = Settings(max_upload_mb=0)
    # Patch max_upload_bytes property to 50 bytes
    with patch.object(Settings, "max_upload_bytes", 50):
        app.dependency_overrides[get_settings] = lambda: tiny_settings
        try:
            file_path = FIXTURES_DIR / "sample.pdf"  # 593 bytes > 50 bytes
            with open(file_path, "rb") as f:
                response = client.post(
                    "/api/convert",
                    files={"file": ("sample.pdf", f, "application/pdf")},
                )
            assert response.status_code == 413
            data = response.json()
            assert data["error"] == "too_large"
        finally:
            app.dependency_overrides.pop(get_settings, None)


def test_temp_dir_empty_after_requests(client: TestClient) -> None:
    """Ensure no leftover temporary files in /tmp after successful and failed requests."""
    initial_files = {f for f in os.listdir("/tmp") if f.startswith("mdbridge_")}

    # 1. Successful request
    with open(FIXTURES_DIR / "sample.csv", "rb") as f:
        resp1 = client.post(
            "/api/convert",
            files={"file": ("sample.csv", f, "text/csv")},
        )
    assert resp1.status_code == 200

    # 2. Failed request (image rejected)
    with open(FIXTURES_DIR / "photo.jpg", "rb") as f:
        resp2 = client.post(
            "/api/convert",
            files={"file": ("photo.jpg", f, "image/jpeg")},
        )
    assert resp2.status_code == 415

    # 3. Failed request (renamed jpeg)
    with open(FIXTURES_DIR / "fake.pdf", "rb") as f:
        resp3 = client.post(
            "/api/convert",
            files={"file": ("fake.pdf", f, "application/pdf")},
        )
    assert resp3.status_code == 415

    after_files = {f for f in os.listdir("/tmp") if f.startswith("mdbridge_")}
    assert after_files == initial_files


def test_missing_or_invalid_content_length_returns_411(client: TestClient) -> None:
    """Ensure missing or non-integer Content-Length returns 411 length_required."""

    # Chunked / streaming request with no Content-Length
    def chunk_gen():
        yield b"chunked data"

    resp_missing = client.post("/api/convert", content=chunk_gen())
    assert resp_missing.status_code == 411
    data_missing = resp_missing.json()
    assert data_missing["error"] == "length_required"

    # Non-integer Content-Length
    resp_invalid = client.post(
        "/api/convert",
        headers={"Content-Length": "not-an-int"},
        content=b"some body",
    )
    assert resp_invalid.status_code == 411
    data_invalid = resp_invalid.json()
    assert data_invalid["error"] == "length_required"


def test_timeout_returns_504(client: TestClient) -> None:
    """Ensure conversion timeout returns 504 with timeout error code."""
    original_converter = app.state.converter
    timeout_converter = ConverterService(max_concurrency=1, timeout_s=0.001)
    app.state.converter = timeout_converter
    try:

        def slow_convert(*_args: object, **_kwargs: object) -> str:
            time.sleep(0.05)
            return "done"

        timeout_converter._sync_convert_stream = slow_convert  # type: ignore[assignment]
        with open(FIXTURES_DIR / "sample.csv", "rb") as f:
            response = client.post(
                "/api/convert",
                files={"file": ("sample.csv", f, "text/csv")},
            )
        assert response.status_code == 504
        data = response.json()
        assert data["error"] == "timeout"
    finally:
        app.state.converter = original_converter


def test_max_concurrency_enforced() -> None:
    """Ensure request-level semaphore with MAX_CONCURRENCY=1 enforces no overlap."""
    original_converter = app.state.converter
    original_semaphore = getattr(app.state, "semaphore", None)

    app.state.semaphore = asyncio.Semaphore(1)
    app.state.request_semaphore = app.state.semaphore

    test_converter = ConverterService(max_concurrency=1, timeout_s=10.0)
    app.state.converter = test_converter

    active_count = 0
    max_active_observed = 0
    timing_records: list[tuple[float, float]] = []

    def instrumented_sync_convert(*_args: object, **_kwargs: object) -> str:
        nonlocal active_count, max_active_observed
        start_time = time.perf_counter()
        active_count += 1
        max_active_observed = max(max_active_observed, active_count)
        time.sleep(0.05)
        active_count -= 1
        end_time = time.perf_counter()
        timing_records.append((start_time, end_time))
        return "# Converted"

    test_converter._sync_convert_stream = instrumented_sync_convert  # type: ignore[assignment]

    async def run_concurrent_requests() -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as async_client:
            csv_bytes = (FIXTURES_DIR / "sample.csv").read_bytes()
            resp1, resp2 = await asyncio.gather(
                async_client.post(
                    "/api/convert",
                    files={"file": ("sample1.csv", csv_bytes, "text/csv")},
                ),
                async_client.post(
                    "/api/convert",
                    files={"file": ("sample2.csv", csv_bytes, "text/csv")},
                ),
            )
            assert resp1.status_code == 200
            assert resp2.status_code == 200

    try:
        asyncio.run(run_concurrent_requests())
        assert max_active_observed == 1
        assert len(timing_records) == 2
        # First request finishes before second request starts conversion
        assert timing_records[0][1] <= timing_records[1][0]
    finally:
        app.state.converter = original_converter
        if original_semaphore is not None:
            app.state.semaphore = original_semaphore
            app.state.request_semaphore = original_semaphore


def test_no_named_temporary_file_created(client: TestClient) -> None:
    """Ensure app.main and app.converter do not create NamedTemporaryFile."""
    with patch(
        "tempfile.NamedTemporaryFile",
        side_effect=AssertionError("NamedTemporaryFile must not be created"),
    ):
        with open(FIXTURES_DIR / "sample.csv", "rb") as f:
            response = client.post(
                "/api/convert",
                files={"file": ("sample.csv", f, "text/csv")},
            )
        assert response.status_code == 200
        assert "Alice" in response.text


def test_format_json_response(client: TestClient) -> None:
    """Ensure ?format=json returns structured JSON response."""
    with open(FIXTURES_DIR / "sample.csv", "rb") as f:
        response = client.post(
            "/api/convert?format=json",
            files={"file": ("sample.csv", f, "text/csv")},
        )
    assert response.status_code == 200
    data = response.json()
    assert "markdown" in data
    assert "warnings" in data
    assert data["converter_version"] == CONVERTER_VERSION
    assert "Alice" in data["markdown"]


def test_frontmatter_query_param(client: TestClient) -> None:
    """Ensure ?frontmatter=false disables frontmatter."""
    with open(FIXTURES_DIR / "sample.csv", "rb") as f:
        response = client.post(
            "/api/convert?frontmatter=false",
            files={"file": ("sample.csv", f, "text/csv")},
        )
    assert response.status_code == 200
    assert "source_file:" not in response.text
    assert "converted_at:" not in response.text
    assert "Alice" in response.text


def test_root_serves_index_html(client: TestClient) -> None:
    """Ensure GET / serves index.html."""
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "<title>MyMarkItDown</title>" in response.text


@pytest.mark.parametrize(
    "asset_path",
    [
        "/app.js",
        "/plan.js",
        "/fs-access.js",
        "/zip-fallback.js",
        "/styles.css",
    ],
)
def test_static_assets_served(client: TestClient, asset_path: str) -> None:
    """Ensure static JavaScript and CSS assets are served."""
    response = client.get(asset_path)
    assert response.status_code == 200
    assert len(response.text) > 0
