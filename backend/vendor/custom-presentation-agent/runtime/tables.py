"""Source table cells: preserve grids, merges and inherited typography during import."""
from runtime.text_frames import TemplateTextFrame as NativeTextFrame, TemplateParagraph as NativeParagraph, apply_bullet_properties
from runtime.security import xml

MAX_TABLE_ROWS = 10

def cell_frame(table, cell, item):
    style = cell.effective_style
    frame = NativeTextFrame(source_element_id=f'{item.source_object_id}:{cell.row}:{cell.col}', source_fingerprint=str((item.raw_xml_ref or {}).get('sha256') or ''),
        width_emu=sum(w or 0 for w in table.grid_column_widths_emu[cell.col:cell.col+cell.col_span]),
        height_emu=sum(r.height_emu or 0 for r in table.rows[cell.row:cell.row+cell.row_span]))
    for key in ('left_emu','right_emu','top_emu','bottom_emu'):
        if cell.margins.get(key) is not None: setattr(frame,key,cell.margins[key])
    full = item.geometry_full
    # Table grid sizes are local coordinates and transform with the entire group.
    for p in cell.rich_text.paragraphs if cell.rich_text else []:
        run = next((r for r in p.runs if r.text.strip()),None)
        font = run.effective_style if run else p.default_style
        prop=p.properties
        def spacing(name, default):
            value=getattr(prop,name)
            return (getattr(prop,name+'_unit') or 'percent',value) if value is not None else default
        paragraph=NativeParagraph(has_text=bool(''.join(r.text for r in p.runs).strip()),
            font_family=(font.font_family if font else None) or style.font_family,
            font_size_pt=(font.font_size_pt if font else None) or style.font_size_pt or 18,
            bold=bool((font.bold if font else False) or style.font_weight==700),italic=bool((font.italic if font else False) or style.italic),
            margin_left_emu=prop.margin_left_emu or 0,margin_right_emu=prop.margin_right_emu or 0,indent_emu=prop.indent_emu or 0,
            line_spacing=spacing('line_spacing',('percent',100)),space_before=spacing('space_before',('points',0)),space_after=spacing('space_after',('points',0)))
        if p.bullet and p.bullet.type not in (None,'none'):
            # Only admit lists whose actual paragraph XML we can measure.
            if not prop.raw_xml or not apply_bullet_properties(paragraph, xml(prop.raw_xml.encode())) or not paragraph.bullet_text:
                paragraph.reason_codes.append('table_bullet_unsupported')
        frame.paragraphs.append(paragraph)
    if not frame.paragraphs: frame.reason_codes.append('table_font_unresolved')
    return frame

def table_slots(table,item,box):
    for row in table.rows:
        for physical_index,cell in enumerate(row.cells):
            if cell.h_merge or cell.v_merge: continue
            frame=cell_frame(table,cell,item)
            style=cell.effective_style
            paragraph=frame.paragraphs[0] if frame.paragraphs else None
            size=paragraph.font_size_pt if paragraph and paragraph.font_size_pt else 20
            original=cell.text
            # OOXML may omit merge-continuation cells. Geometry uses logical columns,
            # but replacement must address the physical <a:tc> in the source row.
            yield dict(key=f's{item.shape_id}_r{cell.row}_c{cell.col}',shapeId=item.shape_id,cell=[cell.row,physical_index],
                role='table_header' if cell.row==0 else 'table_cell',text=original[:1800],maxChars=max(8,min(300,int(frame.width_emu/12700/max(1,size*.62))*max(1,int(frame.height_emu/12700/(size*1.35))))),
                x=box['x']+sum(w or 0 for w in table.grid_column_widths_emu[:cell.col])/12700,y=box['y']+sum(r.height_emu or 0 for r in table.rows[:cell.row])/12700,
                w=frame.width_emu/12700,h=frame.height_emu/12700,font=(paragraph.font_family if paragraph else None) or 'Arial',size=size,
                bold=bool(paragraph and paragraph.bold),color=style.text_color or '#202020',align='left',
                defaultFontSize=18 if getattr(cell,'rich_text',None) and any(not ((next((r.effective_style.font_size_pt for r in p.runs if r.text.strip()),None)) or (p.default_style and p.default_style.font_size_pt) or style.font_size_pt) for p in cell.rich_text.paragraphs) else None),frame
