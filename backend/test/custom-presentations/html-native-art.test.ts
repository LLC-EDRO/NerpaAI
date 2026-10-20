import test from 'node:test';
import assert from 'node:assert/strict';
import {sandboxArtifactAllowed,validateSandboxArtifacts} from '../../src/custom-presentations/engine/sandbox-protocol.js';
import {cssSourceDesign} from '../../src/custom-presentations/engine/html-model-geometry.js';
import {sourceHtmlDesign} from '../../src/custom-presentations/engine/html-source-design.js';
import {htmlAuthorResponseSchema} from '../../src/custom-presentations/engine/html-author-schema.js';

test('separate native-art backgrounds cross the sandbox protocol only under registered safe names',()=>{
 assert.ok(sandboxArtifactAllowed('html_template','html-native-background-18.png'));
 for(const name of ['../html-native-background-18.png','html-native-background-18.png/extra','html-native-background-x.png','html-native-background-1000.png'])assert.equal(sandboxArtifactAllowed('html_template',name),false);
 const result={version:1,profilesOnly:true,layouts:[{background:'html-background-18.png',nativeBackground:'html-native-background-18.png'}],refreshedArtwork:['html-background-18.png','html-native-background-18.png']};
 const files=['html-template.json',...result.refreshedArtwork];
 assert.doesNotThrow(()=>validateSandboxArtifacts('html_template',result,files,0,false,true));
 assert.throws(()=>validateSandboxArtifacts('html_template',result,files.slice(0,2),0,false,true));
 assert.throws(()=>validateSandboxArtifacts('html_template',{...result,refreshedArtwork:['html-native-background-19.png']},files,0,false,true));
});
test('shared model context retains native identities but avoids resending vector path code on every slide',()=>{
 const source={canvas:{width:960,height:540},textAnchors:[],artwork:[],photoFrames:[],dataFrames:[],sourceHtml:{nativeArt:{objects:[{shapeId:30,kind:'cxnSp',editable:true,svg:'VERY_LONG_VECTOR_PATH'}],unsupported:[]}}};
 const compact=cssSourceDesign(source,true),full=cssSourceDesign(source);
 assert.equal(compact.sourceHtml.nativeArt.objects[0].shapeId,30);assert.ok(!JSON.stringify(compact).includes('VERY_LONG_VECTOR_PATH'));assert.ok(JSON.stringify(full).includes('VERY_LONG_VECTOR_PATH'));
});
test('local edits can remove an owned sample picture or connector while logos and heading remain protected',()=>{
 const rect={x:100,y:150,w:300,h:150},base={canRemove:true,box:rect,hasText:false};
 const design=sourceHtmlDesign({width:960,height:540},{htmlRole:'content',htmlTitleShapeId:9,slots:[],sourceObjects:[
  {...base,shapeId:7,kind:'picture',role:'photo'},{...base,shapeId:8,kind:'connector',role:'unknown'},
  {...base,shapeId:9,kind:'shape',role:'title',fill:{color:'#fff'}},{...base,shapeId:10,kind:'picture',role:'logo'}]});
 assert.deepEqual(design.editableShapes.map(s=>s.shapeId),[7,8]);
 assert.deepEqual(design.editableShapes[0]!.allowedActions,['remove']);
});
test('strict author grammar restricts global batch identities and requires complete slide code',()=>{
 const schema=htmlAuthorResponseSchema([5,6]) as any,item=schema.properties.slides.items;
 assert.deepEqual(item.properties.index.enum,[5,6]);assert.equal(item.type,'object');assert.equal(item.additionalProperties,false);
 assert.ok(item.required.includes('html'));assert.ok(item.required.includes('css'));assert.ok(item.required.includes('sourceShapeEdits'));
});
test('empty text placeholders and removed sample data do not become fake protected artwork',()=>{
 const b={x:100,y:200,w:400,h:160},layout={htmlRole:'content',slots:[],imageSlots:[{shapeId:3,box:b}],sourceObjects:[
  {shapeId:1,kind:'shape',hasText:false,fill:null,line:null,box:b},
  {shapeId:2,kind:'group',hasText:false,box:b},
  {shapeId:3,parentShapeId:2,kind:'picture',hasText:false,box:b},
  {shapeId:4,kind:'chart',hasText:false,box:b},
  {shapeId:5,kind:'shape',hasText:false,line:{color:'#123456'},box:b}]};
 const result=sourceHtmlDesign({width:960,height:540},layout);
 assert.deepEqual(result.artwork.map(a=>a.shapeId),[5]);assert.equal(result.dataFrames[0]!.shapeId,4);
});
