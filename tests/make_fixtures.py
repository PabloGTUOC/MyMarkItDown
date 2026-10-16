"""Script to generate tiny fixtures (<200KB each) for testing."""

import io
import zipfile
from pathlib import Path

import openpyxl
from pptx import Presentation

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def make_jpeg_bytes() -> bytes:
    """Generate a minimal valid 1x1 JPEG image."""
    return bytes(
        [
            0xFF,
            0xD8,
            0xFF,
            0xE0,
            0x00,
            0x10,
            0x4A,
            0x46,
            0x49,
            0x46,
            0x00,
            0x01,
            0x01,
            0x01,
            0x00,
            0x60,
            0x00,
            0x60,
            0x00,
            0x00,
            0xFF,
            0xDB,
            0x00,
            0x43,
            0x00,
            0x08,
            0x06,
            0x06,
            0x07,
            0x06,
            0x05,
            0x08,
            0x07,
            0x07,
            0x07,
            0x09,
            0x09,
            0x08,
            0x0A,
            0x0C,
            0x14,
            0x0D,
            0x0C,
            0x0B,
            0x0B,
            0x0C,
            0x19,
            0x12,
            0x13,
            0x0F,
            0x14,
            0x1D,
            0x1A,
            0x1F,
            0x1E,
            0x1D,
            0x1A,
            0x1C,
            0x1C,
            0x20,
            0x24,
            0x2E,
            0x27,
            0x20,
            0x22,
            0x2C,
            0x23,
            0x1C,
            0x1C,
            0x28,
            0x37,
            0x29,
            0x2C,
            0x30,
            0x31,
            0x34,
            0x34,
            0x34,
            0x1F,
            0x27,
            0x39,
            0x3D,
            0x38,
            0x32,
            0x3C,
            0x2E,
            0x33,
            0x34,
            0x32,
            0xFF,
            0xC0,
            0x00,
            0x0B,
            0x08,
            0x00,
            0x01,
            0x00,
            0x01,
            0x01,
            0x01,
            0x11,
            0x00,
            0xFF,
            0xC4,
            0x00,
            0x1F,
            0x00,
            0x00,
            0x01,
            0x05,
            0x01,
            0x01,
            0x01,
            0x01,
            0x01,
            0x01,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
            0x01,
            0x02,
            0x03,
            0x04,
            0x05,
            0x06,
            0x07,
            0x08,
            0x09,
            0x0A,
            0x0B,
            0xFF,
            0xDA,
            0x00,
            0x08,
            0x01,
            0x01,
            0x00,
            0x00,
            0x3F,
            0x00,
            0xBF,
            0x00,
            0xFF,
            0xD9,
        ]
    )


def create_sample_pdf(path: Path) -> None:
    """Generate a minimal valid 1-page PDF."""
    pdf_content = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n"
        b"4 0 obj\n<< /Length 44 >>\nstream\nBT\n/F1 12 Tf\n72 720 Td\n(Hello PDF Document) Tj\nET\nendstream\nendobj\n"
        b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n"
        b"xref\n0 6\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000058 00000 n \n"
        b"0000000115 00000 n \n"
        b"0000000244 00000 n \n"
        b"0000000338 00000 n \n"
        b"trailer\n<< /Size 6 /Root 1 0 R >>\n"
        b"startxref\n417\n%%EOF\n"
    )
    path.write_bytes(pdf_content)


def create_sample_docx(path: Path) -> None:
    """Generate a minimal valid DOCX package."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>",
        )
        z.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            "</Relationships>",
        )
        z.writestr(
            "word/document.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body>"
            "<w:p><w:r><w:t>Hello DOCX Document</w:t></w:r></w:p>"
            "</w:body>"
            "</w:document>",
        )
    path.write_bytes(buf.getvalue())


def create_sample_xlsx(path: Path) -> None:
    """Generate a minimal valid XLSX document."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["Name", "Value"])
    ws.append(["Alice", 100])
    ws.append(["Bob", 200])
    wb.save(path)


def create_sample_pptx(path: Path) -> None:
    """Generate a minimal valid PPTX document."""
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[0])
    slide.shapes.title.text = "Hello Presentation"
    prs.save(path)


def create_sample_csv(path: Path) -> None:
    """Generate a sample CSV file."""
    path.write_text(
        "id,name,role\n1,Alice,Engineer\n2,Bob,Designer\n", encoding="utf-8"
    )


def create_sample_html(path: Path) -> None:
    """Generate a sample HTML file."""
    content = (
        "<!DOCTYPE html>\n"
        "<html>\n"
        "<head><title>Sample HTML</title></head>\n"
        "<body>\n"
        "<h1>Sample Title</h1>\n"
        "<p>Sample paragraph content.</p>\n"
        "</body>\n"
        "</html>\n"
    )
    path.write_text(content, encoding="utf-8")


def generate_all() -> None:
    """Generate all test fixtures."""
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

    jpeg_data = make_jpeg_bytes()
    (FIXTURES_DIR / "photo.jpg").write_bytes(jpeg_data)
    (FIXTURES_DIR / "fake.pdf").write_bytes(jpeg_data)

    create_sample_pdf(FIXTURES_DIR / "sample.pdf")
    create_sample_docx(FIXTURES_DIR / "sample.docx")
    create_sample_xlsx(FIXTURES_DIR / "sample.xlsx")
    create_sample_pptx(FIXTURES_DIR / "sample.pptx")
    create_sample_csv(FIXTURES_DIR / "sample.csv")
    create_sample_html(FIXTURES_DIR / "sample.html")

    print(f"Generated fixtures in {FIXTURES_DIR}:")
    for f in FIXTURES_DIR.iterdir():
        print(f"  {f.name}: {f.stat().st_size} bytes")


if __name__ == "__main__":
    generate_all()
