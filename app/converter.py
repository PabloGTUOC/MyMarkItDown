"""Document conversion service wrapping MarkItDown."""

import asyncio
import importlib.metadata
from typing import BinaryIO

import anyio
from markitdown import MarkItDown, StreamInfo

# Instantiate MarkItDown once at startup with plugins disabled
MARKITDOWN_INSTANCE = MarkItDown(enable_plugins=False)
CONVERTER_VERSION: str = importlib.metadata.version("markitdown")


class ConversionError(Exception):
    """Conversion error with specific error code and status."""

    def __init__(self, code: str, detail: str, status_code: int = 422) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status_code = status_code


class ConverterService:
    """Manages threadpool execution and timeouts for MarkItDown conversions."""

    def __init__(self, max_concurrency: int = 2, timeout_s: float = 120.0) -> None:
        self.max_concurrency = max_concurrency
        self.timeout_s = timeout_s

    def _sync_convert_stream(self, file_stream: BinaryIO, ext: str) -> str:
        """Run synchronous conversion from a binary stream using MarkItDown."""
        try:
            stream = getattr(file_stream, "_file", file_stream)
            result = MARKITDOWN_INSTANCE.convert_stream(
                stream,
                stream_info=StreamInfo(extension=ext),
            )
            return result.text_content or ""
        except Exception as exc:
            raise ConversionError(
                code="conversion_failed",
                detail=f"Failed to convert document: {exc}",
                status_code=422,
            ) from exc

    async def convert_stream(self, file_stream: BinaryIO, ext: str) -> str:
        """Asynchronously convert a binary stream with timeout."""
        try:
            return await asyncio.wait_for(
                anyio.to_thread.run_sync(self._sync_convert_stream, file_stream, ext),
                timeout=self.timeout_s,
            )
        except TimeoutError as exc:
            raise ConversionError(
                code="timeout",
                detail=f"Conversion timed out after {self.timeout_s} seconds.",
                status_code=504,
            ) from exc


# Global singleton converter service
converter_service = ConverterService()
