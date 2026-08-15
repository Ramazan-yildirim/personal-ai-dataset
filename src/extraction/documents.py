"""Document-to-text extraction adapters for registered raw sources."""

from __future__ import annotations

import json
import re
import sqlite3
import zipfile
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from src.database.connection import PROJECT_ROOT
from src.database.sources import compute_file_hash, get_source


EXTRACTED_ROOT = PROJECT_ROOT / "data" / "staging" / "extracted"


class ExtractionError(Exception):
    """Base exception for document extraction."""


class ExtractionValidationError(ExtractionError, ValueError):
    """Raised when a document cannot be passed to an adapter."""


class ExtractionDependencyError(ExtractionError):
    """Raised when an optional parser dependency is unavailable."""


class ExtractionIntegrityError(ExtractionError):
    """Raised when raw content no longer matches its registered hash."""


class EmptyExtractionError(ExtractionError):
    """Raised when an adapter cannot extract meaningful text."""


class _VisibleHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.hidden_depth = 0

    def handle_starttag(self, tag: str, attrs):
        if tag in {"script", "style"}:
            self.hidden_depth += 1
        elif tag in {"p", "div", "br", "li", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str):
        if tag in {"script", "style"} and self.hidden_depth:
            self.hidden_depth -= 1
        elif tag in {"p", "div", "li"}:
            self.parts.append("\n")

    def handle_data(self, data: str):
        if not self.hidden_depth:
            self.parts.append(data)


def _normalize_text(text: str) -> str:
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
    normalized = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", normalized)


def _read_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1254"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise ExtractionValidationError(
        f"Metin dosyasının encoding'i çözülemedi: {path}"
    )


def _extract_json(path: Path) -> str:
    try:
        content = json.loads(_read_text(path))
    except json.JSONDecodeError as error:
        raise ExtractionValidationError(
            f"Geçersiz JSON belgesi: {path}"
        ) from error
    return json.dumps(content, ensure_ascii=False, indent=2, sort_keys=True)


def _extract_html(path: Path) -> str:
    parser = _VisibleHTMLParser()
    parser.feed(_read_text(path))
    return "".join(parser.parts)


def _extract_docx(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            document_xml = archive.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError) as error:
        raise ExtractionValidationError(f"Geçersiz DOCX belgesi: {path}") from error

    try:
        root = ElementTree.fromstring(document_xml)
    except ElementTree.ParseError as error:
        raise ExtractionValidationError(
            f"Geçersiz DOCX XML içeriği: {path}"
        ) from error
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    paragraphs = []
    for paragraph in root.iter(f"{namespace}p"):
        parts = [
            node.text or ""
            for node in paragraph.iter(f"{namespace}t")
        ]
        if parts:
            paragraphs.append("".join(parts))
    return "\n".join(paragraphs)


def _extract_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as error:
        raise ExtractionDependencyError(
            "PDF extraction için 'pip install -r requirements.txt' çalıştırın."
        ) from error

    try:
        reader = PdfReader(str(path))
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as error:
        raise ExtractionValidationError(
            f"PDF metni çıkarılamadı: {path}"
        ) from error


def extract_text(file_path: str | Path) -> str:
    """Extract normalized text using the adapter selected by file suffix."""

    path = Path(file_path).expanduser().resolve()
    if not path.exists() or not path.is_file():
        raise ExtractionValidationError(f"Belge bulunamadı: {path}")

    suffix = path.suffix.lower()
    if suffix in {".txt", ".md", ".csv"}:
        text = _read_text(path)
    elif suffix == ".json":
        text = _extract_json(path)
    elif suffix in {".html", ".htm"}:
        text = _extract_html(path)
    elif suffix == ".docx":
        text = _extract_docx(path)
    elif suffix == ".pdf":
        text = _extract_pdf(path)
    elif suffix in {".png", ".jpg", ".jpeg"}:
        raise ExtractionDependencyError(
            "Görsel belgeler için OCR adaptörü henüz mevcut değil."
        )
    else:
        raise ExtractionValidationError(
            f"Bu uzantı için extraction adaptörü yok: {suffix}"
        )

    normalized = _normalize_text(text)
    if not normalized:
        raise EmptyExtractionError(f"Belgeden anlamlı metin çıkarılamadı: {path}")
    return normalized


def _source_path(file_path: str) -> Path:
    path = Path(file_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def extract_source(
    source_id: int,
    *,
    output_root: str | Path | None = None,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Verify and extract a registered source into reproducible staging JSON."""

    source = get_source(source_id, connection=connection)
    if not source["is_active"]:
        raise ExtractionValidationError("Inactive bir source extract edilemez.")
    if not source["file_path"]:
        raise ExtractionValidationError("Source kaydının file_path alanı yok.")

    path = _source_path(source["file_path"])
    actual_hash = compute_file_hash(path)
    if source["file_hash"] and actual_hash != source["file_hash"]:
        raise ExtractionIntegrityError(
            "Raw belge içeriği kayıtlı hash ile eşleşmiyor."
        )

    text = extract_text(path)
    destination_root = (
        Path(output_root).resolve()
        if output_root is not None
        else EXTRACTED_ROOT
    )
    destination_root.mkdir(parents=True, exist_ok=True)
    output_path = destination_root / f"source_{source_id}_{actual_hash[:8]}.json"
    payload = {
        "source_id": source_id,
        "source_type": source["source_type"],
        "title": source["title"],
        "file_path": source["file_path"],
        "file_hash": actual_hash,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "text": text,
    }

    temporary_path = output_path.with_suffix(".json.tmp")
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary_path.replace(output_path)
    return {**payload, "output_path": str(output_path)}
