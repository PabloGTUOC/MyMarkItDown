"""Tests for validation logic and magic-byte sniffing."""

from pathlib import Path

import pytest

from app.validation import (
    IMAGE_EXTENSIONS,
    SUPPORTED_EXTENSIONS,
    ValidationError,
    validate_file,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_allowed_extensions_pass() -> None:
    """Ensure all supported extensions pass validation with appropriate headers."""
    for ext in SUPPORTED_EXTENSIONS:
        if ext in (".docx", ".xlsx", ".pptx", ".epub"):
            header = b"PK\x03\x04"
        elif ext == ".pdf":
            header = b"%PDF-1.4"
        else:
            header = b"plain text header"

        validated_ext = validate_file(f"doc{ext}", header)
        assert validated_ext == ext


def test_unsupported_extension_rejected() -> None:
    """Ensure unsupported extensions raise unsupported_type ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        validate_file("archive.tar", b"some bytes")
    assert exc_info.value.code == "unsupported_type"

    with pytest.raises(ValidationError) as exc_info:
        validate_file("program.exe", b"MZ")
    assert exc_info.value.code == "unsupported_type"


def test_zip_extension_rejected() -> None:
    """Ensure .zip archives are rejected in v1."""
    with pytest.raises(ValidationError) as exc_info:
        validate_file("archive.zip", b"PK\x03\x04")
    assert exc_info.value.code == "unsupported_type"


def test_image_extensions_rejected() -> None:
    """Ensure image extensions are rejected with code image_rejected."""
    for ext in IMAGE_EXTENSIONS:
        with pytest.raises(ValidationError) as exc_info:
            validate_file(f"image{ext}", b"some bytes")
        assert exc_info.value.code == "image_rejected"


def test_renamed_jpeg_rejected() -> None:
    """Ensure JPEG bytes disguised as .pdf are caught and rejected."""
    fake_pdf = FIXTURES_DIR / "fake.pdf"
    content = fake_pdf.read_bytes()
    with pytest.raises(ValidationError) as exc_info:
        validate_file("fake.pdf", content)
    assert exc_info.value.code == "image_rejected"


def test_invalid_pdf_header_rejected() -> None:
    """Ensure a file with .pdf extension lacking %PDF header is rejected."""
    with pytest.raises(ValidationError) as exc_info:
        validate_file("corrupt.pdf", b"NOT_A_PDF_CONTENT")
    assert exc_info.value.code == "unsupported_type"


def test_invalid_zip_container_rejected() -> None:
    """Ensure a file with .docx extension lacking zip container is rejected."""
    with pytest.raises(ValidationError) as exc_info:
        validate_file("corrupt.docx", b"NOT_A_ZIP_CONTAINER")
    assert exc_info.value.code == "unsupported_type"


def test_missing_filename() -> None:
    """Ensure empty or missing filenames are rejected."""
    with pytest.raises(ValidationError) as exc_info:
        validate_file("", b"content")
    assert exc_info.value.code == "unsupported_type"

    with pytest.raises(ValidationError) as exc_info:
        validate_file("no_extension", b"content")
    assert exc_info.value.code == "unsupported_type"
