import test from 'node:test';
import assert from 'node:assert/strict';
import {planContentNumbers} from '../../src/custom-presentations/engine/source-numbers.js';

import {planQualityWarnings} from '../../src/custom-presentations/engine/plan-quality.js';


test('known citation IDs are not numerical claims in a plan',()=>{
 assert.deepEqual(planContentNumbers('43% (evidence-12); 2024', ['evidence-12']),['43','2024']);
 assert.deepEqual(planContentNumbers('evidence-121 12 people', ['evidence-12']),['121','12']);
 assert.deepEqual(planContentNumbers('37,3 л. Evidence-2, EVIDENCE-12.', ['evidence-2','evidence-12']),['37.3']);
 assert.deepEqual(planContentNumbers('Evidence-121 12 people', ['evidence-12']),['121','12']);
});
test('unmatched plan figures are warnings, without changing the valid plan',()=>{
 const plan={slides:[{sourceLayoutId:'slide_4',title:'Результаты',brief:'37,3 л, Evidence-2; прогноз 90%'}]};
 const original=structuredClone(plan);
 assert.deepEqual(planQualityWarnings(plan,'37,3 л',['evidence-2']).map(w=>({slide:w.slide,reason:w.reason})),[{slide:1,reason:'plan_numbers_review'}]);
 assert.deepEqual(plan,original);
 assert.deepEqual(planQualityWarnings({...plan,slides:[{...plan.slides[0]!,brief:'37,3 л. Evidence-2.'}]},'37,3 л',['evidence-2']),[]);
});
