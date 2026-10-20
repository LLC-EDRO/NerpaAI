import test from 'node:test';
import assert from 'node:assert/strict';
import {numbers,evidenceNumbers} from '../../src/custom-presentations/engine/source-numbers.js';


test('calendar dates agree across dotted and Russian notation without decimal truncation',()=>{
 assert.deepEqual(numbers('Срок 1.10.2027'), numbers('Срок 1 октября 2027'));
 assert.notDeepEqual(numbers('1.10.2027'), numbers('1.1.2027'));
 assert.ok(!numbers('1.10.2027').includes('1.1'));
 assert.ok(evidenceNumbers('1 октября 2027').includes('2027'));
 assert.ok(!evidenceNumbers('2027').includes('date:2027-10-01'));
 assert.deepEqual(numbers('1.10%'),['1.1']);
});
test('native fact checks recognize typographical thousands without merging years or decimals',()=>{
 assert.deepEqual(numbers('12 841; 1\u00a0065,7; 25\u202f000; 2024 2025'),['12841','1065.7','25000','2024','2025']);
 assert.deepEqual(numbers('2–3 дня; 1.5%'),['2','3','1.5']);
});
test('spelled time ranges agree with numeric copy but unrelated/composite words are not numbers',()=>{
 const values=evidenceNumbers('двух-трёхдневный аудит, пятилетний план, четырёхчасовая проверка');
 for(const n of ['2','3','5','4'])assert.ok(values.includes(n));
 assert.ok(!evidenceNumbers('двадцать один человек').includes('1'));
 assert.deepEqual(evidenceNumbers('трибуна, двухсотлетний'),[]);
});
test('fractions preserve numerator/denominator as a single value',()=>{
 assert.deepEqual(numbers('≈1 / 3; 2/3; 2018'),['1/3','2/3','2018']);
 assert.ok(evidenceNumbers('около одной трети потока').includes('1/3'));
 assert.ok(evidenceNumbers('две трети').includes('2/3'));
 assert.ok(!evidenceNumbers('две трети').includes('1/3'));
 assert.ok(!evidenceNumbers('третьего этапа').includes('1/3'));
});

test('signed quantities, decimal equivalence and comma sequences retain their meanings',()=>{
 assert.deepEqual(numbers('−3,1; +2,20; -1.40; 24.0; -0,0'),['-3.1','2.2','-1.4','24','0']);
 assert.deepEqual(numbers('1,2,3,4: 20,24,28,23 Н; 14,5 мм'),['1','2','3','4','20','24','28','23','14.5']);
 assert.deepEqual(numbers('2–3; 2-3; evidence-121'),['2','3','2','3','121']);
});
