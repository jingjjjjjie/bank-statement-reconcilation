import { appState } from '../api.js';
import { node } from '../dom.js';
import { renderOfficePreview } from '../office.js';

// Scope screen state and handlers to this cached Vue view.
export default function initialize(page) {
const { root, $, api, toast, pollVisible, showDevelopmentMode, navigate, routeQuery } = page;
let token;
/* Folder selection is read-only until the user starts a review. */
let sourceState = {};
let previewToken = null, preparing = false;
// Returning to the active workspace only navigates; it never starts processing.
function canResume() {
  return !!sourceState.active && sourceState.active === sourceState.selected?.path;
}
async function loadPreview() {
  const workspace = sourceState.workspace;
  previewToken = null;
  $('#prepare-source').hidden = !canResume();
  $('#start-source').textContent = canResume() ? 'Resume workspace' : 'Proceed';
  if (canResume()) {
    $('#workspace-status').textContent = 'Workspace in progress';
    $('#source-preview').textContent = 'Continue where you left off.';
    $('#start-source').disabled = false;
    return;
  }
  $('#start-source').disabled = true;
  $('#workspace-status').textContent = 'Checking workspace';
  $('#source-preview').textContent = 'Checking exact duplicates…';
  try {
    const preview = await api('/api/source/preview');
    if (sourceState.workspace !== workspace || $('#source-path').value.trim() !== workspace) return;
    previewToken = preview.token;
    $('#workspace-status').textContent = 'Ready to proceed';
    $('#source-preview').textContent = preview.groups ?
      `${preview.groups} exact duplicate groups found. Proceed to copy them into output/duplicates/ and continue automatically.` :
      'Both input folders are ready. Continue to the document list.';
    $('#start-source').disabled = false;
  } catch (error) {
    $('#workspace-status').textContent = 'Workspace needs attention';
    $('#source-preview').textContent = error.message;
  }
}
function showSource(data) {
  sourceState = {...sourceState, ...data};
  const selected = sourceState.workspace ? sourceState.selected : null;
  $('#selected-source').hidden = !selected;
  $('#source-action').hidden = !selected;
  if (selected) {
    $('#source-path').value = sourceState.workspace;
    $('#workspace-name').textContent = sourceState.workspace.split(/[\\/]/).filter(Boolean).pop();
    $('#workspace-location').textContent = sourceState.workspace;
    $('#statement-name').textContent = sourceState.bank.path.split(/[\\/]/).pop();
    $('#document-count').textContent = `${selected.files.toLocaleString()} supporting files`;
    $('#browse-source').textContent = 'Change workspace';
  }
  if (Object.hasOwn(data, 'selected') && selected) loadPreview();

}

/* Keep errors visible without changing the active review. */
async function sourceAction(action) {
  $('#source-error').hidden = true;
  try {
    await action();
  } catch (error) {
    $('#source-error').textContent = error.message;
    $('#source-error').hidden = false;
  }
}

let browserPath = null;
async function browse(path) {
  const items = $('#browser-items');
  items.replaceChildren();
  $('#browser-error').hidden = true;
  $('#browser-use').disabled = true;
  $('#browser-current').textContent = 'Loading folders…';
  try {
    const query = new URLSearchParams();
    if (path) query.set('path', path);
    const data = await api('/api/source/browse?' + query);
    browserPath = data.path;
    $('#browser-use').disabled = false;
    $('#browser-current').textContent = data.path || 'Computer';
    $('#browser-use').hidden = !data.path;
    const addItem = (label, target, action) => {
      const button = node('button', 'browser-item', label);
      button.type = 'button'; button.onclick = () => action(target); items.append(button);
    };
    if (data.path) addItem('↖ Up one level', data.parent, browse);
    for (const folder of data.folders) addItem('📁 ' + (folder.split(/[\\/]/).filter(Boolean).pop() || folder), folder, browse);
    if (!data.folders.length) items.append(node('p', '', 'No subfolders here.'));
  } catch (error) {
    $('#browser-error').textContent = error.message;
    $('#browser-error').hidden = false;
  }
}
function openBrowser() {
  $('#path-browser').showModal();
  browse(sourceState.workspace || null);
}
$('#browse-source').onclick = () => openBrowser();
$('#browser-close').onclick = () => $('#path-browser').close();
$('#browser-use').onclick = async () => {
  $('#browser-error').hidden = true;
  $('#browser-use').disabled = true;
  try {
    const result = await api('/api/source/workspace-select', {path: browserPath});
    showSource(result); $('#path-browser').close();
  } catch (error) {
    $('#browser-error').textContent = error.message;
    $('#browser-error').hidden = false;
  } finally { $('#browser-use').disabled = false; }
};
$('#source-path').oninput = () => {
  previewToken = null; $('#start-source').disabled = true;
  $('#workspace-status').textContent = 'Confirm your new folder';
  $('#source-preview').textContent = 'Select workspace to check this path before proceeding.';
};
$('#select-source').onclick = () => sourceAction(async () => {
  const result = await api('/api/source/workspace-select', {path: $('#source-path').value});
  showSource(result);
});
function showPreparation(data) {
  // Display measured stage counts and keep failures visible for retry.
  if (data.status === 'idle') return;
  $('#source-preparation').hidden = false;
  if (data.status === 'running') $('#workspace-status').textContent = 'Preparing files';
  const labels = {duplicates:'Copying exact duplicates', excel:'Converting Excel previews',
    files:'Preparing PDF pages and other files', complete:'Preparation complete'};
  $('#preparation-stage').textContent = data.status === 'failed' ? 'Preparation needs attention' : labels[data.stage];
  $('#preparation-bar').value = data.percent || 0;
  $('#preparation-detail').textContent = data.error || `${data.file || ''}${data.total ? ` (${data.done} / ${data.total})` : ''}`;
  $('#preparation-warnings').hidden = !data.warnings?.length;
  $('#preparation-warnings').textContent = data.warnings?.join('\n') || '';
}
async function prepareFiles() {
  // Keep this page responsive while Python copies, converts and prepares original inputs.
  if (preparing) return;
  preparing = true;
  const controls = [...root.querySelectorAll('button, input')];
  const disabled = controls.map(control => control.disabled);
  controls.forEach(control => { control.disabled = true; });
  showPreparation({status:'running', stage:'duplicates', percent:0, file:'Checking files'});
  $('#source-preparation').scrollIntoView({block:'nearest'});
  try {
    if (!previewToken) previewToken = (await api('/api/source/preview')).token;
    const result = await api('/api/source/start', {preview: previewToken, prepare_files:true});
    showPreparation({status:'complete', stage:'complete', percent:100, warnings:result.warnings});
    if (!result.warnings?.length) await navigate('/documents');
    else showSource(await api('/api/source'));
  } catch (error) {
    showPreparation({status:'failed', error:error.message});
    throw error;
  } finally {
    preparing = false;
    controls.forEach((control, index) => { control.disabled = disabled[index]; });
  }
}
pollVisible(async () => {
  if (preparing) showPreparation(await api('/api/source/progress'));
}, 400);
$('#prepare-source').onclick = () => sourceAction(prepareFiles);
$('#start-source').onclick = () => sourceAction(async () => {
  if (canResume()) await navigate(appState.resumePath);
  else await prepareFiles();
});
Promise.all([api('/api/session'), api('/api/source')]).then(([session, source]) => {
  token = session.token;
  showSource(source);
  api('/api/source/progress').then(progress => {
    if (progress.workspace === source.workspace) showPreparation(progress);
  }).catch(error => toast(error.message));
}).catch(error => {
  $('#source-error').textContent = error.message;
  $('#source-error').hidden = false;
});

}
