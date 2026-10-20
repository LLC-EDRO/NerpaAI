import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm} from 'node:fs/promises';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {uniqueWarnings} from '../../src/custom-presentations/engine/quality-warnings.js';

import {validateSandboxArtifacts} from '../../src/custom-presentations/engine/sandbox-protocol.js';

import {writeJson} from '../../src/custom-presentations/engine/store.js';


test('PPTX with warnings needs actual artifacts but can omit failed PDF',()=>{
 const result={slides:[{}],warnings:[{reason:'html_text_overflow'}],pptxWritten:true,pdfAvailable:false};
 const files=['presentation.pptx','package-cleanup.json','render-quality.json','html-scenes.json'];
 assert.doesNotThrow(()=>validateSandboxArtifacts('html_export',result,files,1));
 assert.throws(()=>validateSandboxArtifacts('html_export',result,files.slice(1),1));
 assert.throws(()=>validateSandboxArtifacts('html_export',{...result,pdfAvailable:true},files,1));
});
