"""Adapt the imported parser/analyzer without changing their complete JSON contracts."""
import json
import hashlib
import gc
from pydantic import BaseModel
from types import SimpleNamespace
from runtime.model_store import write_model
from app.presentation.parser import PresentationParser
from app.presentation.template import TemplateAnalyzer, TemplateAnalyzerConfig
from runtime.text_frames import source_text_frame, TemplateTextFitter as NativeTextFitter
from runtime.tables import table_slots, cell_frame
from runtime.charts import chart_spec
from runtime.security import read_package, slide_order, xml, NS
from runtime.fonts import choose_fonts, recover_marker_fonts, prepare_font_copy, font_report, materialize_table_fonts
from runtime.sample_furniture import is_sample_furniture
from runtime.preflight import layout_readiness
from runtime.shape_text_geometry import ShapeTextGeometry
from runtime.textbox_repair import recover_textbox_bounds
from runtime.table_repair import recover_table_rows
from runtime.empty_diagrams import empty_diagram_nodes
from runtime.typography import inherited_text_color,inherited_vertical_alignment
from runtime.text_protection import retain_text_artwork
from runtime.drawn_tables import recover_drawn_tables
from runtime.embedded_objects import embedded_preview_records, protected_preview_shape_ids
from runtime.optional_svg import optional_svg_recoveries
from runtime.shape_ids import recover_shape_ids

RECOVERY_VERSION = 22

def flatten(objects):
    for item in objects:
        yield item
        yield from flatten(item.children)

def text_of(item):
    return '\n'.join(''.join(r.text for r in p.runs) for p in item.rich_text.paragraphs) if item.rich_text else ''

def restore_native_order(model, order):
    """Retain parser IDs and apply the original presentation order to all records."""
    positions={part:index for index,part in enumerate(order)}
    indices={slide.slide_id:positions[slide.source_part] for slide in model.slides}
    seen=set()
    def visit(value):
        if isinstance(value,(BaseModel,SimpleNamespace,dict,list,tuple)):
            if id(value) in seen:return
            seen.add(id(value))
        if isinstance(value,(BaseModel,SimpleNamespace)):
            identity=getattr(value,'slide_id',None)
            if hasattr(value,'slide_index') and identity in indices:value.slide_index=indices[identity]
            for child in (dict(value) if isinstance(value,BaseModel) else vars(value)).values():visit(child)
        elif isinstance(value,dict):
            if value.get('slide_id') in indices and 'slide_index' in value:value['slide_index']=indices[value['slide_id']]
            for child in value.values():visit(child)
        elif isinstance(value,(list,tuple)):
            for child in value:visit(child)
    visit(model)
    model.slides.sort(key=lambda slide:positions[slide.source_part])

