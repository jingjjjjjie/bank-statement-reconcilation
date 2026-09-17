/* Folder selection is read-only until the user starts a review. */
let sourceState = {};
let previewToken = null;
async function loadPreview() {
  const workspace = sourceState.workspace;
  previewToken = null;
  $('#start-source').disabled = true;
  $('#workspace-status').textContent = 'Checking workspace';
  $('#source-preview').textContent = 'Checking exact duplicates…';
  try {
    const preview = await api('/api/source/preview');
    if (sourceState.workspace !== workspace || $('#source-path').value.trim() !== workspace) return;
    previewToken = preview.token;
    $('#workspace-status').textContent = 'Ready to proceed';
    $('#source-preview').textContent = preview.groups ?
      `${preview.groups} duplicate groups found. A report will be created when you proceed.` :
      'Both input folders are ready. Continue to document review.';
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
$('#start-source').onclick = () => sourceAction(async () => {
  $('#start-source').disabled = true;
  try {
    await api('/api/source/start', {preview: previewToken});
    location.assign('/review');
  } finally {$('#start-source').disabled = false;}
});
Promise.all([api('/api/session'), api('/api/source')]).then(([session, source]) => {
  token = session.token;
  showSource(source);
}).catch(error => {
  $('#source-error').textContent = error.message;
  $('#source-error').hidden = false;
});
