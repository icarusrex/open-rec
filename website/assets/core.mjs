export const normalize = value => String(value ?? '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim();

export function filterRecords(records, {query = '', country = '', category = '', status = ''} = {}) {
  const needle = normalize(query);
  return records.filter(record => (!country || record.country === country) &&
    (!category || record.category === category) && (!status || record.status === status) &&
    (!needle || normalize([record.name, record.summary, record.location, record.category, record.country, record.status, ...(record.tags ?? [])].join(' ')).includes(needle)));
}

export const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char]));

export function readProgress(storage, validIds) {
  try {
    const value = JSON.parse(storage.getItem('openrec-checklist-v1') ?? '[]');
    return Array.isArray(value) ? [...new Set(value.filter(id => typeof id === 'string' && validIds.includes(id)))] : [];
  } catch { return []; }
}

export function writeProgress(storage, ids) {
  try { storage.setItem('openrec-checklist-v1', JSON.stringify(ids)); return true; }
  catch { return false; }
}
