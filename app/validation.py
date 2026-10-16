"""File type validation and magic-byte sniffing."""

from pathlib import Path
from typing import Final

import filetype

SUPPORTED_EXTENSIONS: Final[tuple[str, ...]] = (
    ".pdf",
    ".docx",
    ".pptx",
    ".xlsx",
    ".xls",
    ".csv",
    ".json",
    ".xml",
    ".txt",
    ".md",
    ".html",
    ".htm",
    ".epub",
    ".msg",
)

IMAGE_EXTENSIONS: Final[tuple[str, ...]] = (
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".bmp",
    ".tiff",
    ".tif",
    ".heic",
    ".heif",
    ".ico",
    ".svg",
)

ZIP_CONTAINER_EXTENSIONS: Final[tuple[str, ...]] = (
    ".docx",
    ".pptx",
    ".xlsx",
    ".epub",
)


class ValidationError(Exception):
    """Validation exception with error code and detail."""

    def __init__(self, code: str, detail: str, status_code: int = 415) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status_code = status_code


def validate_file(filename: str, header_bytes: bytes) -> str:
    """Validate filename extension and magic bytes.

    Returns the normalized extension (e.g. '.pdf').
    Raises ValidationError if invalid.
    """
    if not filename:
        raise ValidationError(code="unsupported_type", detail="Filename is required.")

    ext = Path(filename).suffix.lower()
    if not ext:
        raise ValidationError(
            code="unsupported_type",
            detail=f"File '{filename}' has no extension.",
        )

    # 1. Reject images by extension immediately
    if ext in IMAGE_EXTENSIONS:
        raise ValidationError(
            code="image_rejected",
            detail=f"Image files ('{ext}') are not supported.",
        )

    # 2. Reject explicit .zip archives in v1
    if ext == ".zip":
        raise ValidationError(
            code="unsupported_type",
            detail="ZIP archives are not supported in v1.",
        )

    # 3. Check allowed extensions list
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValidationError(
            code="unsupported_type",
            detail=f"Extension '{ext}' is not supported.",
        )

    # 4. Sniff magic bytes if we have content
    if header_bytes:
        kind = filetype.guess(header_bytes)
        if kind is not None:
            mime = kind.mime
            if mime.startswith("image/"):
                raise ValidationError(
                    code="image_rejected",
                    detail=f"File contains image data ({mime}) and is rejected.",
                )
            if mime.startswith(("audio/", "video/")):
                raise ValidationError(
                    code="unsupported_type",
                    detail=f"Audio/video format '{mime}' is not supported.",
                )
            if (
                mime in ("application/zip", "application/x-zip-compressed")
                and ext not in ZIP_CONTAINER_EXTENSIONS
            ):
                raise ValidationError(
                    code="unsupported_type",
                    detail=f"ZIP archive cannot be uploaded as '{ext}'.",
                )

        # 5. Extension-specific container validation
        if (
            ext == ".pdf"
            and not header_bytes.startswith(b"%PDF-")
            and b"%PDF-" not in header_bytes[:1024]
        ):
            raise ValidationError(
                code="unsupported_type",
                detail="File has .pdf extension but does not contain valid PDF header.",
            )

        if ext in ZIP_CONTAINER_EXTENSIONS and not header_bytes.startswith(
            b"PK\x03\x04"
        ):
            raise ValidationError(
                code="unsupported_type",
                detail=f"File has '{ext}' extension but is not a valid zip container.",
            )

    return ext
