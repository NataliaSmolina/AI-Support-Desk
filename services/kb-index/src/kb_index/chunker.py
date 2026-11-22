import re
from typing import Protocol

from .models import Chunk, Document
from .tokenization import TokenCounter


class Chunker(Protocol):
    def chunk(self, doc: Document) -> list[Chunk]:
        """Разбивает документ на смысловые чанки."""


HEADER_REGEX = re.compile(r'^(#{1,6})\s+(.*)$')
SENTENCE_SPLIT = re.compile(r'(?<=[.!?…])\s+')


class MarkdownHeaderChunker:
    def __init__(self, tokenizer: TokenCounter, max_tokens: int):
        if max_tokens < 1:
            raise ValueError("max_tokens must be positive")
        self.tokenizer = tokenizer
        self.max_tokens = max_tokens

    def chunk(self, doc: Document) -> list[Chunk]:
        """
        Splits Markdown by headers, then limits each section by token count.
        Large sections are split by paragraphs, sentences and token boundaries.
        Headers are preserved in the chunk metadata and in embedding_text.
        """
        chunks: list[Chunk] = []

        for headers, text in self._sections(doc.content):
            text = text.strip()
            if not text:
                continue

            for piece in self._split_section(headers, text):
                chunks.append(
                    Chunk(
                        text=piece,
                        headers=headers,
                        source_file=doc.source_file,
                    )
                )

        return chunks

    def _sections(self, content: str) -> list[tuple[tuple[str, ...], str]]:
        sections: list[tuple[tuple[str, ...], str]] = []
        current_headers: dict[int, str] = {}
        current_text_lines: list[str] = []
        in_code_block = False

        def flush_section() -> None:
            text = "\n".join(current_text_lines).strip()
            if text:
                hierarchy = tuple(
                    current_headers[level]
                    for level in sorted(current_headers)
                )
                sections.append((hierarchy, text))
            current_text_lines.clear()

        for line in content.split("\n"):
            if line.strip().startswith("```"):
                in_code_block = not in_code_block
                current_text_lines.append(line)
                continue

            if in_code_block:
                current_text_lines.append(line)
                continue

            match = HEADER_REGEX.match(line.strip())
            if match:
                flush_section()

                level = len(match.group(1))
                title = match.group(2).strip()

                for key in [key for key in current_headers if key >= level]:
                    del current_headers[key]

                current_headers[level] = title
            else:
                current_text_lines.append(line)

        flush_section()
        return sections

    def _split_section(self, headers: tuple[str, ...], text: str) -> list[str]:
        if self._fits(headers, text):
            return [text]

        pieces: list[tuple[str, str]] = []
        for block in self._blocks(text):
            block_pieces = self._split_block(headers, block)
            structured = self._is_table(block) or self._is_code_block(block)
            for index, piece in enumerate(block_pieces):
                if not pieces:
                    separator = ""
                elif index == 0 or structured:
                    separator = "\n\n"
                else:
                    separator = " "
                pieces.append((piece, separator))

        return self._pack(headers, pieces)

    def _blocks(self, text: str) -> list[str]:
        """Делит текст на абзацы, не разрывая fenced code blocks."""
        blocks: list[str] = []
        current_lines: list[str] = []
        in_code_block = False

        for line in text.split("\n"):
            if line.strip().startswith("```"):
                in_code_block = not in_code_block
                current_lines.append(line)
                continue

            if not in_code_block and not line.strip():
                if current_lines:
                    blocks.append("\n".join(current_lines).strip())
                    current_lines.clear()
            else:
                current_lines.append(line)

        if current_lines:
            blocks.append("\n".join(current_lines).strip())

        return [block for block in blocks if block]

    def _split_block(self, headers: tuple[str, ...], block: str) -> list[str]:
        if self._fits(headers, block):
            return [block]

        if self._is_table(block):
            return self._split_table(headers, block)

        if self._is_code_block(block):
            return self._split_code_block(headers, block)

        sentences = [
            sentence.strip()
            for sentence in SENTENCE_SPLIT.split(block)
            if sentence.strip()
        ]
        if len(sentences) <= 1:
            return self._hard_split(headers, block)

        pieces: list[str] = []
        for sentence in sentences:
            if self._fits(headers, sentence):
                pieces.append(sentence)
            else:
                pieces.extend(self._hard_split(headers, sentence))

        return pieces

    @staticmethod
    def _is_table(block: str) -> bool:
        lines = [line for line in block.splitlines() if line.strip()]
        return (
            len(lines) >= 2
            and all(line.lstrip().startswith("|") for line in lines)
        )

    @staticmethod
    def _is_code_block(block: str) -> bool:
        return block.lstrip().startswith("```")

    def _split_table(self, headers: tuple[str, ...], block: str) -> list[str]:
        lines = block.splitlines()
        header_lines = lines[:2]
        rows = lines[2:]

        header_text = "\n".join(header_lines)
        if not self._fits(headers, header_text):
            return self._hard_split(headers, block)

        chunks: list[str] = []
        current = list(header_lines)

        for row in rows:
            candidate = "\n".join(current + [row])
            if self._fits(headers, candidate):
                current.append(row)
                continue

            if len(current) > len(header_lines):
                chunks.append("\n".join(current))

            row_with_header = "\n".join(header_lines + [row])
            if self._fits(headers, row_with_header):
                current = list(header_lines) + [row]
            else:
                chunks.extend(self._hard_split(headers, row_with_header))
                current = list(header_lines)

        if len(current) > len(header_lines):
            chunks.append("\n".join(current))

        return chunks or [block]

    def _split_code_block(self, headers: tuple[str, ...], block: str) -> list[str]:
        lines = block.splitlines()
        opening = lines[0]
        closing = (
            lines[-1]
            if len(lines) > 1 and lines[-1].strip().startswith("```")
            else None
        )
        body = lines[1:-1] if closing else lines[1:]

        chunks: list[str] = []
        current = [opening]

        for line in body:
            candidate_lines = current + [line]
            if closing:
                candidate_lines.append(closing)

            if self._fits(headers, "\n".join(candidate_lines)):
                current.append(line)
                continue

            if len(current) > 1:
                chunk_lines = current + ([closing] if closing else [])
                chunks.append("\n".join(chunk_lines))

            current = [opening]
            single_line = [opening, line]
            if closing:
                single_line.append(closing)

            if self._fits(headers, "\n".join(single_line)):
                current.append(line)
            else:
                # Очень длинная строка кода: сохраняем fences, но режем строку.
                chunks.extend(
                    self._hard_split(headers, "\n".join(single_line))
                )
                current = [opening]

        if len(current) > 1:
            chunk_lines = current + ([closing] if closing else [])
            chunks.append("\n".join(chunk_lines))

        return chunks or self._hard_split(headers, block)

    def _pack(
        self,
        headers: tuple[str, ...],
        pieces: list[tuple[str, str]],
    ) -> list[str]:
        chunks: list[str] = []
        current = ""

        for piece, separator in pieces:
            if not current:
                current = piece
                continue

            candidate = current + separator + piece
            if self._fits(headers, candidate):
                current = candidate
            else:
                chunks.append(current)
                current = piece

        if current:
            chunks.append(current)

        return chunks

    def _hard_split(self, headers: tuple[str, ...], text: str) -> list[str]:
        """Режет текст по максимальному префиксу, помещающемуся в лимит."""
        pieces: list[str] = []
        remaining = text.strip()

        while remaining:
            if self._fits(headers, remaining):
                pieces.append(remaining)
                break

            low, high = 0, len(remaining)
            while low < high:
                middle = (low + high + 1) // 2
                if self._fits(headers, remaining[:middle]):
                    low = middle
                else:
                    high = middle - 1

            if low <= 0:
                raise ValueError(
                    "Заголовки и служебные токены не помещаются в max_tokens"
                )

            cut = low
            whitespace = remaining.rfind(" ", 0, cut + 1)
            if whitespace > 0 and whitespace >= cut // 2:
                cut = whitespace

            piece = remaining[:cut].strip()
            if not piece:
                piece = remaining[:cut]

            pieces.append(piece)
            remaining = remaining[cut:].strip()

        return pieces

    def _fits(self, headers: tuple[str, ...], text: str) -> bool:
        embedding_text = Chunk(text=text, headers=headers).embedding_text
        return self.tokenizer.count(embedding_text) <= self.max_tokens
