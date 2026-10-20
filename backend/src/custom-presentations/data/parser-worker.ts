/** Trusted parser code runs in a bounded worker. Uploaded cells are never
 * executable code; formulas are read only from their existing cached values. */
export const dataParserWorker = String.raw`
const {parentPort,workerData}=require('node:worker_threads');
const fail=code=>{throw new Error(code)};
const clean=value=>value==null?'':value instanceof Date?value.toISOString().slice(0,10):typeof value==='object'?JSON.stringify(value):String(value);
function csv(text,delimiter){
  const rows=[];let row=[],cell='',quoted=false;
  for(let i=0;i<text.length;i++){
    const c=text[i];
    if(c==='"'){if(quoted&&text[i+1]==='"'){cell+='"';i++;}else if(quoted||!cell.length)quoted=!quoted;else cell+=c;}
    else if(!quoted&&(c===delimiter||c==='\n')){row.push(cell);cell='';if(c==='\n'){rows.push(row);row=[];}}
    else if(c!=='\r'||quoted)cell+=c;
    if(rows.length>10002||row.length>40||cell.length>20000)fail('data_too_large');
  }
  if(quoted)fail('data_invalid_quotes');
  row.push(cell);if(row.some(value=>value.trim()))rows.push(row);return rows;
}
function textTable(text){
  const lines=text.trim().split(/\r?\n/).filter(line=>line.trim()&&!/^\s*\|?[\s:|+-]+\|?\s*$/.test(line));
  if(lines.length<2)return [];
  const pairs=lines.map(line=>line.match(/^\s*([^:]{1,160})\s*:\s*(.+)$/));
  if(pairs.every(Boolean))return [['Показатель','Значение'],...pairs.map(pair=>[pair[1],pair[2]])];
  const candidates=['\t',';',',','|'];
  const ranked=candidates.map(delimiter=>{const parsed=csv(lines.slice(0,25).join('\n'),delimiter);const widths=parsed.map(row=>row.length).filter(n=>n>1);const width=widths.sort((a,b)=>widths.filter(n=>n===b).length-widths.filter(n=>n===a).length)[0]||0;return {delimiter,score:width>1?widths.filter(n=>n===width).length*10+Math.min(width,10):0};}).sort((a,b)=>b.score-a.score);
  if(ranked[0].score){let rows=csv(lines.join('\n'),ranked[0].delimiter);if(ranked[0].delimiter==='|')rows=rows.map(row=>{if(!row[0].trim())row.shift();if(!row.at(-1).trim())row.pop();return row;});const start=rows.findIndex((row,i)=>row.length>1&&rows[i+1]?.length===row.length);return start<0?[]:rows.slice(start);}
  const fixed=lines.map(line=>line.trim().split(/\s{2,}/));if(fixed.filter(row=>row.length>1).length>=2)return fixed;
  const simple=lines.map(line=>line.trim().split(/\s+/));if(simple[0].length>1&&simple.every(row=>row.length===simple[0].length)&&simple.slice(1).every(row=>row.slice(1).every(value=>/^[+−-]?\d+(?:[.,]\d+)?%?$/.test(value))))return simple;
  return [];
}
function delimitedTable(text,extension){
  const variants=(extension==='tsv'?['\t']:[';',',','\t','|']).map(delimiter=>{
    const rows=csv(text,delimiter),widths=rows.map(row=>row.length).filter(n=>n>1),counts=new Map();for(const width of widths)counts.set(width,(counts.get(width)||0)+1);
    const mode=[...counts].sort((a,b)=>b[1]-a[1])[0];return {rows,score:mode?mode[1]*10+Math.min(mode[0],9):0};
  }).sort((a,b)=>b.score-a.score);
  return variants[0].score?variants[0].rows:[];
}
function jsonTables(value,name,depth=0){
  if(depth>4)fail('data_invalid');
  if(Array.isArray(value)&&value.length){
    if(value.every(cell=>cell==null||typeof cell==='number'))return [{name,rows:[['Наблюдение','Значение'],...value.map((cell,i)=>[String(i+1),clean(cell)])]}];
    if(value.every(Array.isArray))return [{name,rows:value.map(row=>row.map(clean))}];
    if(value.every(row=>row&&typeof row==='object'&&!Array.isArray(row))){
      const keys=[...new Set(value.flatMap(row=>Object.keys(row)))];if(keys.length>40)fail('data_too_large');
      return [{name,rows:[keys,...value.map(row=>keys.map(key=>clean(Object.hasOwn(row,key)?row[key]:null)))]}];
    }
  }
  if(value&&typeof value==='object'&&!Array.isArray(value)){
    const rows=value.rows??value.data??value.records;
    if(Array.isArray(rows)&&Array.isArray(value.columns??value.headers)){
      const columns=(value.columns??value.headers).map(column=>column&&typeof column==='object'?{key:column.key??column.name??column.label,label:column.label??column.name??column.key}:{key:column,label:column});
      return [{name,rows:[columns.map(column=>clean(column.label)),...rows.map(row=>Array.isArray(row)?row.map(clean):columns.map(column=>clean(row?.[column.key])))]}];
    }
    const keys=Object.keys(value);
    if(keys.length&&keys.every(key=>value[key]==null||typeof value[key]!=='object'))return [{name,rows:[['Показатель','Значение'],...keys.map(key=>[key,clean(value[key])])]}];
    if(keys.length&&keys.every(key=>Array.isArray(value[key])&&value[key].every(cell=>cell==null||typeof cell!=='object'))){
      const length=Math.max(...keys.map(key=>value[key].length));if(length>10000)fail('data_too_large');
      return [{name,rows:[keys,...Array.from({length},(_,i)=>keys.map(key=>clean(value[key][i]))) ]}];
    }
    if(rows)return jsonTables(rows,name,depth+1);
    return keys.flatMap(key=>jsonTables(value[key],key,depth+1));
  }
  return [];
}
(async()=>{
 const bytes=Buffer.from(workerData.bytes),extension=workerData.extension;let tables=[];
 if(['xlsx','xls','xlsm','ods'].includes(extension)){
  if(bytes[0]===80&&bytes[1]===75){
   const {default:JSZip}=await import(workerData.zipModule),zip=await JSZip.loadAsync(bytes);
   const entries=Object.values(zip.files);if(entries.length>2500||entries.reduce((n,item)=>n+(item._data?.uncompressedSize||0),0)>60*1024*1024)fail('data_too_large');
  }
  const module=await import(workerData.xlsxModule),XLSX=module.default??module;
  const book=XLSX.read(bytes,{type:'buffer',cellDates:true,cellFormula:false,cellHTML:false,sheetRows:10002});
  if(book.SheetNames.length>12)fail('data_too_large');
  tables=book.SheetNames.map(name=>{
   const sheet=book.Sheets[name],range=XLSX.utils.decode_range(sheet['!fullref']??sheet['!ref']??'A1');
   if(range.e.r-range.s.r>10000||range.e.c-range.s.c>=40)fail('data_too_large');
   return {name,rows:XLSX.utils.sheet_to_json(sheet,{header:1,raw:true,defval:null,blankrows:false}).map(row=>row.map(clean))};
  });
 }else{
  let text=new TextDecoder(bytes[0]===255&&bytes[1]===254?'utf-16le':bytes[0]===254&&bytes[1]===255?'utf-16be':'utf-8').decode(bytes).replace(/^\uFEFF/,'');
  if(text.includes('\uFFFD'))text=new TextDecoder('windows-1251').decode(bytes);
  if(['json','jsonl','ndjson'].includes(extension)){
   let value;try{value=extension==='json'?JSON.parse(text):text.split(/\r?\n/).filter(line=>line.trim()).map(line=>JSON.parse(line));}catch{fail('data_invalid_json');}
   tables=jsonTables(value,workerData.name);
  }else if(extension==='xml'){
   // No DTD, entity expansion, network access or executable processing.
   if(/<!DOCTYPE|<!ENTITY/i.test(text))fail('data_invalid_xml');
   const module=await import(workerData.xmlModule),{XMLParser,XMLValidator}=module;
   if(XMLValidator.validate(text)!==true)fail('data_invalid_xml');
   let depth=0,maxDepth=0,nodes=0;
   for(const match of text.matchAll(/<([^>]+)>/g)){
    const tag=match[1];if(/^[!?]/.test(tag))continue;
    if(tag.startsWith('/'))depth--;else{nodes++;if(!tag.endsWith('/'))depth++;}
    maxDepth=Math.max(maxDepth,depth);if(maxDepth>24||nodes>250000)fail('data_too_large');
   }
   const parser=new XMLParser({ignoreAttributes:false,attributeNamePrefix:'',parseTagValue:false,parseAttributeValue:false,processEntities:false,trimValues:true});
   let value;try{value=parser.parse(text);}catch{fail('data_invalid_xml');}
   function unwrap(value,depth=0){
    if(depth>24)fail('data_too_large');
    if(value&&typeof value==='object'&&!Array.isArray(value)){
     const keys=Object.keys(value).filter(key=>!key.startsWith('?'));
     if(keys.length===1&&value[keys[0]]&&typeof value[keys[0]]==='object')return unwrap(value[keys[0]],depth+1);
    }
    return value;
   }
   tables=jsonTables(unwrap(value),workerData.name);
  }else if(['csv','tsv'].includes(extension))tables=[{name:workerData.name,rows:delimitedTable(text,extension)}];
  else {
   const blocks=text.split(/\n\s*\n/),parsed=blocks.map((block,index)=>({name:index?workerData.name+' · '+(index+1):workerData.name,rows:textTable(block),block}));
   const hasNumbers=table=>table.rows.slice(1).some(row=>row.some(cell=>/^[+−-]?\d+(?:[.,]\d+)?(?:\s*%)?$/.test(cell.trim())));
   // Source/version/URL prose can resemble semicolon-delimited records. Keep
   // it as provenance, never offer it as a second statistical table.
   const numeric=parsed.filter(table=>table.rows.length>1&&hasNumbers(table));
   const selected=numeric.length?parsed.filter(table=>table.rows.length>1&&(hasNumbers(table)||!/^\s*(?:Источник|Source|Версия|https?:)/im.test(table.block))):parsed.filter(table=>table.rows.length>1);
   const notes=parsed.filter(table=>!selected.includes(table)).map(table=>table.block).join('\n\n').slice(0,4000);
   tables=selected.map(({name,rows})=>({name,rows,...(notes?{sourceNotes:notes}:{})}));
  }
 }
 tables=tables.filter(table=>table.rows.length>1&&table.rows.some(row=>row.length>1));
 if(!tables.length)fail('data_no_table');
 if(tables.length>12||tables.some(table=>table.rows.length>10001||table.rows.some(row=>row.length>40))||tables.reduce((n,table)=>n+table.rows.reduce((m,row)=>m+row.length,0),0)>200000)fail('data_too_large');
 parentPort.postMessage({tables});
})().catch(error=>parentPort.postMessage({error:/^data_/.test(error.message)?error.message:'data_invalid'}));
`;
