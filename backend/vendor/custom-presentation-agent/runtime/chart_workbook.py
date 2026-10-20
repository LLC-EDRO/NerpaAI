"""Update chart-bound cells while retaining the original embedded XLSX package."""
import io
import posixpath
import re
import zipfile
from lxml import etree
from runtime.security import NS, xml, relationship_target

SHEET_NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
S = {'s': SHEET_NS}
REFERENCE = re.compile(r"^(?:'((?:[^']|'')+)'|([^'!\[\]]+))!\$?([A-Za-z]{1,3})\$?([1-9][0-9]*)(?::\$?([A-Za-z]{1,3})\$?([1-9][0-9]*))?$")

def column_number(name):
    result = 0
    for letter in name.upper():
        result = result * 26 + ord(letter) - 64
    return result

def column_name(number):
    result = ''
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result

def parse_reference(formula):
    match = REFERENCE.fullmatch(formula or '')
    if not match:
        raise ValueError('pptx_chart_workbook_reference_unsupported')
    quoted, plain, start_column, start_row, end_column, end_row = match.groups()
    sheet = quoted.replace("''", "'") if quoted is not None else plain
    start = (column_number(start_column), int(start_row))
    end = (column_number(end_column or start_column), int(end_row or start_row))
    if (not sheet or max(start[0], end[0]) > 16384 or max(start[1], end[1]) > 1048576
            or end[0] < start[0] or end[1] < start[1]
            or start[0] != end[0] and start[1] != end[1]):
        raise ValueError('pptx_chart_workbook_reference_unsupported')
    count = end[0] - start[0] + end[1] - start[1] + 1
    if count > 500:
        raise ValueError('pptx_chart_point_limit')
    cells = [(col, row) for row in range(start[1], end[1] + 1) for col in range(start[0], end[0] + 1)]
    return sheet, cells

