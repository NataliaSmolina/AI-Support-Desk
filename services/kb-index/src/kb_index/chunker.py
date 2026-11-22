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
            for index, piece in enumerate(block_pieces):
                if not pieces:
                    separator = ""
                elif index == 0:
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

        if block.lstrip().startswith("```"):
            return self._hard_split(headers, block)

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
