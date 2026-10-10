import { reactive } from 'vue';

// Only shared display state lives here. The server owns evidence and decisions.
export const appState = reactive({
  session: null, workspace: { name: 'Loading review…', period: '' },
  resumePath: '/documents', steps: [], navigationReviewId: null, syncing: false, liveConnected: false, changes: 0, revisions: {}, toast: '', error: '',
});
export const pages = new Set();
let sessionRequest, navigationRequest, toastTimer;
let navigationRevision = 0;
const displayPaths = new Set(['/api/workflow-checks', '/api/document-status', '/api/matching']);
const liveValues = new Map(), liveVersions = new Map();
let liveStream;

export function toast(message) {
  appState.toast = message;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { appState.toast = ''; }, 5000);
}

export async function loadSession() {
  // Coalesce simultaneous initial requests and detect workspace/server changes.
  if (!sessionRequest) sessionRequest = fetch('/api/session')
    .then(async response => {
      if (!response.ok) throw Error('Unable to connect to the dashboard');
      const session = await response.json();
      if (session.review_id !== appState.session?.review_id) {
        liveValues.clear(); liveVersions.clear();
        appState.navigationReviewId = null;
        appState.syncing = false;
      }
      appState.session = session;
      return appState.session;
    }).finally(() => { sessionRequest = null; });
  return sessionRequest;
}

export async function api(path, body, options = {}) {
  const session = appState.session || await loadSession();
  if (path === '/api/session' && body === undefined) return session;
  if (path === '/api/source/start' && [...pages].some(page => page.isDirty())) {
    const source = await api('/api/source');
    if (source.active !== source.selected?.path &&
        !confirm('Switch workspace and discard unsaved edits?')) throw Error('Workspace switch cancelled');
  }
  if (body === undefined && appState.liveConnected && liveValues.has(path)) return structuredClone(liveValues.get(path));
  const response = await fetch(path, body === undefined ? { signal: options.signal,
    headers: displayPaths.has(path) ? { Prefer: 'stale-while-revalidate' } : {},
  } : {
    method: 'POST', signal: options.signal,
    headers: { 'Content-Type': 'application/json', 'X-Review-Token': session.token,
      'X-Review-Id': options.reviewId || session.review_id },
    body: JSON.stringify(body),
  });
  const text = await response.text();
  let data;
  try { data = JSON.parse(text); }
  catch { throw Error(`The server could not complete this request (HTTP ${response.status}). Your edits are still on this page.`); }
  if (!response.ok) throw Error(data.error || 'Request failed');
  if (body === undefined && session.review_id === appState.session?.review_id && response.headers.has('X-Workspace-Revision')) {
    liveVersions.set(path, Number(response.headers.get('X-Workspace-Revision')));
    if (response.headers.get('X-Workspace-Updating') === 'true') appState.syncing = true;
  }
  if (body !== undefined) {
    const selectionOnly = path.startsWith('/api/source/') && path !== '/api/source/bank-prepare';
    if (!selectionOnly) {
      appState.changes++;
      appState.revisions[path] = (appState.revisions[path] || 0) + 1;
    }
    if (path === '/api/source/start') await loadSession();
    // Saved extraction and matching decisions update their completion ticks.
    refreshNavigation(true).catch(error => toast(error.message));
  }
  return data;
}

// Refresh a cached view only after a write to the data it displays.
export function revisionFor(prefixes) {
  if (!prefixes) return appState.changes;
  return Object.entries(appState.revisions).reduce((total, [path, revision]) =>
    total + (prefixes.some(prefix => path.startsWith(prefix)) ? revision : 0), 0);
}

export async function refreshNavigation(invalidate = false) {
  // A save during a pending refresh must get a subsequent, current snapshot.
  if (invalidate) navigationRevision++;
  if (!navigationRequest) navigationRequest = (async () => {
    let revision, reviewId;
    do {
      revision = navigationRevision;
      reviewId = appState.session?.review_id;
      const [workspace, workflow] = await Promise.all([
        api('/api/workspace'), api('/api/workflow-checks'),
      ]);
      if (reviewId !== appState.session?.review_id) continue;
      appState.workspace = workspace;
      appState.steps = workflow.steps;
      appState.navigationReviewId = reviewId;
    } while (reviewId !== appState.session?.review_id || revision !== navigationRevision);
  })().finally(() => { navigationRequest = null; });
  return navigationRequest;
}

// One event stream replaces per-tab progress requests; normal HTTP remains the reconnect fallback.
export function startLive() {
  if (liveStream) return;
  window.addEventListener('online', recoverLive);
  liveStream = new EventSource('/api/live');
  liveStream.onopen = () => { appState.liveConnected = true; liveValues.clear(); };
  liveStream.onerror = () => { appState.liveConnected = false; liveValues.clear(); };
  liveStream.onmessage = async message => {
    const event = JSON.parse(message.data);
    if (event.review_id !== appState.session?.review_id) {
      // Retain dirty drafts; their existing review-id guard rejects writes to another workspace.
      if ([...pages].some(page => page.isDirty())) return;
      liveValues.clear(); liveVersions.clear();
      await loadSession();
      await refreshNavigation(true);
      return;
    }
    if (event.kind === 'progress') liveValues.set(event.path, event.data);
    if (event.kind === 'updating') appState.syncing = true;
    if (event.kind === 'sync') appState.syncing = event.updating;
    if (event.kind === 'error') { toast(event.error); return; }
    if (event.kind !== 'snapshot' || liveVersions.get(event.path) === event.version) return;
    if (event.path === '/api/workflow-checks') refreshNavigation().catch(error => toast(error.message));
    for (const page of pages) page.liveUpdate?.(event.path);
  };
}

export function stopLive() {
  window.removeEventListener('online', recoverLive);
  liveStream?.close(); liveStream = null;
  liveValues.clear(); appState.liveConnected = false;
}

function recoverLive() {
  // A revision notice received while offline is not proof its payload was loaded.
  liveVersions.clear();
  refreshNavigation().catch(error => toast(error.message));
  for (const page of pages) for (const path of displayPaths) page.liveUpdate?.(path);
}