class ChartWorkbook:
    def __init__(self, payload):
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            infos = archive.infolist()
            if len(infos) > 2000 or sum(info.file_size for info in infos) > 40 * 1024 * 1024:
                raise ValueError('pptx_embedded_archive_limit')
            if len({info.filename for info in infos}) != len(infos):
                raise ValueError('pptx_duplicate_parts')
            self.parts = {info.filename: archive.read(info) for info in infos if not info.is_dir()}
        self.book = xml(self.parts['xl/workbook.xml'])
        rels = {rel.get('Id'): rel for rel in xml(self.parts['xl/_rels/workbook.xml.rels'])}
        self.sheets = {}
        for sheet in self.book.findall('s:sheets/s:sheet', S):
            rel = rels.get(sheet.get('{%s}id' % NS['r']))
            if rel is None or rel.get('TargetMode') == 'External':
                raise ValueError('pptx_chart_workbook_reference_unsupported')
            part = relationship_target('xl/_rels/workbook.xml.rels', rel.get('Target', ''))
            self.sheets[sheet.get('name', '').casefold()] = (sheet.get('name'), part, xml(self.parts[part]))
        self.writes = {}
        self.changed = set()
        self.managed = None
        self.managed_bindings = {}

    def binding(self, formula, count=None, allow_formula=False):
        name, coords = parse_reference(formula)
        entry = self.sheets.get(name.casefold())
        if entry is None or count is not None and len(coords) != count:
            raise ValueError('pptx_chart_workbook_reference_unsupported')
        for col, row in coords:
            cell = entry[2].find(f's:sheetData/s:row[@r="{row}"]/s:c[@r="{column_name(col)}{row}"]', S)
            if not allow_formula and cell is not None and cell.find('s:f', S) is not None:
                # A computed source cell is not a replaceable data literal.
                raise ValueError('pptx_chart_workbook_formula_unsupported')
        return entry, coords

    def managed_binding(self, formula, source, coords, values):
        signature=(formula,tuple(values))
        if signature in self.managed_bindings:return self.managed_bindings[signature]
        if self.managed is None:
            names={entry[0].casefold() for entry in self.sheets.values()}
            name='Nerpa Data';number=2
            while name.casefold() in names:name=f'Nerpa Data {number}';number+=1
            part_number=1
            while f'xl/worksheets/nerpaChartData{part_number}.xml' in self.parts:part_number+=1
            part=f'xl/worksheets/nerpaChartData{part_number}.xml'
            sheet=etree.Element('{%s}worksheet'%SHEET_NS,nsmap={None:SHEET_NS})
            etree.SubElement(sheet,'{%s}dimension'%SHEET_NS,ref='A1')
            etree.SubElement(sheet,'{%s}sheetData'%SHEET_NS)
            sheets=self.book.find('s:sheets',S)
            rid='nerpaChartData'
            rels=xml(self.parts['xl/_rels/workbook.xml.rels'])
            while any(rel.get('Id')==rid for rel in rels):rid+='x'
            identity=max((int(s.get('sheetId')) for s in sheets),default=0)+1
            etree.SubElement(sheets,'{%s}sheet'%SHEET_NS,name=name,sheetId=str(identity),attrib={'{%s}id'%NS['r']:rid})
            etree.SubElement(rels,'{%s}Relationship'%NS['pr'],Id=rid,Type=NS['r']+'/worksheet',Target=posixpath.relpath(part,'xl'))
            self.parts['xl/_rels/workbook.xml.rels']=etree.tostring(rels,xml_declaration=True,encoding='UTF-8')
            types=xml(self.parts['[Content_Types].xml'])
            etree.SubElement(types,'{%s}Override'%NS['ct'],PartName='/'+part,ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml')
            self.parts['[Content_Types].xml']=etree.tostring(types,xml_declaration=True,encoding='UTF-8')
            self.managed=(name,part,sheet)
            self.sheets[name.casefold()]=self.managed
        entry=self.managed
        occupied=[column_number(re.sub(r'[0-9]+$', '',cell.get('r','A1'))) for cell in entry[2].findall('s:sheetData/s:row/s:c',S)]
        column=max(occupied,default=0)+1
        targets=[(column,i+1) for i in range(len(values))]
        for i,target in enumerate(targets):
            old=self.cell(source[2],*coords[min(i,len(coords)-1)],create=False)
            cell=self.cell(entry[2],*target)
            if old is not None:
                for attr,value in old.attrib.items():
                    if attr!='r':cell.set(attr,value)
        quoted="'"+entry[0].replace("'","''")+"'"
        column=column_name(column)
        formula=f'{quoted}!${column}$1' if len(values)==1 else f'{quoted}!${column}$1:${column}${len(values)}'
        result=(entry,targets,formula)
        self.managed_bindings[signature]=result
        return result

    def update(self, formula_node, values):
        entry, coords = self.binding(formula_node.text,allow_formula=True)
        name, part, sheet = entry
        computed=any((cell:=self.cell(sheet,col,row,create=False)) is not None and cell.find('s:f',S) is not None for col,row in coords)
        conflicts = any((part, col, row) in self.writes and self.writes[part, col, row] != value
                        for (col, row), value in zip(coords, values))
        if computed or conflicts or len(coords)!=len(values):
            # Excel frequently shares one X range between scatter series. New
            # series have independent X values; copy the conflicting binding to
            # a dedicated data worksheet rather than overwrite another. A
            # source formula is similarly retained, never evaluated/replaced.
            entry,coords,formula=self.managed_binding(formula_node.text,entry,coords,values)
            name,part,sheet=entry
            formula_node.text=formula
        for (col, row), value in zip(coords, values):
            cell = self.cell(sheet, col, row)
            for child in list(cell):
                if etree.QName(child).localname in ('v', 'is', 'f'): cell.remove(child)
            cell.attrib.pop('t', None)
            if isinstance(value, str):
                cell.set('t', 'inlineStr')
                inline=etree.Element('{%s}is'%SHEET_NS)
                cell.insert(next((i for i,node in enumerate(cell) if etree.QName(node).localname=='extLst'),len(cell)),inline)
                text = etree.SubElement(inline, '{%s}t' % SHEET_NS)
                text.text = value
                if value != value.strip(): text.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
            else:
                number=etree.Element('{%s}v'%SHEET_NS);number.text=str(value)
                cell.insert(next((i for i,node in enumerate(cell) if etree.QName(node).localname=='extLst'),len(cell)),number)
            self.writes[part, col, row] = value
        self.changed.add(part)
        dimension = sheet.find('s:dimension', S)
        if dimension is not None:
            addresses = [cell.get('r') for cell in sheet.findall('s:sheetData/s:row/s:c', S)]
            columns = [column_number(re.sub(r'[0-9]+$', '', address)) for address in addresses]
            rows = [int(re.sub(r'^[A-Z]+', '', address)) for address in addresses]
            if columns and rows: dimension.set('ref', f'{column_name(min(columns))}{min(rows)}:{column_name(max(columns))}{max(rows)}')

    @staticmethod
    def cell(sheet, col, row, create=True):
        data = sheet.find('s:sheetData', S)
        if data is None:
            raise ValueError('pptx_chart_workbook_reference_unsupported')
        row_node = data.find(f's:row[@r="{row}"]', S)
        if row_node is None:
            if not create: return None
            row_node = etree.Element('{%s}row' % SHEET_NS, r=str(row))
            data.insert(next((i for i, node in enumerate(data) if int(node.get('r', '0')) > row), len(data)), row_node)
        address = column_name(col) + str(row)
        cell = row_node.find(f's:c[@r="{address}"]', S)
        if cell is None and create:
            cell = etree.Element('{%s}c' % SHEET_NS, r=address)
            row_node.insert(next((i for i, node in enumerate(row_node) if column_number(re.sub(r'[0-9]+$', '', node.get('r', 'A1'))) > col), len(row_node)), cell)
        return cell

    def serialize(self):
        for _, part, sheet in self.sheets.values():
            if part in self.changed: self.parts[part] = etree.tostring(sheet, xml_declaration=True, encoding='UTF-8')
        calc = self.book.find('s:calcPr', S)
        if calc is None: calc = etree.SubElement(self.book, '{%s}calcPr' % SHEET_NS)
        calc.set('fullCalcOnLoad', '1')
        self.parts['xl/workbook.xml'] = etree.tostring(self.book, xml_declaration=True, encoding='UTF-8')
        result = io.BytesIO()
        with zipfile.ZipFile(result, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, payload in self.parts.items(): archive.writestr(name, payload)
        return result.getvalue()
