"""Extractor — wyciąganie czystego tekstu z DOCX, ODT, PDF i TXT.

DOCX/ODT czytamy bezpośrednio z archiwum ZIP (stdlib), PDF przez pypdf
(czysty Python). Dzięki temu nie potrzebujemy lxml ani PyMuPDF, których
nie da się łatwo zainstalować na FreeBSD (CT8).
"""
from __future__ import annotations

import io
import re
import unicodedata
import zipfile
from pathlib import PurePath
from xml.etree import ElementTree as ET

SUPPORTED_EXTENSIONS = {".docx", ".odt", ".pdf", ".txt"}
MAX_XML_BYTES = 60 * 1024 * 1024  # ochrona przed "zip bombami"

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
TEXT_NS = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"


class ExtractionError(ValueError):
    """Nie udało się odczytać pliku."""


def extract_text(filename: str, data: bytes) -> str:
    ext = PurePath(filename or "").suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ExtractionError(
            f"Nieobsługiwany format pliku '{ext or '?'}'. Obsługiwane: DOCX, ODT, PDF, TXT."
        )
    if not data:
        raise ExtractionError("Plik jest pusty.")
    try:
        if ext == ".docx":
            text = _extract_docx(data)
        elif ext == ".odt":
            text = _extract_odt(data)
        elif ext == ".pdf":
            text = _extract_pdf(data)
        else:
            text = _decode_text(data)
    except ExtractionError:
        raise
    except Exception as exc:  # pragma: no cover - zależne od uszkodzonych plików
        raise ExtractionError(f"Nie udało się odczytać pliku: {exc}") from exc
    text = normalize_whitespace(text)
    if not text.strip():
        raise ExtractionError(
            "Nie znaleziono tekstu w pliku (skan bez warstwy tekstowej? — wymagany OCR)."
        )
    return text


def normalize_whitespace(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("­", "")  # miękki dywiz
    text = re.sub(r"[   \t]+", " ", text)
    text = re.sub(r"[ ]{2,}", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _read_zip_member(data: bytes, name: str) -> bytes:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ExtractionError("Plik nie jest poprawnym archiwum DOCX/ODT.") from exc
    with zf:
        try:
            info = zf.getinfo(name)
        except KeyError as exc:
            raise ExtractionError(f"Brak elementu {name} w pliku.") from exc
        if info.file_size > MAX_XML_BYTES:
            raise ExtractionError("Dokument jest zbyt duży.")
        return zf.read(name)


def _extract_docx(data: bytes) -> str:
    root = ET.fromstring(_read_zip_member(data, "word/document.xml"))
    paragraphs: list[str] = []
    for p in root.iter(f"{W_NS}p"):
        parts: list[str] = []
        for node in p.iter():
            tag = node.tag
            if tag == f"{W_NS}t" and node.text:
                parts.append(node.text)
            elif tag == f"{W_NS}tab":
                parts.append(" ")
            elif tag in (f"{W_NS}br", f"{W_NS}cr"):
                parts.append("\n")
        paragraphs.append("".join(parts))
    return "\n\n".join(p for p in paragraphs if p.strip())


def _odt_text(node: ET.Element) -> str:
    parts: list[str] = [node.text or ""]
    for child in node:
        tag = child.tag
        if tag == f"{TEXT_NS}s":
            parts.append(" " * int(child.get(f"{TEXT_NS}c", "1")))
        elif tag == f"{TEXT_NS}tab":
            parts.append(" ")
        elif tag == f"{TEXT_NS}line-break":
            parts.append("\n")
        elif tag in (f"{TEXT_NS}note", f"{TEXT_NS}p", f"{TEXT_NS}h"):
            pass  # przypisy i zagnieżdżone akapity obsługujemy osobno
        else:
            parts.append(_odt_text(child))
        parts.append(child.tail or "")
    return "".join(parts)


def _extract_odt(data: bytes) -> str:
    root = ET.fromstring(_read_zip_member(data, "content.xml"))
    paragraphs = [
        _odt_text(el)
        for el in root.iter()
        if el.tag in (f"{TEXT_NS}p", f"{TEXT_NS}h")
    ]
    return "\n\n".join(p for p in paragraphs if p.strip())


def _extract_pdf(data: bytes) -> str:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception as exc:
                raise ExtractionError("PDF jest zaszyfrowany hasłem.") from exc
        pages = [page.extract_text() or "" for page in reader.pages]
    except PdfReadError as exc:
        raise ExtractionError(f"Uszkodzony PDF: {exc}") from exc
    text = "\n\n".join(pages)
    # Scalanie wyrazów przeniesionych z dywizem na końcu linii: "przy-\nkład"
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    # Pojedyncze złamania linii wewnątrz akapitu → spacja
    text = re.sub(r"(?<![.!?:;\n])\n(?!\n)", " ", text)
    return text


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1250", "iso-8859-2"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")
