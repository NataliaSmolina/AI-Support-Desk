import re
from typing import Protocol

from .models import Chunk, Document


class Chunker(Protocol):
    def chunk(self, doc: Document) -> list[Chunk]:
        """Разбивает документ на смысловые чанки."""


# Regex to match markdown headers, e.g., "# Title", "## Subtitle"
HEADER_REGEX = re.compile(r'^(#{1,6})\s+(.*)$')


class MarkdownHeaderChunker:
    def chunk(self, doc: Document) -> list[Chunk]:
        """
        Splits a markdown document into chunks based on headers.
        Maintains header hierarchy in the metadata and ignores headers inside code blocks.
        """
        chunks = []
        current_headers: dict[int, str] = {}
        current_text_lines = []
        
        lines = doc.content.split('\n')
        in_code_block = False
        
        def flush_chunk():
            text = '\n'.join(current_text_lines).strip()
            if text:
                # Build hierarchy list ordered by header level (H1 -> H2 -> H3)
                hierarchy = tuple(current_headers[i] for i in sorted(current_headers.keys()))
                chunks.append(Chunk(
                    text=text,
                    headers=hierarchy,
                    source_file=doc.source_file,
                ))
            current_text_lines.clear()

        for line in lines:
            # Toggle code block state to avoid parsing headers inside ``` blocks
            if line.strip().startswith("```"):
                in_code_block = not in_code_block
                current_text_lines.append(line)
                continue
                
            if in_code_block:
                current_text_lines.append(line)
                continue
                
            match = HEADER_REGEX.match(line.strip())
            if match:
                # Flush previous chunk before starting a new section
                flush_chunk()
                
                level = len(match.group(1))
                title = match.group(2).strip()
                
                # Update header hierarchy: remove sub-headers deeper or equal to current level
                keys_to_remove = [k for k in current_headers if k >= level]
                for k in keys_to_remove:
                    del current_headers[k]
                    
                current_headers[level] = title
            else:
                current_text_lines.append(line)
                
        # Flush the remaining text as the last chunk
        flush_chunk()
        
        return chunks
