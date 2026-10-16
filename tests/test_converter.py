"""Tests for converter service wrapper."""

import asyncio
import importlib.metadata
import os
import time
from pathlib import Path

import pytest

from app.converter import (
    CONVERTER_VERSION,
    ConversionError,
    ConverterService,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_converter_version() -> None:
    """Ensure converter version matches installed markitdown version."""
    expected_version = importlib.metadata.version("markitdown")
    assert CONVERTER_VERSION == expected_version


def test_convert_supported_fixtures() -> None:
    """Ensure each generated fixture converts successfully to Markdown."""
    converter = ConverterService()

    # PDF
    with open(FIXTURES_DIR / "sample.pdf", "rb") as f:
        pdf_out = asyncio.run(converter.convert_stream(f, ".pdf"))
    assert "Hello PDF Document" in pdf_out

    # DOCX
    with open(FIXTURES_DIR / "sample.docx", "rb") as f:
        docx_out = asyncio.run(converter.convert_stream(f, ".docx"))
    assert "Hello DOCX Document" in docx_out

    # XLSX
    with open(FIXTURES_DIR / "sample.xlsx", "rb") as f:
        xlsx_out = asyncio.run(converter.convert_stream(f, ".xlsx"))
    assert "Alice" in xlsx_out and "100" in xlsx_out

    # PPTX
    with open(FIXTURES_DIR / "sample.pptx", "rb") as f:
        pptx_out = asyncio.run(converter.convert_stream(f, ".pptx"))
    assert "Hello Presentation" in pptx_out

    # CSV
    with open(FIXTURES_DIR / "sample.csv", "rb") as f:
        csv_out = asyncio.run(converter.convert_stream(f, ".csv"))
    assert "Alice" in csv_out and "Engineer" in csv_out

    # HTML
    with open(FIXTURES_DIR / "sample.html", "rb") as f:
        html_out = asyncio.run(converter.convert_stream(f, ".html"))
    assert "Sample Title" in html_out


def test_conversion_timeout() -> None:
    """Ensure conversion times out and raises 504 ConversionError."""
    # Custom slow function to simulate timeout
    converter = ConverterService(timeout_s=0.01)

    def slow_convert(*_args: object, **_kwargs: object) -> str:
        time.sleep(0.05)
        return "done"

    converter._sync_convert_stream = slow_convert  # type: ignore[assignment]

    with (
        open(FIXTURES_DIR / "sample.csv", "rb") as f,
        pytest.raises(ConversionError) as exc_info,
    ):
        asyncio.run(converter.convert_stream(f, ".csv"))

    assert exc_info.value.code == "timeout"
    assert exc_info.value.status_code == 504


def test_convert_stream_cleanup() -> None:
    """Ensure convert_stream leaves no temporary files behind in /tmp."""
    converter = ConverterService()

    csv_bytes = b"col1,col2\nval1,val2\n"
    import io

    stream = io.BytesIO(csv_bytes)

    # Check /tmp before
    initial_tmp_files = {f for f in os.listdir("/tmp") if f.startswith("mdbridge_")}

    result = asyncio.run(converter.convert_stream(stream, ".csv"))
    assert "val1" in result

    # Check /tmp after
    current_tmp_files = {f for f in os.listdir("/tmp") if f.startswith("mdbridge_")}
    assert current_tmp_files == initial_tmp_files
