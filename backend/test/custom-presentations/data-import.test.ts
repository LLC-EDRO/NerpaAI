import test from 'node:test';
import assert from 'node:assert/strict';
import {randomUUID, createHash} from 'node:crypto';
import * as XLSX from 'xlsx';
import {parsePresentationData} from '../../src/custom-presentations/data/parse.js';
import {analyzePresentationData} from '../../src/custom-presentations/data/analyze.js';
import {dataViews} from '../../src/custom-presentations/engine/data-contract.js';

for (const [name, content] of [
  ['observations.json', '[{"Year":"2024","Revenue":12.5},{"Year":"2025","Revenue":18.5}]'],
  ['observations.jsonl', '{"Year":"2024","Revenue":12.5}\n{"Year":"2025","Revenue":18.5}'],
  ['observations.csv', 'Year;Revenue\n2024;12,5\n2025;18,5'],
  ['observations.tsv', 'Year\tRevenue\n2024\t12.5\n2025\t18.5'],
  ['observations.txt', '| Year | Revenue |\n| --- | --- |\n| 2024 | 12.5 |\n| 2025 | 18.5 |'],
  ['observations.xml', '<report><rows><row><Year>2024</Year><Revenue>12.5</Revenue></row><row><Year>2025</Year><Revenue>18.5</Revenue></row></rows></report>'],
  ['attributes.xml', '<rows><row Year="2024" Revenue="12.5"/><row Year="2025" Revenue="18.5"/></rows>'],
] as const) {
  test(`imports ${name} into exact evidence views without inventing values`, async () => {
    const bytes = Buffer.from(content), parsed = await parsePresentationData(bytes, name);
    const receipt = analyzePresentationData(randomUUID(), name, createHash('sha256').update(bytes).digest('hex'), parsed.tables);
    const views = dataViews([receipt]);
    assert.ok(views.length);
    assert.ok(views.some(view => view.series.some(series => series.values.includes(12.5) && series.values.includes(18.5))));
    assert.equal(receipt.datasets[0].rowCount, 2);
  });
}

test('Excel imports values and never evaluates formulas', async () => {
  const workbook = XLSX.utils.book_new();
  const sheet = XLSX.utils.aoa_to_sheet([['Year', 'Value'], ['2024', 3], ['2025', 8]]);
  sheet.B3 = {t: 'n', v: 8, f: '2+6'};
  XLSX.utils.book_append_sheet(workbook, sheet, 'Evidence');
  const parsed = await parsePresentationData(XLSX.write(workbook, {type: 'buffer', bookType: 'xlsx'}), 'facts.xlsx');
  assert.deepEqual(parsed.tables[0].rows, [['Year', 'Value'], ['2024', '3'], ['2025', '8']]);
});

for (const [name, content] of [
  ['entity.xml', '<!DOCTYPE rows [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><rows><row><x>&xxe;</x><y>1</y></row></rows>'],
  ['broken.xml', '<rows><row></rows>'],
  ['broken.json', '[{"value":1}'],
  ['deep.xml', '<a>'.repeat(25) + '<row x="1" y="2"/>' + '</a>'.repeat(25)],
] as const) {
  test(`rejects malformed or unsafe ${name}`, async () => {
    await assert.rejects(parsePresentationData(Buffer.from(content), name), (error: any) => error.status === 422 && error.code.startsWith('data_'));
  });
}

test('validates size, extension, row limits and cancellation before accepting data', async () => {
  await assert.rejects(parsePresentationData(Buffer.alloc(10 * 1024 * 1024 + 1), 'large.json'), (e: any) => e.code === 'data_invalid_file');
  await assert.rejects(parsePresentationData(Buffer.from('x,y\n1,2'), 'file.exe'), (e: any) => e.code === 'data_invalid_file');
  await assert.rejects(parsePresentationData(Buffer.from('x,y\n' + '1,2\n'.repeat(10002)), 'large.csv'), (e: any) => e.code === 'data_too_large');
  const controller = new AbortController(); controller.abort();
  await assert.rejects(parsePresentationData(Buffer.from('x,y\n1,2'), 'facts.csv', controller.signal), (e: any) => e.name === 'AbortError');
});
