import {z} from 'zod';

export const maxNativeChartSeries=6;
export const maxNativeChartPoints=500;

export interface NativeChartAxis {
  id:string;
  dimension:'x'|'y';
  scale:'linear'|'log';
  logBase?:number;
  min?:number;
  max?:number;
}
export interface NativeChartSpec {
  key:string;shapeId:number;part:string;type:string;
  seriesCount:number;pointCount:number;hasTitle:boolean;
  dataKind?:'category'|'xy';
  seriesPointCounts?:number[];
  axes?:NativeChartAxis[];
  seriesAxes?:Array<{xAxisId?:string;yAxisId?:string}>;
}

const chartText={title:z.string().max(80),evidence:z.array(z.string().max(3000))};
const name=z.string().min(1).max(40).refine(value=>value.trim().length>0,'Chart series name must not be blank');
const values=z.array(z.number().finite()).min(1).max(maxNativeChartPoints);
const categoryChart=z.object({...chartText,
  categories:z.array(z.string().min(1).max(30).refine(value=>value.trim().length>0,'Chart category must not be blank')).min(1).max(maxNativeChartPoints),
  series:z.array(z.object({name,values})).min(1).max(maxNativeChartSeries),
}).strict();
const xyChart=z.object({...chartText,kind:z.literal('xy'),
  series:z.array(z.object({name,points:z.array(z.object({x:z.number().finite(),y:z.number().finite()}).strict()).min(1).max(maxNativeChartPoints)}).strict()).min(1).max(maxNativeChartSeries),
}).strict();
export const nativeChartCopySchema=z.union([xyChart,categoryChart]);
export type NativeChartCopy=z.infer<typeof nativeChartCopySchema>;
export const isNativeXYChart=(spec:Pick<NativeChartSpec,'type'|'dataKind'>)=>spec.dataKind==='xy'||spec.type==='scatterChart';
export const isXYChartCopy=(chart:NativeChartCopy):chart is z.infer<typeof xyChart>=>'kind' in chart&&chart.kind==='xy';

export function nativeChartPointCounts(spec:NativeChartSpec) {
  if(!Number.isInteger(spec.seriesCount)||spec.seriesCount<1||spec.seriesCount>maxNativeChartSeries)return[];
  return isNativeXYChart(spec)?spec.seriesPointCounts||Array(spec.seriesCount).fill(spec.pointCount):Array(spec.seriesCount).fill(spec.pointCount);
}

export function nativeChartIssues(spec:NativeChartSpec,chart:NativeChartCopy) {
  const issues:Array<{reason:string;message?:string}>=[];
  const xy=isNativeXYChart(spec);
  if(xy!==isXYChartCopy(chart))return[{reason:'chart_dimensions',message:'Chart data must match the original category or XY chart type.'}];
  const counts=nativeChartPointCounts(spec);
  if(!Number.isInteger(spec.seriesCount)||spec.seriesCount<1||spec.seriesCount>maxNativeChartSeries||counts.length!==spec.seriesCount||
    counts.some(count=>!Number.isInteger(count)||count<1||count>maxNativeChartPoints)||chart.series.length!==spec.seriesCount||
    (!isXYChartCopy(chart)&&chart.series.some(series=>series.values.length!==chart.categories.length)))
    issues.push({reason:'chart_dimensions',message:'Preserve the original series count/order. Every category series must match the new category count; XY series have independent point counts.'});
  const axes=spec.axes||[];
  const logarithmic=axes.filter(axis=>axis.scale==='log');
  if(logarithmic.some(axis=>axis.logBase!==undefined&&(!Number.isFinite(axis.logBase)||axis.logBase<2||axis.logBase>1000)))
    issues.push({reason:'chart_range',message:'Original logarithmic axis base must be between 2 and 1000.'});
  chart.series.forEach((series,index)=>{
    const binding=spec.seriesAxes?.[index];
    const axisFor=(dimension:'x'|'y')=>{
      const id=dimension==='x'?binding?.xAxisId:binding?.yAxisId;
      return id?axes.filter(axis=>axis.id===id):axes.filter(axis=>axis.dimension===dimension);
    };
    if(binding&&[binding.xAxisId,binding.yAxisId].some(id=>id&&!axes.some(axis=>axis.id===id)))
      issues.push({reason:'chart_range',message:'An original series axis binding is missing.'});
    if('points' in series){
      for(const dimension of ['x','y'] as const)
        if(axisFor(dimension).some(axis=>axis.scale==='log')&&series.points.some(point=>point[dimension]<=0))
          issues.push({reason:'chart_range',message:`Series ${index+1}: every ${dimension.toUpperCase()} coordinate on the logarithmic axis must be positive.`});
    }else if([...axisFor('x'),...axisFor('y')].some(axis=>axis.scale==='log')&&series.values.some(value=>value<=0))
      issues.push({reason:'chart_range',message:`Series ${index+1}: every value on the logarithmic axis must be positive.`});
  });
  if(/pie|doughnut/.test(spec.type)&&!isXYChartCopy(chart)&&chart.series.some(series=>series.values.some(value=>value<0)||!series.values.some(value=>value>0)))
    issues.push({reason:'chart_range'});
  return issues;
}
