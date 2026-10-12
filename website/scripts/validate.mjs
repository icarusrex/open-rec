// Data validation shared by the build and the tests.
// Dates are ISO calendar dates (YYYY-MM-DD). A record whose date is only known
// to the month declares date_precision: "month" and still stores the first day.

const DATE_FIELDS = ['date', 'checked_at', 'source_published_at', 'source_updated_at', 'deadline'];
const MONTHS = ['January','February','March','April','May','June','July','August','September','October','November','December'];

export function isCalendarDate(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const [y, m, d] = value.split('-').map(Number);
  if (m < 1 || m > 12 || d < 1) return false;
  const daysInMonth = new Date(Date.UTC(y, m, 0)).getUTCDate();
  return d <= daysInMonth;
}

// Human-readable date that respects declared precision.
export function formatDate(value, precision = 'day') {
  if (!isCalendarDate(value)) throw new Error(`Not a calendar date: ${value}`);
  const [y, m, d] = value.split('-').map(Number);
  if (precision === 'month') return `${MONTHS[m - 1]} ${y}`;
  if (precision !== 'day') throw new Error(`Unknown date precision: ${precision}`);
  return `${d} ${MONTHS[m - 1]} ${y}`;
}

export function validateRecord(row, name) {
  const where = `${name}/${row.id}`;
  if (!/^[a-z0-9-]+$/.test(row.id ?? '')) throw new Error(`Invalid record id in ${name}: ${row.id}`);
  if (!row.sources?.length) throw new Error(`${where}: at least one source is required`);
  for (const s of row.sources) {
    if (!s.label) throw new Error(`${where}: source without label`);
    if (new URL(s.url).protocol !== 'https:') throw new Error(`${where}: non-https source ${s.url}`);
  }
  if (row.website && new URL(row.website).protocol !== 'https:') throw new Error(`${where}: non-https website`);
  if (!isCalendarDate(row.checked_at)) throw new Error(`${where}: checked_at must be a real date`);
  for (const key of ['source_published_at', 'source_updated_at']) {
    if (!Object.hasOwn(row, key)) throw new Error(`${where}: ${key} must be present (use null when unknown)`);
  }
  for (const key of DATE_FIELDS) {
    if (row[key] != null && !isCalendarDate(row[key])) throw new Error(`${where}: ${key} is not a real date (${row[key]})`);
  }
  if (row.date_precision != null) {
    if (!['day', 'month'].includes(row.date_precision)) throw new Error(`${where}: unknown date_precision`);
    if (row.date_precision === 'month' && !row.date?.endsWith('-01')) throw new Error(`${where}: month-precision date must use day 01`);
  }
  for (const key of ['source_published_at', 'source_updated_at']) {
    if (row[key] && row[key] > row.checked_at) throw new Error(`${where}: ${key} is after checked_at`);
  }
  if (row.own_use_share_percent != null) {
    const p = row.own_use_share_percent;
    if (typeof p !== 'number' || p < 0 || p > 100) throw new Error(`${where}: own_use_share_percent must be 0-100`);
  }
  if (row.application_status != null && !['open', 'closed', 'upcoming', 'rolling'].includes(row.application_status)) {
    throw new Error(`${where}: unknown application_status`);
  }
}

export function validateDataset(data) {
  for (const [name, rows] of Object.entries(data)) {
    const ids = new Set();
    for (const row of rows) {
      validateRecord(row, name);
      if (ids.has(row.id)) throw new Error(`${name}: duplicate id ${row.id}`);
      ids.add(row.id);
    }
  }
  for (const study of data['case-studies'] ?? []) {
    if (study.community_id && !data.communities.some(c => c.id === study.community_id)) {
      throw new Error(`case-studies/${study.id}: unknown community_id ${study.community_id}`);
    }
  }
}

// Most recent evidence check across every record: what the site-wide date means.
export function latestCheck(data) {
  return Object.values(data).flat().map(r => r.checked_at).sort().at(-1);
}
