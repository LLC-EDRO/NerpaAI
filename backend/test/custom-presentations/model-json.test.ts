import test from 'node:test';
import assert from 'node:assert/strict';
import {parseModelJson} from '../../src/custom-presentations/engine/model-json.js';

test('model formatting recovery preserves Russian text, formulas, numbers and punctuation inside strings',()=>{
  const value={slides:[{title:'Сравнение «рядов»',brief:'Ирландия: 1,25; Европа: 2. Формула \\alpha. Символы ,} ] { и "кавычки".',sourceImageIds:['image-1']}]};
  const json=JSON.stringify(value);
  for(const text of [json,'\uFEFF'+json,'```json\n'+json+'\n```','Результат:\n'+json+'\nГотово.',json.replace(/\}\]\}$/u,'},],}')])assert.deepEqual(parseModelJson(text),value);
});
test('raw string controls can be escaped without rewriting the source content',()=>{
  assert.deepEqual(parseModelJson('{"text":"Первая строка\nВторая\tстрока"}'),{text:'Первая строка\nВторая\tстрока'});
});
test('incomplete or ambiguous content is rejected for model repair, never fabricated or evaluated',()=>{
  for(const text of ['','no object','{"slides":[{"title":"unfinished','{"value":1,','{"x":[1,2}','{"x":undefined}',"{'x':1}",'(()=>{throw Error("execute")})()'])assert.throws(()=>parseModelJson(text),SyntaxError);
  assert.throws(()=>parseModelJson('x'.repeat(1_000_001)),SyntaxError);
  assert.throws(()=>parseModelJson('result: '+'['.repeat(101)+'0'+']'.repeat(101)),SyntaxError);
});
