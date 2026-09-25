"""File loader adapter — reads TXT and Markdown files from disk.

This is an infrastructure adapter — it performs I/O operations
and returns domain entities.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from domain.entities import Document

SUPPORTED_EXTENSIONS = {".txt", ".md", ".markdown"}


def load_file(path: str) -> Document:
    """Load a single file and return a Document."""
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    ext = file_path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {ext}. Supported: {SUPPORTED_EXTENSIONS}")
    content = file_path.read_text(encoding="utf-8")
    doc_type = "md" if ext in (".md", ".markdown") else "txt"
    return Document(content=content, source=str(file_path), doc_type=doc_type)


def load_directory(path: str) -> List[Document]:
    """Load all supported files from a directory (non-recursive)."""
    dir_path = Path(path)
    if not dir_path.is_dir():
        raise NotADirectoryError(f"Not a directory: {path}")
    documents: List[Document] = []
    for file_path in sorted(dir_path.iterdir()):
        if file_path.is_file() and file_path.suffix.lower() in SUPPORTED_EXTENSIONS:
            documents.append(load_file(str(file_path)))
    return documents
