import io
import zipfile

import pytest

from app.services.extractor import ExtractionError, extract_text


def make_docx(paragraphs):
    body = "".join(
        f'<w:p><w:r><w:t xml:space="preserve">{p}</w:t></w:r></w:p>' for p in paragraphs
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", xml)
    return buf.getvalue()


def make_odt(paragraphs):
    body = "".join(f"<text:p>{p}</text:p>" for p in paragraphs)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
        f"<office:body><office:text>{body}</office:text></office:body></office:document-content>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("content.xml", xml)
    return buf.getvalue()


def make_pdf(text: str) -> bytes:
    """Minimalny poprawny PDF z jedną stroną tekstu (Helvetica)."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode())
    return out.getvalue()


def test_docx_paragraphs_and_polish_chars():
    text = extract_text("praca.docx", make_docx(["Zażółć gęślą jaźń.", "Drugi akapit."]))
    assert text == "Zażółć gęślą jaźń.\n\nDrugi akapit."


def test_odt():
    text = extract_text("praca.odt", make_odt(["Pierwszy akapit ODT.", "Łódź i Kraków."]))
    assert "Pierwszy akapit ODT." in text and "Łódź i Kraków." in text


def test_txt_cp1250_fallback():
    raw = "Zażółć gęślą jaźń".encode("cp1250")
    assert extract_text("a.txt", raw) == "Zażółć gęślą jaźń"


def test_txt_utf8_bom_and_whitespace():
    raw = "﻿Ala  ma kota\r\n\r\n\r\n\r\nKoniec".encode("utf-8")
    assert extract_text("a.TXT", raw) == "Ala ma kota\n\nKoniec"


def test_pdf():
    text = extract_text("doc.pdf", make_pdf("Hello plagiarism checker"))
    assert "Hello plagiarism checker" in text


@pytest.mark.parametrize("name,data", [("a.exe", b"x"), ("a.txt", b""), ("a.docx", b"not a zip")])
def test_errors(name, data):
    with pytest.raises(ExtractionError):
        extract_text(name, data)
