"""Utilities for chunking large text blobs into model-friendly slices."""

from typing import List


def chunk_text(content: str, max_chars: int) -> List[str]:
    """Split text into roughly even chunks without breaking paragraphs."""

    if not content:
        return []

    max_chars = max(1, max_chars)
    paragraphs = content.split("\n\n")

    chunks: List[str] = []
    current: List[str] = []
    current_len = 0

    for paragraph in paragraphs:
        normalized = paragraph.strip()
        if not normalized:
            continue

        addition = len(normalized) + (2 if current else 0)

        if current and current_len + addition > max_chars:
            chunks.append("\n\n".join(current))
            current = [normalized]
            current_len = len(normalized)
        else:
            current.append(normalized)
            current_len += addition

    if current:
        chunks.append("\n\n".join(current))

    return chunks
