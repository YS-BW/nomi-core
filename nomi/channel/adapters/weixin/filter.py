"""微信流式文本过滤器。"""

from __future__ import annotations


class StreamingTextFilter:
    """按增量清洗微信不适合直接发送的 Markdown 结构。"""

    def __init__(self) -> None:
        """初始化增量过滤所需的内部状态。"""
        self._buffer = ""
        self._in_code_fence = False

    def feed(self, delta: str) -> str:
        """输入一段增量文本并返回当前可安全输出的部分。"""
        self._buffer += delta
        return self._drain(eof=False)

    def flush(self) -> str:
        """在流结束时输出剩余可见文本。"""
        return self._drain(eof=True)

    def _drain(self, *, eof: bool) -> str:
        if not self._buffer:
            return ""

        normalized = self._buffer.replace("\r\n", "\n")
        if not eof and normalized.count("```") % 2 == 1:
            fence_start = normalized.rfind("```")
            visible = normalized[:fence_start]
            self._buffer = normalized[fence_start:]
        else:
            visible = normalized
            self._buffer = ""

        return self._sanitize_visible_text(visible, eof=eof)

    def _sanitize_visible_text(self, text: str, *, eof: bool) -> str:
        lines = text.split("\n")
        cleaned: list[str] = []
        for idx, raw_line in enumerate(lines):
            is_last = idx == len(lines) - 1
            line = raw_line
            stripped = line.lstrip()

            if stripped.startswith("```"):
                self._in_code_fence = not self._in_code_fence
                continue
            if self._in_code_fence:
                cleaned.append(line)
                continue

            if stripped.startswith(">"):
                line = stripped[1:].lstrip()

            hashes = len(stripped) - len(stripped.lstrip("#"))
            if 1 <= hashes <= 6 and stripped[:hashes] == "#" * hashes:
                rest = stripped[hashes:]
                if not rest or rest.startswith(" "):
                    line = rest.lstrip()

            if stripped.startswith(("- ", "* ", "_ ")):
                line = stripped[2:]

            if stripped.startswith("|"):
                parts = [part.strip() for part in stripped.strip("|").split("|")]
                line = " ".join(part for part in parts if part and set(part) != {"-"} and set(part) != {":"})

            if not eof and is_last and self._ends_with_unclosed_inline_marker(line):
                self._buffer = line + self._buffer
                break

            cleaned.append(line)

        return "\n".join(item for item in cleaned if item).strip()

    @staticmethod
    def _ends_with_unclosed_inline_marker(text: str) -> bool:
        markers = ("`", "*", "_", "~~")
        for marker in markers:
            if text.endswith(marker) and text.count(marker) % 2 == 1:
                return True
        return False
