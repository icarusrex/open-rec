// Regression tests for defects found in the 12 October 2026 audit.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile, writeFile, mkdtemp, cp, readdir} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {isCalendarDate, formatDate, validateRecord} from '../scripts/validate.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
let unchanged; // one isolated build of the real data, so we never race build.test.mjs over dist/
const real = async () => (unchanged ??= await buildWith(async () => {}));

// Build from a modified copy of the data into a temporary dist.
async function buildWith(mutate) {
  const tmp = await mkdtemp(path.join(tmpdir(), 'openrec-'));
  const dataDir = path.join(tmp, 'data');
  await cp(path.join(root, 'data'), dataDir, {recursive: true});
  const load = async n => JSON.parse(await readFile(path.join(dataDir, `${n}.json`), 'utf8'));
  const save = (n, v) => writeFile(path.join(dataDir, `${n}.json`), JSON.stringify(v));
  await mutate({load, save});
  const dist = path.join(tmp, 'dist');
  const run = spawnSync(process.execPath, [path.join(root, 'scripts/build.mjs')], {
    encoding: 'utf8', env: {...process.env, OPENREC_DATA_DIR: dataDir, OPENREC_DIST: dist},
  });
  const page = p => readFile(path.join(dist, p, 'index.html'), 'utf8');
  return {run, page, dist};
}

test('calendar dates are validated strictly', () => {
  for (const ok of ['2026-02-28', '2024-02-29', '2026-12-31']) assert.ok(isCalendarDate(ok), ok);
  for (const bad of ['2026-02-31', '2025-02-29', '2026-13-01', '2026-00-10', '2026-04-31', '2026-1-01', '', null]) {
    assert.equal(isCalendarDate(bad), false, String(bad));
  }
});

test('a record with an impossible check date is rejected', () => {
  const row = {id: 'x', sources: [{label: 'a', url: 'https://example.org'}], checked_at: '2026-02-31', source_published_at: null, source_updated_at: null};
  assert.throws(() => validateRecord(row, 't'), /checked_at/);
  assert.throws(() => validateRecord({...row, checked_at: '2026-02-01', source_published_at: '2026-02-30'}, 't'), /source_published_at/);
});

test('the build refuses impossible dates in the data', async () => {
  const {run} = await buildWith(async ({load, save}) => {
    const rows = await load('legislation'); rows[0].checked_at = '2026-02-31'; await save('legislation', rows);
  });
  assert.notEqual(run.status, 0);
  assert.match(run.stderr, /checked_at/);
});

test('month-precision dates render the actual month', () => {
  assert.equal(formatDate('2026-03-01', 'month'), 'March 2026');
  assert.equal(formatDate('2026-01-01', 'month'), 'January 2026');
  assert.equal(formatDate('2022-01-14'), '14 January 2022');
});

test('a March edition is labelled March, not January', async () => {
  const {run, page} = await buildWith(async ({load, save}) => {
    const rows = await load('legislation');
    rows.find(r => r.date_precision === 'month').date = '2026-03-01';
    await save('legislation', rows);
  });
  assert.equal(run.status, 0, run.stderr);
  const html = await page('legislation');
  assert.match(html, /<small>March<\/small>/);
  assert.doesNotMatch(html, /January edition/);
});

test('SANJOTEC chart, labels and accessible text all follow the community record', async () => {
  const {run, page} = await buildWith(async ({load, save}) => {
    const rows = await load('communities');
    rows.find(r => r.id === 'pt-sanjotec').own_use_share_percent = 60;
    await save('communities', rows);
  });
  assert.equal(run.status, 0, run.stderr);
  const html = await page('communities');
  assert.match(html, /60 percent host use, 40 percent community sharing/);
  assert.match(html, /<span>60% host use<\/span><span>40% shared<\/span>/);
  assert.match(html, /class="allocation-own" x="0" y="0" width="60"/);
  assert.match(html, /class="allocation-shared" x="60" y="0" width="40"/);
  assert.doesNotMatch(html, /74%/);
});

test('known publication dates are shown, not "not disclosed"', async () => {
  const html = await (await real()).page('legislation');
  for (const id of ['pt-dl-15-2022', 'pt-rac-815-2023']) {
    const block = html.slice(html.indexOf(`id="${id}"`), html.indexOf('</article>', html.indexOf(`id="${id}"`)));
    assert.match(block, /Source published \d{1,2} \w+ \d{4}/, id);
  }
  assert.match(html, /Source published 14 January 2022/);
  assert.match(html, /Source published 27 July 2023/);
});

test('site-wide check date is derived from the records', async () => {
  const {run, page} = await buildWith(async ({load, save}) => {
    const rows = await load('tools'); rows[0].checked_at = '2026-11-03'; await save('tools', rows);
  });
  assert.equal(run.status, 0, run.stderr);
  const home = await page('');
  assert.match(home, /Evidence last checked 3 November 2026/);
  assert.match(await page('legislation'), /checked 3 November 2026/);
});

test('funding deadlines and call status are rendered', async () => {
  const html = await (await real()).page('project');
  assert.match(html, /Call closed/);
  assert.match(html, /Deadline 16 September 2026/);
});

test('social previews use a raster image and the 404 page claims no nav item', async () => {
  const {dist: d} = await real();
  const home = await readFile(path.join(d, 'index.html'), 'utf8');
  assert.match(home, /og:image" content="https:\/\/openrec\.viableplanet\.eu\/assets\/social\.png"/);
  assert.match(home, /twitter:card" content="summary_large_image"/);
  const png = await readFile(path.join(d, 'assets/social.png'));
  assert.deepEqual([...png.subarray(1, 4)], [0x50, 0x4e, 0x47]);
  const notFound = await readFile(path.join(d, '404.html'), 'utf8');
  assert.doesNotMatch(notFound, /aria-current/);
  assert.doesNotMatch(notFound, /rel="canonical"/);
  assert.match(notFound, /noindex/);
});

test('in-page anchors point at ids that exist on the target page', async () => {
  const {dist} = await real();
  const pages = {};
  for (const p of ['', 'start', 'communities', 'legislation', 'tools', 'project']) {
    pages[`/${p ? p + '/' : ''}`] = await readFile(path.join(dist, p, 'index.html'), 'utf8');
  }
  for (const [route, html] of Object.entries(pages)) {
    for (const href of html.matchAll(/href="(\/[^"#]*)?#([^"]+)"/g)) {
      const target = href[1] ?? route; const id = href[2];
      if (id === 'main') continue;
      assert.ok(pages[target], `${route}: unknown page ${target}`);
      assert.ok(pages[target].includes(`id="${id}"`), `${route}: missing #${id} on ${target}`);
    }
  }
});