def analyze(source, folder, _original_sha=None, _derive_data_layouts=True, _original_parts=None):
    parts = read_package(source.read_bytes())
    order = slide_order(parts)
    embedded_previews = embedded_preview_records(parts)
    optional_svg = optional_svg_recoveries(parts)
    parts, drawn_tables = recover_drawn_tables(parts)
    parts, shape_id_repairs = recover_shape_ids(parts)
    prepared = prepare_font_copy(parts, folder, []) if drawn_tables or embedded_previews or optional_svg or shape_id_repairs else source
    model = PresentationParser().parse(prepared)
    if not model.passed:
        raise ValueError('pptx_parse_failed')
    original_sha = _original_sha or hashlib.sha256(source.read_bytes()).hexdigest()
    originals = _original_parts if _original_parts is not None else set(order)
    write_model(folder / 'parser.json', model)
    requirements = {}
    for slide in model.slides:
        for item in flatten(slide.objects):
            if item.rich_text and item.text_frame and (item.has_text_content or item.placeholder_type):
                for paragraph in source_text_frame(item).paragraphs:
                    if paragraph.font_family:
                        requirements.setdefault(paragraph.font_family,set()).add((paragraph.bold,paragraph.italic))
    shapes={s.source_object_id:s for slide in model.slides for s in flatten(slide.objects)}
    for table in model.tables:
        for row in table.rows:
            for cell in row.cells:
                if cell.effective_style.font_family:
                    requirements.setdefault(cell.effective_style.font_family,set()).add((cell.effective_style.font_weight==700,bool(cell.effective_style.italic)))
                shape=shapes.get(table.linked_object_id)
                if shape:
                    for paragraph in cell_frame(table,cell,shape).paragraphs:
                        if paragraph.font_family:requirements.setdefault(paragraph.font_family,set()).add((paragraph.bold,paragraph.italic))
    substitutions = choose_fonts(requirements)
    prepared_sha = None
    # Each recovery uses the effective result of the previous one: a missing
    # source face must not prevent measuring a recoverable degenerate textbox.
    if substitutions:
        parts=materialize_table_fonts(parts,model,substitutions)
        prepared = prepare_font_copy(parts, folder, substitutions)
        del model
        gc.collect()
        model = PresentationParser().parse(prepared)
        if not model.passed: raise ValueError('pptx_parse_failed')
        parts = read_package(prepared.read_bytes())
    parts, bullet_substitutions = recover_marker_fonts(parts, model)
    if bullet_substitutions:
        prepared = prepare_font_copy(parts, folder, [])
        del model
        gc.collect()
        model = PresentationParser().parse(prepared)
        if not model.passed: raise ValueError('pptx_parse_failed')
    parts, textbox_repairs = recover_textbox_bounds(parts, [item for slide in model.slides for item in flatten(slide.objects)])
    if textbox_repairs:
        prepared = prepare_font_copy(parts, folder, [])
        del model
        gc.collect()
        model = PresentationParser().parse(prepared)
        if not model.passed: raise ValueError('pptx_parse_failed')
    parts, table_repairs = recover_table_rows(parts, model)
    if table_repairs:
        prepared = prepare_font_copy(parts, folder, [])
        del model
        gc.collect()
        model = PresentationParser().parse(prepared)
        if not model.passed: raise ValueError('pptx_parse_failed')
    if embedded_previews or optional_svg or drawn_tables or shape_id_repairs or substitutions or bullet_substitutions or textbox_repairs or table_repairs:
        prepared_sha = hashlib.sha256(prepared.read_bytes()).hexdigest()
        parts = read_package(prepared.read_bytes())
    # The upstream parser orders part names. Respect actual PowerPoint slide ordering.
    restore_native_order(model, order)
    template = TemplateAnalyzer(config=TemplateAnalyzerConfig(semantic_mode='off', vision_review_mode='off')).analyze(presentation_model=model).template_model
    write_model(folder / 'effective-parser.json', model)
    width = model.dimensions.width_emu / 12700
    height = model.dimensions.height_emu / 12700
    from runtime.page_numbers import pagination_padding,pagination_shape_ids
    page_roots={s.slide_id:xml(parts[s.source_part]) for s in model.slides}
    pagination=pagination_padding(page_roots.values(),width,height)
    source_ordinals={slide.slide_id:index+1 for index,slide in enumerate(model.slides)}
    for assignment in template.slide_assignments:
        root=page_roots.get(assignment.slide_id)
        if root is None:continue
        markers=pagination_shape_ids(root,width,height,source_ordinals[assignment.slide_id],pagination)
        for role in assignment.role_assignments:
            if role.source_level=='slide' and role.source_open_xml_shape_id in markers:role.role='page_number'
    write_model(folder / 'analyzer.json', template)
    layouts, warnings, frames = [], [], {}
    tables={t.linked_object_id:t for t in model.tables if t.source_level=='slide'}
    assignments = {a.slide_id: {r.source_open_xml_shape_id: r for r in a.role_assignments if r.source_level == 'slide'} for a in template.slide_assignments}
    fitter = NativeTextFitter()
    text_geometry = ShapeTextGeometry(parts)
    for slide in model.slides:
        frames[slide.slide_id]={}
        roles = assignments.get(slide.slide_id, {})
        slots, pictures, problems, charts = [], [], [], []
        empty_nodes = empty_diagram_nodes(xml(parts[slide.source_part]))
        static_previews = protected_preview_shape_ids(xml(parts[slide.source_part]))
        if empty_nodes:
            problems.append('Пустая схема содержит соединённые блоки без доступных текстовых полей. Для заполнения автоматически выбирается другой содержательный макет этого шаблона.')
        for item in flatten(slide.objects):
            if item.hidden or item.shape_id is None:
                continue
            role = roles.get(item.shape_id)
            geom = item.geometry_full.absolute_bbox if item.geometry_full else item.geometry
            if geom is None:
                continue
            box = dict(x=(geom.x_emu or 0)/12700, y=(geom.y_emu or 0)/12700, w=(geom.width_emu or 0)/12700, h=(geom.height_emu or 0)/12700)
            if box['w'] <= 0 or box['h'] <= 0:
                continue
            if item.object_kind in ('smartart', 'embedded_object'):
                problems.append('Слайд содержит SmartArt или встроенный объект: сохранён в разборе, автоматическое заполнение этого макета пока недоступно.')
            if item.object_kind == 'chart':
                try: charts.append({**chart_spec(item,parts),**box})
                except ValueError as error:
                    reasons={
                        'pptx_chart_type_unsupported':'Тип исходной диаграммы пока не поддерживает автоматическое обновление.',
                        'pptx_chart_series_limit':'Автоматическое обновление поддерживает не более 6 рядов диаграммы.',
                        'pptx_chart_point_limit':'Автоматическое обновление поддерживает не более 500 точек в каждом ряду.',
                        'pptx_chart_scale_unsupported':'В исходной диаграмме некорректная или неподдерживаемая числовая шкала.',
                        'pptx_chart_workbook_reference_unsupported':'Ссылки исходной диаграммы на данные книги Excel не удалось однозначно сопоставить.',
                        'pptx_chart_labels_unsupported':'Пользовательские подписи исходной диаграммы не удалось однозначно связать с её данными.',
                    }
                    problems.append(reasons.get(str(error),'Неполные или неподдерживаемые исходные данные диаграммы.')+' Исходная диаграмма сохранена; макет доступен только для просмотра.')
            if item.object_kind == 'picture' and item.shape_id not in static_previews and role and role.role not in ('logo', 'decoration', 'background', 'footer', 'page_number') and box['w'] * box['h'] > width * height * .035:
                pictures.append((item, box))
            if item.object_kind == 'table':
                table=tables.get(item.source_object_id)
                if not table: problems.append('Не удалось сопоставить ячейки таблицы с исходным объектом.')
                else:
                    for slot,frame in table_slots(table,item,box):
                        slots.append(slot)
                        frames[slide.slide_id][slot['key']]=frame.model_dump()
                        probes=fitter.probe(frame)
                        if any(probe.status=='unverifiable' for probe in probes): problems.append('Не удалось проверить шрифт или геометрию ячеек таблицы.')
            if item.rich_text and item.object_kind == 'shape' and item.placeholder_type not in ('dt', 'sldNum'):
                original = text_of(item)
                if is_sample_furniture(original):
                    continue
                if retain_text_artwork(original, role.role if role else None):
                    continue
                if not original.strip() and item.placeholder_type not in ('title', 'ctrTitle', 'body', 'subTitle', 'obj'):
                    continue
                frame = source_text_frame(item, text_geometry)
                frames[slide.slide_id][f's{item.shape_id}']=frame.model_dump()
                probes = fitter.probe(frame)
                if any(probe.status == 'unverifiable' for probe in probes):
                    if any('font' in reason for probe in probes for reason in probe.reason_codes):
                        problems.append('Шрифт текстового поля недоступен или не содержит нужных символов. Установите шрифты шаблона на сервере.')
                    else:
                        problems.append('В текстовом поле есть неподдерживаемые параметры оформления. Макет сохранён для просмотра.')
                style = item.text_style
                size = frame.paragraphs[0].font_size_pt if frame.paragraphs else None
                size = size or (style.font_size_pt if style and style.font_size_pt else 20)
                # Advisory budget only; every generated/edit payload is physically measured again.
                capacity = min(1800, max(1, int(max(1, box['w']-14)/max(1,size*.62)) * max(1, int(max(1,box['h']-7)/(size*1.35)))))
                slot_role = role.role if role and role.role != 'decoration' else 'body'
                slots.append(dict(key=f's{item.shape_id}', shapeId=item.shape_id, role=slot_role, text=original[:1800], maxChars=capacity,
                                  **box, verticalAlign=inherited_vertical_alignment(item), font=frame.paragraphs[0].font_family if frame.paragraphs else 'Arial', size=size,
                                  bold=bool(style and style.bold), color=inherited_text_color(item, parts) or (style.color if style else None) or '#202020', align={'ctr':'center','r':'right','center':'center','right':'right'}.get(item.rich_text.paragraphs[0].alignment if item.rich_text.paragraphs else None,'left')))
        picture = max(pictures, key=lambda p: p[1]['w'] * p[1]['h'], default=None)
        if not slots:
            visible = [item for item in flatten(slide.objects) if not item.hidden]
            image_only = len([item for item in visible if item.object_kind == 'picture']) == 1 and not any(text_of(item).strip() for item in visible)
            problems.append('Слайд сохранён одной картинкой: отдельных редактируемых текстовых полей нет.' if image_only else 'На слайде нет доступных для заполнения текстовых полей.')
        if len(slots)>80: problems.append('На слайде более 80 полей. Разделите слишком плотный макет.')
        layouts.append(dict(id=slide.slide_id, index=slide.slide_index, part=slide.source_part,
                            name=(slots[0]['text'][:90] if slots else '') or f'Слайд {slide.slide_index+1}', slots=slots, charts=charts,
                            **(dict(imageShapeId=picture[0].shape_id, imageBox=picture[1],imageAspectRatio=(picture[0].geometry_full.local_bbox.width_emu/picture[0].geometry_full.local_bbox.height_emu) if picture[0].geometry_full and picture[0].geometry_full.local_bbox and picture[0].geometry_full.local_bbox.height_emu else picture[1]['w']/picture[1]['h']) if picture else {}),
                            visuals=dict(unlabelledShapes=sum(1 for obj in flatten(slide.objects) if not obj.hidden and obj.object_kind in ('shape','connector') and not text_of(obj).strip())),
                            warnings=list(dict.fromkeys(problems)), usable=bool(slots) and not problems and len(slots) <= 80))
        layouts[-1].update(layout_readiness(layouts[-1], frames[slide.slide_id], fitter))
        # A valid package with ordinary editable content can be rebuilt when
        # its original frames cannot be measured. Unsupported native objects
        # remain disabled rather than being silently dropped by reconstruction.
        descendants = list(flatten(slide.objects))
        supported = all(item.object_kind in ('group','shape','picture','table','chart','connector','line') for item in descendants)
        supported = supported and len(charts) == sum(item.object_kind == 'chart' for item in descendants)
        if not layouts[-1]['usable'] and slots and len(slots)<=80 and supported:
            layouts[-1]['requiresRebuild'] = True
            layouts[-1]['usable'] = True
        from runtime.vector_charts import candidates
        graphics=candidates(xml(parts[slide.source_part]),slots)
        if graphics:
            layouts[-1]['vectorCharts']=graphics
            layouts[-1]['requiresRebuild']=True

    warnings = list(dict.fromkeys(p for l in layouts for p in l['warnings']))
    if embedded_previews:
        warnings.append('Встроенные объекты сохранены как изображения. Их оформление сохранено; содержимое этих объектов нельзя редактировать в генераторе.')
    if optional_svg:
        warnings.append('Недоступные дополнительные SVG-версии изображений пропущены; сохранены оригинальные растровые изображения из файла.')
    colors=[c.value for c in sorted(model.color_usage_metrics,key=lambda c:c.occurrences,reverse=True) if c.value.startswith('#')][:8]
    style_profile=dict(colors=colors,backgrounds=list(dict.fromkeys(s.background.color for s in model.slides if s.background and s.background.color)),fonts=model.theme.fonts if model.theme else [])
    for layout in layouts:
        layout['drawnTableShapeIds']=[t['shapeId'] for t in drawn_tables if t['part']==layout['part']]
    data = dict(sha256=original_sha, recoveryVersion=RECOVERY_VERSION, width=width, height=height, layouts=layouts, warnings=warnings, parserVersion=model.parser.agent_version,styleProfile=style_profile,
                fontSubstitutions=substitutions, bulletFontSubstitutions=bullet_substitutions, textboxRepairs=textbox_repairs, tableRowRepairs=table_repairs, drawnTableRepairs=drawn_tables, shapeIdRepairs=shape_id_repairs, embeddedObjectPreviews=embedded_previews, optionalSvgFallbacks=optional_svg, fontReport=font_report(requirements), **(dict(preparedSha256=prepared_sha) if prepared_sha else {}))
    from runtime.data_layouts import append_data_layouts, records as data_layout_records
    if _derive_data_layouts:
        def data_object(item):
            return dict(shape_id=item.shape_id,object_kind=item.object_kind,hidden=item.hidden,
                        placeholder_type=item.placeholder_type,geometry_full=item.geometry_full.model_dump() if item.geometry_full else None,
                        geometry=item.geometry.model_dump() if item.geometry else None,children=[data_object(child) for child in item.children])
        # Only measured geometry/roles are needed; do not duplicate rich text,
        # XML styles and media records from a potentially large parser model.
        model_data=dict(slides=[dict(slide_id=slide.slide_id,objects=[data_object(item) for item in slide.objects]) for slide in model.slides])
        analyzer_data=dict(slide_assignments=[dict(slide_id=assignment.slide_id,role_assignments=[role.model_dump() for role in assignment.role_assignments]) for assignment in template.slide_assignments])
        prepared_parts, added = append_data_layouts(parts,data,model_data,analyzer_data)
        if added:
            derived_source=prepare_font_copy(prepared_parts,folder,[])
            result=analyze(derived_source,folder,_original_sha=original_sha,_derive_data_layouts=False,_original_parts=originals)
            # The source substitutions remain useful to the user even though
            # the prepared file already contains their resolved font faces.
            for key in ('fontSubstitutions','bulletFontSubstitutions','textboxRepairs','tableRowRepairs','drawnTableRepairs','shapeIdRepairs'):
                result[key]=data[key]+[item for item in result[key] if item not in data[key]]
            result['fontReport']=data['fontReport']
            result['preparedSha256']=hashlib.sha256(derived_source.read_bytes()).hexdigest()
            (folder/'analysis.json').write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
            return result
    derivatives={item['part']:item for item in data_layout_records(parts) if item['part'] not in originals}
    for layout in layouts:
        item=derivatives.get(layout['part'])
        if item:
            layout.update(derivedMediaKind=item['kind'],derivedSourceLayoutId=item['sourceLayoutId'],derivedDataLayoutVersion=1)
            if item['chartType']:
                layout.update(derivedChartType=item['chartType'],derivedSeriesCount=item['seriesCount'])
            if item['kind']=='text':
                for role in ('title','body'):
                    for slot in layout['slots']:
                        if slot['shapeId']==item[role+'ShapeId']:
                            slot['role']=role
                layout['derivedTextShapeIds']={role:item[role+'ShapeId'] for role in ('title','body')}
            layout['name']={'text':'Заголовок и содержание','table':'Таблица сравнения','chart':'График по данным','image':'Иллюстрация из материала'}[item['kind']]
    if _original_sha:
        data['preparedSha256']=hashlib.sha256(source.read_bytes()).hexdigest()
    for layout in layouts:
        layout["sourceOriginalLayout"] = layout["part"] in originals
    (folder / 'analysis.json').write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    (folder / 'frames.json').write_text(json.dumps(frames,ensure_ascii=False),encoding='utf-8')
    return data
