import {filterRecords, readProgress, writeProgress} from './core.mjs';

document.documentElement.classList.add('js');

// Printouts should carry sources: open closed disclosures for printing, then restore them.
let openedForPrint = [];
window.addEventListener('beforeprint', () => {
  openedForPrint = [...document.querySelectorAll('details:not([open])')];
  for (const d of openedForPrint) d.open = true;
});
window.addEventListener('afterprint', () => {
  for (const d of openedForPrint) d.open = false;
  openedForPrint = [];
});
const menu = document.querySelector('.menu-button');
const nav = document.querySelector('#navigation');
menu.hidden = false;
menu.addEventListener('click', () => {
  const open = menu.getAttribute('aria-expanded') !== 'true';
  menu.setAttribute('aria-expanded', String(open));
  nav.classList.toggle('is-open', open);
});
document.addEventListener('keydown', event => {
  if(event.key === 'Escape' && menu.getAttribute('aria-expanded') === 'true') {
    menu.setAttribute('aria-expanded','false'); nav.classList.remove('is-open'); menu.focus();
  }
});

const directory = document.querySelector('[data-directory]');
if (directory) {
  const kind = directory.dataset.directory;
  const form = directory.querySelector('[data-filters]');
  const count = directory.querySelector('[data-result-count]');
  try {
    const response = await fetch(`/data/${kind}.json`);
    if(!response.ok) throw new Error('Data unavailable');
    const records = await response.json();
    function restore() {
      const params = new URLSearchParams(location.search);
      for(const control of form.elements) {
        if(!control.name) continue;
        const value = params.get(control.name) ?? '';
        control.value = control.tagName==='SELECT' && ![...control.options].some(o=>o.value===value) ? '' : value;
      }
    }
    function update(updateUrl=true) {
      const filters = Object.fromEntries(new FormData(form));
      const visible = new Set(filterRecords(records,filters).map(r=>r.id));
      for(const card of directory.querySelectorAll('[data-record-id]')) {
        const element = kind === 'legislation' ? card : card.parentElement;
        element.hidden = !visible.has(card.dataset.recordId);
      }
      const label = kind === 'communities' ? 'initiatives' : kind === 'legislation' ? 'records' : 'tools';
      count.textContent = `${visible.size} of ${records.length} ${label} shown`;
      directory.querySelector('[data-empty]').hidden = visible.size > 0;
      if(updateUrl) {
        const url = new URL(location.href);
        for(const [key,value] of Object.entries(filters)) value ? url.searchParams.set(key,value) : url.searchParams.delete(key);
        try { history.replaceState(null,'',url); } catch { /* Filtering still works when history access is denied. */ }
      }
    }
    form.addEventListener('submit', event => event.preventDefault());
    form.addEventListener('input', () => update());
    form.addEventListener('change', () => update());
    form.addEventListener('reset', () => queueMicrotask(() => update()));
    directory.querySelector('[data-reset]').addEventListener('click',()=>form.reset());
    window.addEventListener('popstate',()=>{restore();update(false);});
    restore(); update(false); form.hidden = false;
  } catch {
    count.textContent += ' · Search is temporarily unavailable. All records remain visible.';
  }
  const id = decodeURIComponent(location.hash.slice(1));
  const target = id && document.getElementById(id);
  if(target && !target.hidden) {
    const details = target.querySelector('details');
    if(details) details.open = true;
  }
}

const steps = [...document.querySelectorAll('[data-step]')];
if(steps.length) {
  let storage;
  try { storage = window.localStorage; } catch { storage = null; }
  const selected = new Set(readProgress(storage,steps.map(s=>s.dataset.step)));
  function showProgress(persist=false) {
    for(const step of steps) {
      step.checked = selected.has(step.dataset.step);
      step.closest('.checklist-step').classList.toggle('is-complete',step.checked);
    }
    document.querySelector('progress').value = selected.size;
    document.querySelector('[data-progress-label]').textContent = `${selected.size} of ${steps.length} steps marked`;
    if(persist && !writeProgress(storage,[...selected])) document.querySelector('[data-storage-note]').textContent = 'Browser storage is unavailable. Progress works for this visit; download your checklist to keep a copy.';
  }
  for(const step of steps) {
    step.hidden=false;
    step.addEventListener('change',()=>{
      step.checked ? selected.add(step.dataset.step) : selected.delete(step.dataset.step);
      showProgress(true);
    });
  }
  document.querySelector('[data-checklist-controls]').hidden=false;
  document.querySelector('[data-reset-checklist]').addEventListener('click',()=>{selected.clear();showProgress(true);});
  document.querySelector('[data-print]').addEventListener('click',()=>window.print());
  document.querySelector('[data-export-checklist]').addEventListener('click',()=>{
    const checklist = steps.map(step=>({id:step.dataset.step, title:step.closest('article').querySelector('h2').textContent, marked_complete:step.checked}));
    const blob = new Blob([JSON.stringify({exported_at:new Date().toISOString(),note:'Personal organising progress; does not establish approval or eligibility.',steps:checklist},null,2)],{type:'application/json'});
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a'); link.href=url;link.download='openrec-starter-checklist.json';link.click();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
  });
  showProgress();
}
