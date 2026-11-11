"""Minimal HTML table extractor on the standard library's html.parser.

It replaces BeautifulSoup for the one thing the parsers need: every <table> in
document order, as rows of cells with whitespace-collapsed text and the link
targets in each cell.

- Rows from <thead>, <tbody> and <tfoot> come in document order.
- Unclosed <td>, <th> and <tr> are closed by the next cell, row or table end.
- A nested table is extracted as its own Table (after its parent, in start-tag
  order), and its text is not added to the parent cell.
- Text inside <script> and <style> is ignored.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser


@dataclass(frozen=True)
class Cell:
    text: str
    hrefs: tuple[str, ...] = ()
    header: bool = False  # a <th> cell


@dataclass
class Row:
    cells: list[Cell] = field(default_factory=list)


@dataclass
class Table:
    rows: list[Row] = field(default_factory=list)


def extract_tables(html: str) -> list[Table]:
    parser = _TableParser()
    parser.feed(html)
    parser.close()
    return parser.tables


class _OpenTable:
    def __init__(self, table: Table) -> None:
        self.table = table
        self.row: list[Cell] | None = None
        self.parts: list[str] | None = None  # text of the open cell
        self.hrefs: list[str] = []
        self.header = False

    def close_cell(self) -> None:
        if self.parts is None:
            return
        text = " ".join(" ".join(self.parts).split())
        if self.row is None:
            self.row = []
        self.row.append(Cell(text=text, hrefs=tuple(self.hrefs), header=self.header))
        self.parts, self.hrefs, self.header = None, [], False

    def close_row(self) -> None:
        self.close_cell()
        if self.row is not None:
            self.table.rows.append(Row(cells=self.row))
            self.row = None

    def open_cell(self, header: bool) -> None:
        self.close_cell()
        if self.row is None:
            self.row = []
        self.parts, self.hrefs, self.header = [], [], header


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[Table] = []
        self.stack: list[_OpenTable] = []
        self.skip_depth = 0  # inside <script> or <style>

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self.skip_depth += 1
            return
        if tag == "table":
            table = Table()
            self.tables.append(table)
            self.stack.append(_OpenTable(table))
            return
        if not self.stack:
            return
        current = self.stack[-1]
        if tag == "tr":
            current.close_row()
            current.row = []
        elif tag in ("td", "th"):
            current.open_cell(header=tag == "th")
        elif tag in ("thead", "tbody", "tfoot"):
            current.close_row()
        elif tag == "a" and current.parts is not None:
            href = dict(attrs).get("href")
            if href and href.strip():
                current.hrefs.append(href.strip())
        elif tag == "br" and current.parts is not None:
            current.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        if not self.stack:
            return
        current = self.stack[-1]
        if tag == "table":
            current.close_row()
            self.stack.pop()
        elif tag in ("td", "th"):
            current.close_cell()
        elif tag in ("tr", "thead", "tbody", "tfoot"):
            current.close_row()

    def handle_data(self, data: str) -> None:
        if self.skip_depth or not self.stack:
            return
        current = self.stack[-1]
        if current.parts is not None:
            current.parts.append(data)

    def close(self) -> None:
        super().close()
        while self.stack:
            self.stack.pop().close_row()
