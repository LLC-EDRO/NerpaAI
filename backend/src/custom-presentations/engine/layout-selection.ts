import type {Layout} from './domain.js';
import {regularTables, maxTableRows} from './source-tables.js';
import {nativeChartCopySchema,nativeChartIssues,isNativeXYChart,type NativeChartCopy} from './native-charts.js';
import {narrativeLayoutCapabilities} from './narrative-layouts.js';

/** Capabilities come from parsed OOXML objects, never a slide name or preview. */
export function layoutEditability(layout:Layout) {
  const nativeIds=[...new Set(layout.slots.filter(s=>s.cell).map(s=>s.shapeId))];
  const adaptable=regularTables(layout);
  const converted=new Set<number>(layout.drawnTableShapeIds || []);
  return {
    nativeTables:nativeIds.filter(id=>!converted.has(id)).length,
    recoveredEditableTables:nativeIds.filter(id=>converted.has(id)).length,
    nativeCharts:layout.charts.length,
    staticVectorCharts:(layout.vectorCharts || []).length,
    textFields:layout.slots.filter(s=>!s.cell).length,
    tables:adaptable.map(t=>({shapeId:t.shapeId,canResizeRows:true,canReduceColumns:true,maxTotalRows:maxTableRows,maxDataRows:t.maxDataRows,columns:t.columnCount})),
    graphicDataEditable:layout.charts.length>0 || nativeIds.length>0,
    // A graphic with no table/chart object must not be advertised as data-editable.
    unboundArtwork:layout.visuals?.unlabelledShapes || 0,
  };
}

export function preferEditableLayouts(layouts:Layout[]) {
  const rank=(l:Layout)=>{
    const c=layoutEditability(l);
    return (c.nativeCharts || c.nativeTables ? 0 : c.recoveredEditableTables ? 1 : c.textFields ? 2 : 3) +
      (narrativeLayoutCapabilities(l).automaticContentEligible?0:3) + (l.requiresRebuild?4:0);
  };
  return [...layouts].sort((a,b)=>rank(a)-rank(b));
}

type SourceRecord=Record<string,unknown>;
const sourceRecord=(value:unknown):SourceRecord|undefined=>value!==null&&typeof value==='object'&&!Array.isArray(value)?value as SourceRecord:undefined;

/** Only unchanged, extracted blocks can create an automatic requirement. The
 * host omits blocks after a text edit; instructions, research wishes and the
 * template's example values never become factual evidence here. */
export function sourceMediaRequirements(layouts:Layout[],document:{blocks?:unknown[]}|undefined,interiorSlides:number){
  const tables:Array<{id:string;rows:string[][]}>=[];
  const charts:Array<{id:string;data:NativeChartCopy;xyAllowed:boolean}>=[];
  const addChart=(id:string,data:unknown,xyAllowed=false)=>{
    const parsed=nativeChartCopySchema.safeParse(data);
    if(parsed.success&&parsed.data.series.every(series=>'values' in series?series.values.length>=2:series.points.length>=2))charts.push({id,data:parsed.data,xyAllowed});
  };
  for(const value of document?.blocks||[]){
    const block=sourceRecord(value);
    if(!block||typeof block.id!=='string'||!block.id)continue;
    if(block.type==='table'&&Array.isArray(block.rows)){
      const rows:string[][]=[];
      for(const rawRow of block.rows){
        if(!Array.isArray(rawRow)){rows.length=0;break;}
        const cells=rawRow.map(sourceRecord);
        if(cells.some((cell,index)=>!cell||typeof cell.text!=='string'||!cell.text.trim()||cell.columnIndex!==index||
          (cell.colSpan!==undefined&&cell.colSpan!==1)||(cell.rowSpan!==undefined&&cell.rowSpan!==1))){rows.length=0;break;}
        rows.push(cells.map(cell=>(cell!.text as string).trim()));
      }
      if(rows.length<3||rows[0]!.length<2||rows.some(row=>row.length!==rows[0]!.length)||
        new Set(rows.slice(1).map(row=>JSON.stringify(row))).size<2)continue;
      tables.push({id:block.id,rows});
      // A single numeric property across named records is a supported series.
      // Never combine different columns into shared units without evidence.
      const categories=rows.slice(1).map(row=>row[0]!);
      for(let column=1;column<rows[0]!.length;column++){
        const rawNumbers=rows.slice(1).map(row=>row[column]!.replace(/\u2212/g,'-').replace(',','.'));
        if(rawNumbers.some(text=>!/^[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?$/.test(text)))continue;
        addChart(block.id,{title:'',categories,series:[{name:rows[0]![column],values:rawNumbers.map(Number)}],evidence:[]});
      }
    }else if(block.type==='chart'&&Array.isArray(block.series)&&block.series.length){
      const series=block.series.map(sourceRecord);
      if(series.some(item=>!item||!Array.isArray(item.categories)||!Array.isArray(item.values)))continue;
      const categories=series[0]!.categories as unknown[];
      if(series.some(item=>JSON.stringify(item!.categories)!==JSON.stringify(categories)))continue;
      addChart(block.id,{title:'',categories,series:series.map((item,index)=>({name:item!.name||`Ряд ${index+1}`,values:item!.values})),evidence:[]},true);
    }
  }
  const usable=layouts.filter(layout=>layout.usable&&!layout.requiresRebuild&&narrativeLayoutCapabilities(layout).automaticContentEligible);
  const compatibleChart=(layout:Layout)=>layout.charts.length>0&&layout.charts.every(spec=>charts.some(chart=>{
    if(!isNativeXYChart(spec))return nativeChartIssues(spec,chart.data).length===0;
    // An extracted chart preserves numeric X values in categories. Textual
    // categories cannot become invented X coordinates for scatter diagrams.
    if(!chart.xyAllowed||!('categories' in chart.data))return false;
    const categories=chart.data.categories.map(text=>text.trim().replace(/\u2212/g,'-').replace(',','.'));
    if(categories.some(text=>!/^[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?$/.test(text)))return false;
    const xy=nativeChartCopySchema.safeParse({kind:'xy',title:'',evidence:[],series:chart.data.series.map(series=>({name:series.name,
      points:series.values.map((y,index)=>({x:Number(categories[index]),y}))}))});
    return xy.success&&nativeChartIssues(spec,xy.data).length===0;
  }));
  const tableLayouts=usable.filter(layout=>(!layout.charts.length||compatibleChart(layout))&&regularTables(layout).some(table=>table.columnCount>=2&&table.maxDataRows>=2));
  const chartLayouts=charts.length?usable.filter(compatibleChart):[];
  const tableIds=tables.length?tableLayouts.map(layout=>layout.id):[];
  const chartIds=chartLayouts.map(layout=>layout.id);
  const tableSources=tables.map(table=>table.id),chartSources=[...new Set(charts.map(chart=>chart.id))];
  const roomForBoth=interiorSlides>=2||tableIds.some(id=>chartIds.includes(id));
  return {
    tables:{min:interiorSlides>0&&tableIds.length&&(roomForBoth||!chartIds.length)?1:0,compatibleLayoutIds:tableIds,sourceBlockIds:tableSources},
    charts:{min:interiorSlides>0&&chartIds.length&&(roomForBoth||!tableIds.length)?1:0,compatibleLayoutIds:chartIds,sourceBlockIds:chartSources},
  };
}
