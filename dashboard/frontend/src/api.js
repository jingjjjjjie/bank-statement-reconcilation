import { reactive } from 'vue';

// Only shared display state lives here. The server owns evidence and decisions.
export const appState = reactive({
  session: null, workspace: { name: 'Loading review…', period: '' },
  steps: [], development: false, changes: 0, toast: '', error: '',
});
export const pages = new Set();
let sessionRequest, navigationRequest, toastTimer;

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
      appState.session = await response.json();
      return appState.session;
    }).finally(() => { sessionRequest = null; });
  return sessionRequest;
}

export async function api(path, body, options = {}) {
  const session = appState.session || await loadSession();
  if (path === '/api/session' && body === undefined) return session;
  if (path === '/api/source/start' && [...pages].some(page => page.isDirty()) &&
      !confirm('Switch workspace and discard unsaved edits?')) throw Error('Workspace switch cancelled');
  const response = await fetch(path, body === undefined ? { signal: options.signal } : {
    method: 'POST', signal: options.signal,
    headers: { 'Content-Type': 'application/json', 'X-Review-Token': session.token,
      'X-Review-Id': options.reviewId || session.review_id },
    body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw Error(data.error || 'Request failed');
  if (body !== undefined) {
    appState.changes++;
    if (path === '/api/source/start') await loadSession();
    if (path === '/api/development-mode') appState.development = data.enabled;
    // Reviewing extracted fields does not change pipeline stage completion.
    if (!['/api/receipts/accept', '/api/receipts/classify'].includes(path)) {
      refreshNavigation().catch(error => toast(error.message));
    }
  }
  return data;
}

export async function refreshNavigation() {
  // Shared metadata is fetched once, then refreshed after actions rather than on every view.
  if (!navigationRequest) navigationRequest = Promise.all([
    api('/api/workspace'), api('/api/workflow-checks'), api('/api/development-mode'),
  ]).then(([workspace, workflow, development]) => {
    appState.workspace = workspace;
    appState.steps = workflow.steps;
    appState.development = development.enabled;
  }).finally(() => { navigationRequest = null; });
  return navigationRequest;
}
