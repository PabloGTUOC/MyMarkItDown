"""FastAPI application entrypoint and routes."""

import asyncio
import hashlib
import logging
import os
import time
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app.config import Settings, get_settings
from app.converter import (
    CONVERTER_VERSION,
    ConversionError,
    ConverterService,
)
from app.frontmatter import add_frontmatter
from app.validation import (
    SUPPORTED_EXTENSIONS,
    ValidationError,
    validate_file,
)

logger = logging.getLogger("mdbridge")


def get_converter(request: Request) -> ConverterService:
    """Retrieve shared ConverterService instance from application state."""
    return request.app.state.converter


def _resolve_settings(request: Request, fallback: Settings) -> Settings:
    """Resolve active settings taking dependency overrides into account."""
    override = request.app.dependency_overrides.get(get_settings)
    if override is not None:
        return override()
    return getattr(request.app.state, "settings", fallback)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    if settings is None:
        settings = get_settings()
    current_settings = settings

    # Configure logging
    logging.basicConfig(
        level=getattr(logging, current_settings.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    app = FastAPI(
        title="MyMarkItDown",
        description="Stateless document to Markdown conversion service",
        root_path=current_settings.root_path,
    )

    # Initialize shared app state
    app.state.settings = current_settings
    app.state.semaphore = asyncio.Semaphore(current_settings.max_concurrency)
    app.state.request_semaphore = app.state.semaphore
    app.state.converter = ConverterService(
        max_concurrency=current_settings.max_concurrency,
        timeout_s=current_settings.convert_timeout_s,
    )

    # Early Content-Length check (411/413) and request-level concurrency middleware
    @app.middleware("http")
    async def enforce_content_length_and_concurrency(request: Request, call_next):
        if request.method == "POST" and request.url.path.rstrip("/") == "/api/convert":
            content_length = request.headers.get("content-length")
            if content_length is None:
                return JSONResponse(
                    status_code=411,
                    content={
                        "error": "length_required",
                        "detail": "Content-Length header is required for /api/convert.",
                    },
                )
            try:
                declared_len = int(content_length)
            except ValueError:
                return JSONResponse(
                    status_code=411,
                    content={
                        "error": "length_required",
                        "detail": "Content-Length header must be an integer.",
                    },
                )

            active_settings = _resolve_settings(request, current_settings)
            if declared_len > active_settings.max_upload_bytes:
                return JSONResponse(
                    status_code=413,
                    content={
                        "error": "too_large",
                        "detail": (
                            f"Upload size ({declared_len} bytes) exceeds "
                            f"limit of {active_settings.max_upload_mb} MB."
                        ),
                    },
                )

            # Gate the entire request (upload spooling + conversion)
            sem = getattr(request.app.state, "semaphore", None) or getattr(
                request.app.state, "request_semaphore", None
            )
            if sem is not None:
                async with sem:
                    return await call_next(request)
            return await call_next(request)

        return await call_next(request)

    @app.exception_handler(ValidationError)
    async def validation_error_handler(
        _request: Request, exc: ValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.code, "detail": exc.detail},
        )

    @app.exception_handler(ConversionError)
    async def conversion_error_handler(
        _request: Request, exc: ConversionError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.code, "detail": exc.detail},
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(
        _request: Request, exc: HTTPException
    ) -> JSONResponse:
        detail_msg = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        code = "http_error"
        if exc.status_code == 413:
            code = "too_large"
        elif exc.status_code == 415:
            code = "unsupported_type"
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": code, "detail": detail_msg},
        )

    @app.get("/healthz")
    async def health_check() -> dict[str, str]:
        """Health check endpoint."""
        return {"status": "ok"}

    @app.get("/api/formats")
    async def get_formats() -> list[str]:
        """Return the allow-list of accepted extensions."""
        return list(SUPPORTED_EXTENSIONS)

    @app.post("/api/convert")
    async def convert_document(
        request: Request,
        file: Annotated[UploadFile, File(...)],
        frontmatter: Annotated[bool | None, Query()] = None,
        format: Annotated[Literal["md", "json"], Query()] = "md",
        converter: Annotated[ConverterService, Depends(get_converter)] = None,
        settings: Annotated[Settings, Depends(get_settings)] = None,
    ) -> Response:
        """Convert an uploaded document to Markdown."""
        start_time = time.perf_counter()
        filename = file.filename or "unknown"
        filename_hash = hashlib.sha256(
            filename.encode("utf-8", errors="replace")
        ).hexdigest()[:8]
        status = "failed"
        file_size = 0
        ext = ""

        if settings is None:
            settings = _resolve_settings(request, current_settings)
        if converter is None:
            converter = request.app.state.converter

        try:
            # 1. Read header bytes (e.g. 8192 bytes) from UploadFile
            header_bytes = await file.read(8192)

            # 2. Get file size via file.size (fallback: seek to end)
            size = getattr(file, "size", None)
            if size is None:
                file.file.seek(0, os.SEEK_END)
                file_size = file.file.tell()
            else:
                file_size = size

            # 3. Enforce max_upload_bytes -> 413 too_large
            if file_size > settings.max_upload_bytes:
                status = "too_large"
                raise HTTPException(
                    status_code=413,
                    detail=(
                        f"Upload size ({file_size} bytes) exceeds limit "
                        f"of {settings.max_upload_mb} MB."
                    ),
                )

            # 4. Rewind to beginning of stream
            await file.seek(0)
            file.file.seek(0)

            # 5. Validate filename and magic bytes
            ext = validate_file(filename, header_bytes)

            # 6. Perform conversion directly from the spooled stream
            markdown_content = await converter.convert_stream(file.file, ext)

            # 7. Apply frontmatter if requested
            include_frontmatter = (
                frontmatter
                if frontmatter is not None
                else settings.enable_frontmatter_default
            )
            if include_frontmatter:
                markdown_content = add_frontmatter(
                    markdown_content=markdown_content,
                    source_file=filename,
                    source_size_bytes=file_size,
                    converter=f"markitdown {CONVERTER_VERSION}",
                )

            status = "success"

            # 8. Return response according to requested format
            if format == "json":
                return JSONResponse(
                    content={
                        "markdown": markdown_content,
                        "warnings": [],
                        "converter_version": CONVERTER_VERSION,
                    }
                )
            return Response(
                content=markdown_content,
                media_type="text/markdown; charset=utf-8",
            )

        except (ValidationError, ConversionError, HTTPException):
            raise
        except Exception as exc:
            status = "error"
            raise ConversionError(
                code="conversion_failed",
                detail=f"Unexpected error during conversion: {exc}",
                status_code=422,
            ) from exc
        finally:
            # Log conversion metrics (never file contents or Markdown)
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            logger.info(
                "Conversion finished: name_sha256=%s ext=%s size=%d duration_ms=%.1f status=%s",
                filename_hash,
                ext,
                file_size,
                duration_ms,
                status,
            )

    # Mount static files
    static_path = Path(__file__).parent / "static"
    if static_path.exists():
        app.mount(
            "/", StaticFiles(directory=str(static_path), html=True), name="static"
        )

    return app


app = create_app()
