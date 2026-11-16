'use strict';

const $ = id => document.getElementById(id);
const state = { dbId: null, tableId: null, table: null, rowId: null, busy: false, uncertain: false };
const types = ['integer', 'real', 'char', 'string', 'color', 'colorInvl'];
const dialog = $('editor');
let submitEditor = null;
let editorLocked = false;

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function button(text, handler) {
  const node = element('button', text);
  node.type = 'button';
  node.addEventListener('click', handler);
  return node;
}
function input(value = '') {
  const node = element('input');
  node.type = 'text';
  node.value = value;
  return node;
}
function field(caption, control) {
  const node = element('label', undefined, 'field');
  node.append(element('span', caption), control);
  return node;
}
function status(message, error = false) {
  $('status').textContent = message;
  $('status').classList.toggle('error', error);
}
function updateControls() {
  const locked = state.busy || state.uncertain;
  for (const id of ['new-database', 'import']) $(id).disabled = locked;
  $('new-table').disabled = locked || !state.dbId;
  $('export').disabled = state.busy || !state.dbId;
  for (const id of ['add-row', 'deduplicate', 'delete-table']) $(id).disabled = locked || !state.table;
  $('edit-row').disabled = locked || !state.rowId;
  $('refresh').disabled = state.busy;
  $('databases').disabled = state.busy;
  $('tables').querySelectorAll('button').forEach(node => { node.disabled = state.busy; });
  $('save').disabled = state.busy || editorLocked;
  $('cancel').disabled = state.busy;
  $('editor-fields').disabled = state.busy;
  $('save').textContent = state.busy ? 'Збереження…' : dialog.dataset.action || 'Зберегти';
  $('workspace').setAttribute('aria-busy', String(state.busy));
}
class ApiError extends Error {
  constructor(message, uncertain = false) { super(message); this.uncertain = uncertain; }
}
// Preserve integers beyond JavaScript's exact numeric range as decimal text.
// Numeric input is sent as text and normalized by the existing server types.
function parseResponse(text) {
  return JSON.parse(text, (key, value, context) => {
    if (typeof value === 'number' && Number.isInteger(value) && !Number.isSafeInteger(value)) {
      if (context && context.source) return context.source;
      throw new Error('Оновіть браузер для точного відображення великих чисел.');
    }
    return value;
  });
}
async function request(path, { method = 'GET', data, raw, text = false } = {}) {
  const mutation = method !== 'GET';
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 10000);
  try {
    const response = await fetch('/api' + path, {
      method, signal: controller.signal,
      headers: data !== undefined || raw !== undefined ? { 'Content-Type': 'application/json' } : {},
      body: raw !== undefined ? raw : data !== undefined ? JSON.stringify(data) : undefined,
    });
    const body = await response.text();
    if (!response.ok) {
      let message = `Сервер повернув HTTP ${response.status}.`;
      try {
        const detail = JSON.parse(body).error;
        if (detail && typeof detail.message === 'string') {
          message = detail.message + (detail.field ? ` (поле: ${detail.field})` : '');
        }
      } catch { /* Keep fallback for non-JSON responses. */ }
      throw new ApiError(message, mutation && response.status >= 500);
    }
    if (response.status === 204) return null;
    if (text) return body;
    try { return parseResponse(body); }
    catch (error) { throw new ApiError('Не вдалося прочитати JSON-відповідь. ' + error.message, mutation); }
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError(error.name === 'AbortError'
      ? 'Сервер не відповів вчасно. Оновіть дані перед повторенням дії.'
      : 'Немає зв’язку із сервером. Перевірте його запуск і натисніть «Оновити».', mutation);
  } finally { clearTimeout(timer); }
}
async function perform(operation, form = false) {
  if (state.busy) return;
  state.busy = true;
  updateControls();
  status('Очікуємо відповідь сервера…');
  try { await operation(); }
  catch (error) {
    if (error.uncertain || !form) state.uncertain = true;
    if (form) {
      editorLocked = Boolean(error.uncertain);
      $('form-error').textContent = error.message + (editorLocked
        ? ' Закрийте форму й оновіть дані перед повторенням дії.' : '');
    }
    status(error.message, true);
  } finally {
    state.busy = false;
    updateControls();
  }
}
function tablePath() { return `/databases/${state.dbId}/tables/${state.tableId}`; }
async function refreshData(message = 'Дані оновлено') {
  const databases = await request('/databases');
  const selected = databases.find(db => db.id === state.dbId);
  const database = selected ? await request(`/databases/${selected.id}`) : null;
  const found = database && database.tables.find(table => table.id === state.tableId);
  const table = found ? await request(`/databases/${database.id}/tables/${found.id}`) : null;
  state.dbId = database ? database.id : null;
  state.tableId = table ? table.id : null;
  state.table = table;
  state.rowId = null;
  state.uncertain = false;
  const select = $('databases');
  select.replaceChildren(new Option('Виберіть базу…', ''));
  for (const db of databases) {
    const option = new Option(db.name, db.id);
    option.title = db.id;
    select.add(option);
  }
  select.value = state.dbId || '';
  $('tables').replaceChildren();
  for (const entry of database ? database.tables : []) {
    const node = button(entry.name, () => {
      state.tableId = entry.id;
      perform(() => refreshData());
    });
    node.setAttribute('aria-current', String(entry.id === state.tableId));
    $('tables').append(node);
  }
  $('table-title').textContent = table ? table.name : 'Ваші дані, по порядку';
  $('database-title').textContent = database ? database.name : 'Створіть базу або виберіть її ліворуч.';
  renderTable();
  status(message);
}
function colorText(value) { return `RGB(${value.red}, ${value.green}, ${value.blue})`; }
function displayValue(value) {
  if (value && typeof value === 'object') {
    if ('red' in value) return colorText(value);
    if ('start' in value) return `${colorText(value.start)} → ${colorText(value.end)}`;
  }
  return String(value);
}
function selectRow(id) {
  if (state.busy) return;
  state.rowId = id;
  $('data-table').querySelectorAll('tbody tr').forEach(row => {
    row.setAttribute('aria-selected', String(row.dataset.id === id));
  });
  updateControls();
}
function renderTable() {
  const head = $('data-table').tHead;
  const body = $('data-table').tBodies[0];
  head.replaceChildren(); body.replaceChildren();
  const table = state.table;
  $('empty').hidden = Boolean(table && table.rows.length);
  $('empty').textContent = table ? 'Таблиця порожня. Додайте перший рядок.' : 'Виберіть або створіть таблицю ліворуч.';
  $('counts').textContent = table
    ? `Рядків: ${table.rows.length}   /   Колонок: ${table.columns.length}   ·   Збережено на сервері`
    : 'Зміни зберігаються автоматично.';
  if (!table) return;
  const header = element('tr'); header.append(element('th', '№'));
  for (const column of table.columns) {
    const cell = element('th', column.name); cell.scope = 'col';
    cell.append(element('span', column.type, 'type')); header.append(cell);
  }
  head.append(header);
  table.rows.forEach((row, index) => {
    const tr = element('tr'); tr.dataset.id = row.id; tr.tabIndex = 0;
    tr.setAttribute('aria-selected', 'false');
    tr.append(element('td', String(index + 1)));
    for (const column of table.columns) {
      const value = row.values[column.name];
      const cell = element('td');
      if (column.type === 'color') {
        const swatch = element('span', undefined, 'swatch');
        swatch.style.backgroundColor = `rgb(${value.red}, ${value.green}, ${value.blue})`;
        swatch.setAttribute('aria-hidden', 'true'); cell.append(swatch);
      }
      const text = displayValue(value);
      cell.append(document.createTextNode(text)); cell.title = text; tr.append(cell);
    }
    tr.addEventListener('click', () => selectRow(row.id));
    tr.addEventListener('dblclick', () => { selectRow(row.id); openRow(true); });
    tr.addEventListener('keydown', event => {
      if (event.key === ' ' || event.key === 'Enter') { event.preventDefault(); selectRow(row.id); }
    });
    body.append(tr);
  });
}
function openEditor(title, build, submit, action = 'Зберегти') {
  if (state.busy || state.uncertain) return;
  $('dialog-title').textContent = title;
  $('editor-fields').replaceChildren();
  $('form-error').textContent = '';
  editorLocked = false;
  dialog.dataset.action = action;
  const getter = build($('editor-fields'));
  submitEditor = async () => {
    const result = await submit(getter());
    dialog.close();
    try { await refreshData(result || 'Зміни збережено'); }
    catch (error) { state.uncertain = true; throw error; }
  };
  updateControls(); dialog.showModal();
}
function openDatabase() {
  openEditor('Нова база', fields => {
    const name = input(); name.placeholder = 'Наприклад, Навчальна колекція';
    fields.append(field('Назва бази', name)); return () => name.value;
  }, async name => {
    const result = await request('/databases', { method: 'POST', data: { name } });
    state.dbId = result.id; state.tableId = null;
  });
}
function openTable() {
  if (!state.dbId) return;
  const dbId = state.dbId;
  openEditor('Нова таблиця', fields => {
    const name = input(); fields.append(field('Назва таблиці', name));
    fields.append(element('p', 'Назва колонки / тип', 'schema-head'));
    const list = element('div'); fields.append(list);
    const entries = [];
    function addColumn() {
      const row = element('div', undefined, 'schema-row');
      const columnName = input(); columnName.setAttribute('aria-label', 'Назва колонки');
      const kind = element('select'); kind.setAttribute('aria-label', 'Тип колонки');
      for (const type of types) kind.add(new Option(type, type));
      const entry = { row, name: columnName, kind }; entries.push(entry);
      row.append(columnName, kind, button('Прибрати', () => {
        row.remove(); entries.splice(entries.indexOf(entry), 1);
      })); list.append(row);
    }
    fields.append(button('+ Колонка', addColumn)); addColumn();
    return () => ({ name: name.value, columns: entries.map(entry => ({ name: entry.name.value, type: entry.kind.value })) });
  }, async data => {
    const result = await request(`/databases/${dbId}/tables`, { method: 'POST', data });
    state.tableId = result.id;
  });
}
function rgbEditor(value) {
  const node = element('div', undefined, 'rgb');
  const channels = {};
  for (const [key, caption] of [['red', 'R'], ['green', 'G'], ['blue', 'B']]) {
    const control = input(value ? value[key] : 0);
    control.type = 'number'; control.min = '0'; control.max = '255'; control.step = '1';
    channels[key] = control;
    const label = element('label', caption); label.append(control); node.append(label);
  }
  return { node, get: () => {
    const result = {};
    for (const [key, control] of Object.entries(channels)) {
      if (!/^\d+$/.test(control.value) || Number(control.value) > 255) {
        control.focus(); throw new Error('Канал RGB має бути цілим числом від 0 до 255.');
      }
      result[key] = Number(control.value);
    }
    return result;
  } };
}
function openRow(edit = false) {
  if (!state.table || state.busy || state.uncertain) return;
  const row = edit ? state.table.rows.find(item => item.id === state.rowId) : null;
  if (edit && !row) return;
  const path = tablePath();
  openEditor(edit ? 'Редагувати рядок' : 'Додати рядок', fields => {
    const getters = new Map();
    for (const column of state.table.columns) {
      const value = row ? row.values[column.name] : undefined;
      let node, getter;
      if (column.type === 'color') {
        const rgb = rgbEditor(value); node = rgb.node; getter = rgb.get;
      } else if (column.type === 'colorInvl') {
        node = element('div', undefined, 'interval');
        const start = rgbEditor(value && value.start), end = rgbEditor(value && value.end);
        for (const [caption, editor] of [['Від', start], ['До', end]]) {
          const line = element('div', undefined, 'interval-line');
          line.append(element('span', caption), editor.node); node.append(line);
        }
        getter = () => ({ start: start.get(), end: end.get() });
      } else {
        node = input(value === undefined ? '' : String(value));
        if (column.type === 'integer' || column.type === 'real') {
          node.inputMode = column.type === 'integer' ? 'numeric' : 'decimal';
          node.placeholder = column.type === 'integer' ? 'Ціле число' : 'Число, наприклад 95.5';
        }
        const control = node; getter = () => control.value;
      }
      const caption = `${column.name} · ${column.type}`;
      if (column.type === 'color' || column.type === 'colorInvl') {
        const group = element('div', undefined, 'field');
        group.setAttribute('role', 'group'); group.setAttribute('aria-label', caption);
        group.append(element('span', caption), node); fields.append(group);
      } else { fields.append(field(caption, node)); }
      getters.set(column.name, getter);
    }
    return () => Object.fromEntries([...getters].map(([name, get]) => [name, get()]));
  }, async values => {
    await request(edit ? `${path}/rows/${row.id}` : `${path}/rows`, {
      method: edit ? 'PATCH' : 'POST', data: edit ? { updates: values } : { values },
    });
  });
}
$('editor-form').addEventListener('submit', event => {
  event.preventDefault();
  if (!editorLocked && submitEditor) perform(submitEditor, true);
});
$('cancel').addEventListener('click', () => { if (!state.busy) dialog.close(); });
dialog.addEventListener('cancel', event => { if (state.busy) event.preventDefault(); });
$('refresh').addEventListener('click', () => perform(() => refreshData()));
$('databases').addEventListener('change', () => {
  state.dbId = $('databases').value || null; state.tableId = null;
  perform(() => refreshData());
});
$('new-database').addEventListener('click', openDatabase);
$('new-table').addEventListener('click', openTable);
$('add-row').addEventListener('click', () => openRow());
$('edit-row').addEventListener('click', () => openRow(true));
$('deduplicate').addEventListener('click', () => perform(async () => {
  const result = await request(tablePath() + '/remove-duplicates', { method: 'POST' });
  await refreshData(`Вилучено: ${result.removed}. Залишилося рядків: ${result.remaining_rows}.`);
}));
$('delete-table').addEventListener('click', () => {
  const path = tablePath();
  openEditor('Видалити таблицю?', fields => {
    fields.append(element('p', 'Таблицю та всі її рядки буде видалено. Продовжити?'));
    return () => null;
  }, async () => {
    await request(path, { method: 'DELETE' }); state.tableId = null;
    return 'Таблицю видалено';
  }, 'Видалити');
});
$('import').addEventListener('click', () => $('import-file').click());
$('import-file').addEventListener('change', () => {
  const file = $('import-file').files[0]; $('import-file').value = '';
  if (!file) return;
  perform(async () => {
    // Send original JSON text: importing must not round large integer values.
    const raw = (await file.text()).replace(/^\uFEFF/, '');
    const result = await request('/databases/import', { method: 'POST', raw });
    state.dbId = result.id; state.tableId = null;
    await refreshData('Імпортовано нову базу');
  });
});
$('export').addEventListener('click', () => perform(async () => {
  const text = await request(`/databases/${state.dbId}/export`, { text: true });
  const url = URL.createObjectURL(new Blob([text], { type: 'application/json;charset=utf-8' }));
  const link = element('a'); link.href = url; link.download = `${state.dbId}.json`;
  document.body.append(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  status('Експорт передано браузеру для завантаження');
}));
updateControls();
perform(() => refreshData());
