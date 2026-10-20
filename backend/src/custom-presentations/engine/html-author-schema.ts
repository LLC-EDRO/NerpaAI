/** Provider grammar: malformed prose cannot replace a slide object or code. */
export function htmlAuthorResponseSchema(indices:number[]):Record<string,unknown>{
  const string={type:'string'},strings={type:'array',items:string};
  const object=(properties:Record<string,unknown>)=>({type:'object',properties,required:Object.keys(properties),additionalProperties:false});
  const array=(items:unknown)=>({type:'array',items});
  const pair=object({title:string,body:string});
  const nullable=(value:any)=>({anyOf:[value,{type:'null'}]});
  return object({thesis:string,css:string,slides:{type:'array',minItems:1,maxItems:indices.length,items:object({
    index:{type:'integer',enum:indices},stencilId:{type:'string',enum:['source-layout','editorial','columns','comparison','figure-right','figure-left','process','metrics','chart-insight','chart-right','chart-wide','table-insight','table-right','table-wide','statement','source-terminal']},title:string,paragraphs:strings,cards:array(pair),steps:array(pair),
    sourceBindings:array(object({shapeId:{type:'integer'},paths:strings})),
    metrics:array(object({value:string,label:string})),
    table:nullable(object({headers:strings,rows:array(strings)})),
    chart:nullable(object({type:{type:'string',enum:['bar','bar-horizontal','line','pie','donut','xy']},title:string,categories:strings,series:array(object({name:string,values:array({type:'number'})}))})),
    chartPresentation:nullable(object({mode:{type:'string',enum:['auto','native','image']},treatment:{type:'string',enum:['plain','gradient','soft-area']},reason:string})),
    takeaway:string,notes:string,speech:string,html:string,css:string,
    sourceShapeEdits:array(object({shapeId:{type:'integer'},action:{type:'string',enum:['remove','replace']}})),
    omitSourceIconIds:array({type:'integer'}),
    designDecision:object({mode:{type:'string',enum:['preserve','adapt','repair']},family:{type:'string',enum:['cover','text','photo','table','chart','radial','timeline','metrics','closing']},reasons:strings}),
  })}});
}
