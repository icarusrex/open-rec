import {test} from 'node:test';
import assert from 'node:assert/strict';
import {filterRecords, escapeHtml, readProgress, writeProgress} from '../assets/core.mjs';

const records = [
  {id:'a', name:'Coopérnico', country:'Portugal', category:'Cooperative', status:'Reported active', summary:'Solar energy in Lisboa'},
  {id:'b', name:'Ecopower', country:'Belgium', category:'Cooperative', status:'Reported active', summary:'Wind'},
  {id:'c', name:'Telheiras', country:'Portugal', category:'Local sharing', status:'Reported operational', summary:'Community'}
];
test('search finds diacritics and combines geography/category/status', () => {
  assert.deepEqual(filterRecords(records, {query:' COOPERNICO ', country:'Portugal', category:'Cooperative',status:'Reported active'}).map(r=>r.id), ['a']);
  assert.deepEqual(filterRecords(records, {query:'wind',country:'Portugal'}), []);
  assert.equal(filterRecords(records, {}).length, 3);
});
test('search finds accented locations, with literal punctuation', () => {
  assert.equal(filterRecords(records, {query:'lisboa'}).length,1);
  assert.equal(filterRecords(records, {query:'['}).length,0);
});
test('record text is escaped for HTML and attributes', () => {
  assert.equal(escapeHtml('<img src=x onerror="alert(1)">&\''), '&lt;img src=x onerror=&quot;alert(1)&quot;&gt;&amp;&#39;');
});
test('corrupted, non-array, duplicate and unknown stored checklist IDs are safe', () => {
  for(const value of ['oops','null','{}','42']) assert.deepEqual(readProgress({getItem:()=>value}, ['one']), []);
  assert.deepEqual(readProgress({getItem:()=> '["one","one","foreign",4]'}, ['one']), ['one']);
  assert.deepEqual(readProgress({getItem(){throw new Error('blocked');}}, ['one']), []);
});
test('storage denial returns failure without breaking checklist use', () => {
  assert.equal(writeProgress({setItem(){throw new Error('blocked');}}, ['one']), false);
  let saved; assert.equal(writeProgress({setItem:(key,value)=>{saved=JSON.parse(value);}}, ['one']),true);
  assert.deepEqual(saved,['one']);
});
