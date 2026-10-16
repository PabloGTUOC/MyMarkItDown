"""Frontmatter generation for converted Markdown documents."""

from datetime import UTC, datetime


def add_frontmatter(
    markdown_content: str,
    source_file: str,
    source_size_bytes: int,
    converter: str,
    converted_at: datetime | None = None,
) -> str:
    """Prepend YAML frontmatter block to the markdown content."""
    if converted_at is None:
        converted_at = datetime.now(UTC)

    # Format timestamp as ISO 8601 with Z: e.g. 2026-10-12T10:15:00Z
    iso_time = converted_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Escape or quote file path if necessary
    safe_filename = source_file.replace("\n", " ").replace('"', '\\"')

    frontmatter_lines = [
        "---",
        f'source_file: "{safe_filename}"'
        if ":" in safe_filename
        else f"source_file: {safe_filename}",
        f"source_size_bytes: {source_size_bytes}",
        f"converted_at: {iso_time}",
        f"converter: {converter}",
        "---",
        "",
    ]

    return "\n".join(frontmatter_lines) + "\n" + markdown_content
