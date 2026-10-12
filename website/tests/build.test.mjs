import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile, readdir, stat} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import {spawnSync} from 'node:child_process';

const root = fileURLToPath(new URL('../', import.meta.url));
const build = spawnSync(process.execPath, [path.join(root,'scripts/build.mjs')], {encoding:'utf8'});

test('build produces all six navigable pages with accessible structure', async () => {
  assert.equal(build.status, 0, build.stderr);
  for (const route of ['','start','communities','legislation','tools','project']) {
    const html = await readFile(path.join(root,'dist',route,'index.html'),'utf8');
    assert.match(html, /<main id="main"/);
    assert.equal((html.match(/<h1[ >]/g) ?? []).length,1);
    assert.match(html,/Skip to content/);
    assert.match(html,/aria-current="page"/);
    assert.ok(!html.includes('\u2014'), 'authored text must have no em dash');
  }
});

test('every generated local link and asset exists, including source downloads', async () => {
  assert.equal(build.status,0,build.stderr);
  async function walk(dir) {
    const out=[];
    for(const entry of await readdir(dir,{withFileTypes:true})) {
      const p=path.join(dir,entry.name);
      if(entry.isDirectory()) out.push(...await walk(p)); else if(p.endsWith('.html')) out.push(p);
    }
    return out;
  }
  for(const file of await walk(path.join(root,'dist'))) {
    const html=await readFile(file,'utf8');
    for(const match of html.matchAll(/(?:href|src)="(\/[^"]*)"/g)) {
      let target=decodeURIComponent(match[1].split(/[?#]/)[0]);
      if(target.endsWith('/')) target+='index.html';
      await assert.doesNotReject(stat(path.join(root,'dist',target)), `${file}: ${target}`);
    }
  }
});

test('all dataset records have unique identities, real dates and safe primary-source links', async () => {
  for(const name of ['communities','tools','legislation','resources','checklist']) {
    const data=JSON.parse(await readFile(path.join(root,'data',name+'.json'),'utf8'));
    assert.equal(new Set(data.map(r=>r.id)).size,data.length);
    for(const r of data) {
      assert.match(r.id,/^[a-z0-9-]+$/);
      assert.match(r.checked_at,/^\d{4}-\d{2}-\d{2}$/);
      assert.ok(!Number.isNaN(Date.parse(r.checked_at)));
      assert.ok(r.sources.length>0);
      for(const s of r.sources) assert.equal(new URL(s.url).protocol,'https:');
      assert.ok(Object.hasOwn(r,'source_published_at'));
      assert.ok(Object.hasOwn(r,'source_updated_at'));
    }
  }
});
