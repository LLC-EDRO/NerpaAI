"""Native, empty data capacity for a measured uploaded-template content region.

The labels below describe an example grid, never evidence for a presentation.
Actual columns/records are selected by the table planner and replaced by the
ordinary native-cell writer. No raster, opaque embedded object or extra theme
relationship is needed for this editable DrawingML table.
"""
import math
import re
from runtime.security import NS
from runtime.drawingml import node, geometry, solid
from runtime.tables import MAX_TABLE_ROWS

def _color(value):
    if not isinstance(value, str) or not re.fullmatch(r'#[0-9A-Fa-f]{6}', value):
        raise ValueError('pptx_data_table_style')
    return value

def _partition(total, count):
    """Integer EMU lengths must add up to the exact frame extent."""
    quotient, remainder = divmod(total, count)
    return [quotient + (index < remainder) for index in range(count)]

def add_data_table(tree, shape_id, box, style, columns=4, data_rows=3):
    """Append one genuine ``a:tbl`` and return its table node.

    All geometry is in points. The caller owns placement and source-artwork
    preservation; this helper touches only the newly appended graphic frame.
    """
    if type(shape_id) is not int or not 1 <= shape_id < 2**32 or tree.xpath('.//p:cNvPr[@id=$id]', namespaces=NS, id=str(shape_id)):
        raise ValueError('pptx_data_table_identity')
    if type(columns) is not int or not 2 <= columns <= 8 or type(data_rows) is not int or not 1 <= data_rows < MAX_TABLE_ROWS:
        raise ValueError('pptx_data_table_grid')
    if not isinstance(box, dict) or any(type(box.get(key)) not in (int, float) or not math.isfinite(box[key]) for key in ('x', 'y', 'w', 'h')):
        raise ValueError('pptx_data_table_geometry')
    if min(box['x'], box['y']) < 0 or min(box['w'], box['h']) <= 0 or max(box['x'] + box['w'], box['y'] + box['h']) * 12700 >= 2**31:
        raise ValueError('pptx_data_table_geometry')
    if not isinstance(style, dict):
        raise ValueError('pptx_data_table_style')
    font = style.get('font')
    size = style.get('bodySize', 18)
    if not isinstance(font, str) or not font.strip() or len(font) > 200 or any(ord(character) < 32 for character in font) or type(size) not in (int, float) or not math.isfinite(size) or not 10 <= size <= 40:
        raise ValueError('pptx_data_table_style')
    colors = {key: _color(style.get(key)) for key in ('ink', 'accent', 'onAccent', 'surface')}
    widths = _partition(round(box['w'] * 12700), columns)
    heights = _partition(round(box['h'] * 12700), data_rows + 1)
    # An undersized insertion is not a capability. Reject it instead of
    # advertising a grid whose ordinary cell writer could never fit one line.
    if min(widths) / 12700 < size * 2 + 12 or min(heights) / 12700 < size * 1.35 + 8:
        raise ValueError('pptx_data_table_capacity')

    frame = node(tree, 'p:graphicFrame')
    nonvisual = node(frame, 'p:nvGraphicFramePr')
    node(nonvisual, 'p:cNvPr', id=shape_id, name='Nerpa editable data table')
    node(nonvisual, 'p:cNvGraphicFramePr')
    node(nonvisual, 'p:nvPr')
    geometry(frame, box, 'p:xfrm')
    graphic = node(node(frame, 'a:graphic'), 'a:graphicData', uri='http://schemas.openxmlformats.org/drawingml/2006/table')
    table = node(graphic, 'a:tbl')
    node(table, 'a:tblPr', firstRow=1, bandRow=0)
    grid = node(table, 'a:tblGrid')
    for width in widths:
        node(grid, 'a:gridCol', w=width)
    headings = ('Объект', 'Свойство', 'Описание', 'Комментарий', 'Признак', 'Условие', 'Результат', 'Примечание')
    for row_index, height in enumerate(heights):
        row = node(table, 'a:tr', h=height)
        for column in range(columns):
            cell = node(row, 'a:tc')
            body = node(cell, 'a:txBody')
            body_properties = node(body, 'a:bodyPr', wrap='square', anchor='ctr')
            node(body_properties, 'a:noAutofit')
            node(body, 'a:lstStyle')
            paragraph = node(body, 'a:p')
            paragraph_properties = node(paragraph, 'a:pPr', algn='l', marL=0, indent=0)
            node(node(paragraph_properties, 'a:lnSpc'), 'a:spcPct', val=110000)
            node(paragraph_properties, 'a:buNone')
            run = node(paragraph, 'a:r')
            text_properties = node(run, 'a:rPr', lang='ru-RU', sz=round(size * 100), b=int(row_index == 0))
            solid(text_properties, colors['onAccent' if row_index == 0 else 'ink'])
            for alphabet in ('a:latin', 'a:ea', 'a:cs'):
                node(text_properties, alphabet, typeface=font)
            label = headings[column] if row_index == 0 else ('Объект ' + chr(0x410 + row_index - 1) if column == 0 else 'Описание')
            node(run, 'a:t').text = label
            properties = node(cell, 'a:tcPr', marL=76200, marR=76200, marT=50800, marB=50800, anchor='ctr')
            for edge in ('L', 'R', 'T', 'B'):
                solid(node(properties, 'a:ln' + edge, w=6350), colors['accent'])
            solid(properties, colors['accent' if row_index == 0 else 'surface'])
    return table
