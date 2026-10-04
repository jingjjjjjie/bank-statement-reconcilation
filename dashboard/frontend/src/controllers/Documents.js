import { node } from '../dom.js';
import { installReceipts } from '../receipts.js';
import { refreshNavigation } from '../api.js';

// Scope screen state and handlers to this cached Vue view.
export default function initialize(page) {
const { $, api, toast, pollVisible } = page;
/* Show saved progress for every prepared content-review document. */
let documentState = {prepared: false, documents: []};
let documentRequestMessage = "";
let executionRevision = 0;
let legacyLocations;
let extractionProgress = '';
let finalSnapshotPending = false;
let documentRows = '';

function sourceFiles(rows) {
  /* Display every original location while retaining one extraction record per hash. */
  return rows.flatMap(item => (item.paths?.length ? item.paths : [item.path]).map((path, index) => ({
    ...item, path: path.replaceAll('\\', '/'), name: path.split(/[\\/]/).pop(),
    duplicate: item.approved_duplicate || index > 0,
    duplicateLabel: item.approved_duplicate ? 'Approved duplicate' : index > 0 ? 'Exact duplicate' : '',
  })));
}

function folderTree(files, allFiles) {
  /* Build a stable folder hierarchy from original paths, independent of filtering. */
  let rootPath = (documentState.source_root || '').replaceAll('\\', '/').replace(/\/$/, '');
  if (!rootPath && allFiles.length) {
    const common = allFiles[0].path.split('/').slice(0, -1);
    for (const item of allFiles) {
      const parts = item.path.split('/').slice(0, -1);
      while (common.some((part, index) => part !== parts[index])) common.pop();
    }
    rootPath = common.join('/');
  }
  const tree = {name:rootPath.split('/').pop() || 'Documents', path:rootPath, folders:new Map(), files:[], count:0};
  for (const item of files) {
    const relative = item.path.startsWith(rootPath + '/') ? item.path.slice(rootPath.length + 1) : item.path;
    const parts = relative.split('/').filter(Boolean); parts.pop();
    let folder = tree; folder.count++;
    for (const name of parts) {
      if (!folder.folders.has(name)) folder.folders.set(name, {name, path:folder.path + '/' + name, folders:new Map(), files:[], count:0});
      folder = folder.folders.get(name); folder.count++;
    }
    folder.files.push(item);
  }
  return tree;
}

function renderDocuments() {
  /* Filter the current saved snapshot without changing workflow state. */
  const rows = documentState.documents;
  const search = $('#document-search').value.trim().toLowerCase();
  const filter = $('#document-filter').value;
  const files = sourceFiles(rows);
  const visible = files.filter(item => (filter === 'all' || (filter === 'duplicate' ? item.duplicate : item.status === filter)) &&
    `${item.name} ${item.path}`.toLowerCase().includes(search));
  $('#document-total').textContent = rows.length;
  $('#document-admin').textContent = rows.filter(item => item.status === 'Needs review').length;
  $('#document-complete').textContent = rows.filter(item => item.status === 'Complete').length;
  $('#document-summary').textContent = documentState.prepared ?
    `${visible.length} of ${files.length} files · ${rows.length} unique documents` :
    'Run documents to prepare your files.';
  const body = $('#document-rows'); body.replaceChildren();
  function appendFile(item, depth) {
    /* Keep duplicate evidence inspectable, but visually secondary to the retained copy. */
    const tr = node('tr', `document-file${item.duplicate ? ' duplicate-file' : ''}`), title = node('td');
    tr.style.setProperty('--folder-depth', depth);
    title.append(node('strong', '', item.name));
    title.title = item.path;
    const label = item.duplicateLabel || item.status;
    const status = node('span', `document-status ${item.duplicate ? 'duplicate' : item.status.toLowerCase().replaceAll(' ', '-')}`, label);
    const open = node('a', '', 'Open file');
    open.href = `/api/content-file?id=${encodeURIComponent(item.id)}`;
    open.target = '_blank'; open.rel = 'noopener';
    const file = node('td', 'document-actions');
    const extraction = node('a', 'receipt-review-link', 'Review Extraction');
    extraction.href = `/extraction-review?unit=${encodeURIComponent(item.id + ':0')}`;
    file.append(extraction, open);
    tr.append(title, node('td'), file);
    tr.children[1].append(status);
    body.append(tr);
  }
  function appendFolder(folder, depth) {
    /* Keep folder headings and all matching files visible. */
    const tr = node('tr', 'document-folder'), cell = node('td'), heading = node('div', 'folder-heading');
    tr.style.setProperty('--folder-depth', depth); cell.colSpan = 3;
    heading.title = folder.path;
    heading.append($('#document-folder-icon svg').cloneNode(true), node('span', 'folder-name', folder.name),
      node('small', 'folder-count', `${folder.count} ${folder.count === 1 ? 'file' : 'files'}`));
    cell.append(heading); tr.append(cell); body.append(tr);
    const compare = (left, right) => left.name.localeCompare(right.name, undefined, {numeric:true});
    [...folder.folders.values()].sort(compare).forEach(child => appendFolder(child, depth + 1));
    folder.files.sort(compare).forEach(item => appendFile(item, depth + 1));
  }
  if (visible.length) appendFolder(folderTree(visible, files), 0);
  $('#document-empty').hidden = !!visible.length;
  $('#document-empty').textContent = documentState.prepared ? 'No documents match this filter.' : 'Click Extract documents to get started.';
}

async function refreshDocuments() {
  /* Poll the checkpointed review while retaining search and filter choices. */
  const revision = executionRevision;
  const snapshot = await api('/api/document-status');
  // Older running servers expose exact-copy locations through their existing report.
  if (snapshot.prepared && snapshot.documents.some(item => !item.paths)) {
    legacyLocations ||= api('/api/state').then(data => new Map((data.automatic ? data.groups : [])
      .map(group => [group.hash, group.files.filter(file => file.valid).map(file => file.original)])))
      .catch(() => new Map());
    const locations = await legacyLocations;
    snapshot.documents = snapshot.documents.map(item => ({...item, paths:locations.get(item.id)?.length ? locations.get(item.id) : [item.path]}));
  }
  documentState = revision === executionRevision ? snapshot : {...snapshot, ...executionFields()};
  const rowsChanged = JSON.stringify(snapshot.documents) !== documentRows;
  documentRows = JSON.stringify(snapshot.documents);
  if (rowsChanged) renderDocuments();
  renderDocumentProgress();
  // Refresh the header when background extraction changes saved document readiness.
  const progress = JSON.stringify(snapshot.documents.map(item => [item.id, item.extracted, item.approved_duplicate]));
  if (progress !== extractionProgress) {
    const changed = extractionProgress !== '';
    extractionProgress = progress;
    refreshNavigation(changed).catch(error => toast(error.message));
  }
}

function setDocumentRequestMessage(message) {
  /* Show immediate feedback while preparing, starting, or stopping a batch. */
  documentRequestMessage = message;
  renderDocumentProgress();
}

function executionFields() {
  /* Keep a slow document snapshot from overwriting a newer stop acknowledgement. */
  return Object.fromEntries(['running', 'stop_requested', 'active_processes', 'execution_status', 'run_error', 'phase', 'elapsed_seconds']
    .map(key => [key, documentState[key]]));
}

function setExecution(state) {
  /* Apply lightweight execution updates independently of document scans. */
  executionRevision++;
  if (documentState.running && state.running === false) finalSnapshotPending = true;
  Object.assign(documentState, state);
  renderDocumentProgress();
}

async function refreshExecution() {
  /* Keep Stop responsive while a full document snapshot is still loading. */
  const revision = executionRevision;
  const state = await api('/api/content/execution');
  if (revision === executionRevision) setExecution(state);
}

function renderDocumentProgress() {
  /* Count saved pages and assemblies together so progress never resets by stage. */
  const rows = documentState.documents;
  const sum = field => rows.reduce((total, row) => total + (row[field] || 0), 0);
  const done = sum('units_read') + sum('assembly_done');
  const total = sum('units_total') + sum('assembly_total');
  const extracted = rows.filter(row => row.extracted).length;
  const processed = rows.filter(row => row.units_total > 0 && row.units_read === row.units_total &&
    row.assembly_done === row.assembly_total).length;
  const stopping = documentState.stop_requested && documentState.running;
  const bar = $('#document-progress-bar');
  const busy = !!documentRequestMessage;
  const preparing = busy && !documentState.prepared;
  $('#run-documents').textContent = documentState.running ? (stopping ? 'Stopping...' : 'Extracting...') :
    preparing ? 'Preparing...' : busy ? 'Starting...' : extracted || done ? 'Resume extraction' : 'Extract documents';
  $('#run-documents').disabled = busy || !!documentState.running || (!!rows.length && extracted === rows.length);
  $('#stop-documents').disabled = !documentState.running || !!documentState.stop_requested;
  $('#stop-documents').textContent = stopping ? 'Stopping...' : 'Stop';
  bar.value = total ? Math.floor(done / total * 100) : 0;
  const percent = bar.value;
  if (preparing) bar.removeAttribute('value');
  $('#document-progress-stage').textContent = preparing ? 'Preparing documents...' : rows.length
    ? `${processed} / ${rows.length} documents processed` : 'Ready to extract';
  $('#document-progress-count').textContent = preparing || !total ? '' : `${done} / ${total} steps (${percent}%)`;
  const track = $('#document-progress-track');
  track.dataset.busy = String(preparing);
  track.dataset.running = String(!!documentState.running && !stopping);
  track.querySelector('.progress-fill').style.transform = `scaleX(${percent / 100})`;
  $('#document-run-status').textContent = documentState.execution_status === 'stop_failed'
    ? documentState.run_error : stopping
    ? `Stopping - waiting for ${documentState.active_processes || 0} active processes to exit.`
    : (!documentState.running && documentRequestMessage) || documentState.run_error ||
      (documentState.running ? `${documentState.phase || 'Extracting supporting documents'} - ${documentState.active_processes || 0} active processes - ${documentState.elapsed_seconds || 0}s elapsed` :
        'Open Review Extraction beside a document to check its extraction.');
}

function rememberFilters() {
  /* Keep this browser's document view when navigating away or reloading. */
  try {
    localStorage.setItem('document-status-filters', JSON.stringify({
      search: $('#document-search').value, status: $('#document-filter').value,
    }));
  } catch { /* Storage restrictions must not prevent filtering. */ }
  renderDocuments();
}

/* Restore preferences only; document progress always comes from saved review state. */
try {
  const filters = JSON.parse(localStorage.getItem('document-status-filters') || '{}');
  if (typeof filters?.search === 'string') $('#document-search').value = filters.search;
  if ([...$('#document-filter').options].some(option => option.value === filters?.status)) {
    $('#document-filter').value = filters.status;
  }
} catch { /* Ignore unavailable storage or invalid old preferences. */ }
$('#document-search').oninput = rememberFilters;
$('#document-filter').onchange = rememberFilters;
refreshDocuments().catch(error => toast(error.message));
pollVisible(async () => {
  if (!documentState.running && !documentRequestMessage && !finalSnapshotPending) return;
  finalSnapshotPending = false;
  try { await refreshDocuments(); }
  catch (error) { finalSnapshotPending = true; throw error; }
}, 2000);
pollVisible(refreshExecution, 500);

installReceipts(page, {getDocumentState: () => documentState, setDocumentRequestMessage, refreshDocuments, setExecution, refreshExecution});


page.onRefresh(refreshDocuments, ['/api/receipts/', '/api/content/']);
}
