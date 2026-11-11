from jamstockex.html import Cell, Row, Table, extract_tables


def texts(table):
    return [[cell.text for cell in row.cells] for row in table.rows]


def test_simple_table_with_header_cells():
    [table] = extract_tables("<table><tr><th>Symbol</th><th>Close</th></tr><tr><td>ACME</td><td>1.5</td></tr></table>")
    assert table == Table(rows=[
        Row(cells=[Cell(text="Symbol", header=True), Cell(text="Close", header=True)]),
        Row(cells=[Cell(text="ACME"), Cell(text="1.5")]),
    ])


def test_thead_tbody_tfoot_rows_come_in_document_order():
    html = """<table>
      <thead><tr><th>H</th></tr></thead>
      <tfoot><tr><td>F</td></tr></tfoot>
      <tbody><tr><td>B1</td></tr><tr><td>B2</td></tr></tbody>
    </table>"""
    [table] = extract_tables(html)
    assert texts(table) == [["H"], ["F"], ["B1"], ["B2"]]


def test_unclosed_cells_and_rows_are_closed_by_what_follows():
    [table] = extract_tables("<table><tr><td>a<td>b<tr><td>c</table><p>after</p>")
    assert texts(table) == [["a", "b"], ["c"]]


def test_unclosed_table_at_end_of_input_is_kept():
    [table] = extract_tables("<table><tr><th>X<tr><td>1")
    assert texts(table) == [["X"], ["1"]]


def test_tbody_closes_an_open_row():
    [table] = extract_tables("<table><thead><tr><th>A</thead><tbody><tr><td>1</tbody></table>")
    assert texts(table) == [["A"], ["1"]]


def test_nested_tables_are_separate_and_not_part_of_the_parent_cell():
    html = """<table>
      <tr><td>outer <table><tr><td>inner 1</td></tr><tr><td>inner 2</td></tr></table> cell</td><td>next</td></tr>
      <tr><td>outer row 2</td></tr>
    </table>"""
    outer, inner = extract_tables(html)
    assert texts(outer) == [["outer cell", "next"], ["outer row 2"]]
    assert texts(inner) == [["inner 1"], ["inner 2"]]


def test_hrefs_are_collected_per_cell():
    html = """<table><tr>
      <td><a href="/i/?instrument=9001">ACME</a> <a href=" https://acme.example ">site</a></td>
      <td>no link</td><td><a>no href</a><a href="">empty</a></td>
    </tr></table>"""
    [table] = extract_tables(html)
    cells = table.rows[0].cells
    assert cells[0].hrefs == ("/i/?instrument=9001", "https://acme.example")
    assert cells[0].text == "ACME site"
    assert cells[1].hrefs == ()
    assert cells[2].hrefs == ()


def test_whitespace_and_entities_are_collapsed():
    [table] = extract_tables("<table><tr><td>\n  Acme\n\t Holdings&nbsp;Ltd<br>Group &amp; Co  </td></tr></table>")
    assert table.rows[0].cells[0].text == "Acme Holdings Ltd Group & Co"


def test_script_and_style_text_is_ignored():
    html = "<table><tr><td>a<script>var x = '<td>no</td>';</script><style>td{}</style>b</td></tr></table>"
    [table] = extract_tables(html)
    assert texts(table) == [["a b"]]


def test_page_without_tables():
    assert extract_tables("<html><body><p>Down for maintenance</p></body></html>") == []
