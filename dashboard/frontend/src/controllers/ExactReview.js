import { node } from '../dom.js';
import { renderOfficePreview } from '../office.js';

// Scope screen state and handlers to this cached Vue view.
export default function initialize(page) {
const { root, $, api, toast, pollVisible, showDevelopmentMode, navigate, routeQuery } = page;
let token;
/* Shared state stays small; the server owns all file checks and mutations. */
let state, selected, filter = 'all', busy = false, renderVersion = 0;
const docs = new Map();
function visibleGroups() {const q = $('#search').value.toLowerCase(); return state.groups.filter(g => (filter === 'all' || g.status === filter) && (g.id + ' ' + g.files.map(f => f.name + ' ' + f.original).join(' ')).toLowerCase().includes(q));}

/* Refresh counts and queue independently of the document previews. */
function render() {
  $('#validate').disabled = busy;
  $('#total').textContent = state.groups.length; $('#pending').textContent = state.pending;
  $('#reviewed').replaceChildren(document.createTextNode(state.reviewed), node('em', '', `/ ${state.groups.length}`));
  $('#progress').style.width = `${state.groups.length ? state.reviewed / state.groups.length * 100 : 0}%`;
  $('#attention').textContent = state.attention ? `${state.attention} group(s) require attention` : 'One selection per group';
  $('#validate').classList.toggle('ready', state.pending === 0 && state.attention === 0);
  $('#folder').textContent = state.folder;
  const groups = visibleGroups(); $('#queue-count').textContent = `${groups.length} ${groups.length === 1 ? 'group' : 'groups'}`;
  if (!groups.some(g => g.id === selected)) selected = groups[0]?.id;
  $('#group-list').replaceChildren();
  for (const g of groups) {
    const button = node('button', `group-item ${g.id === selected ? 'selected' : ''}`);
    button.setAttribute('aria-pressed', g.id === selected);
    const text = node('span', 'group-text'); text.append(node('strong', '', g.files[0].name), node('small', '', `${g.id.replace('group-', 'Group ')} · ${g.files.length} files${g.status === 'reviewed' ? ' · Complete' : ''}`));
    button.append(text, node('span', `group-state ${g.status}`)); button.onclick = () => {selected = g.id; render();}; $('#group-list').append(button);
  }
  renderGroup(state.groups.find(g => g.id === selected));
}

/* Each copy has its own page controls and original-location disclosure. */
function renderGroup(group) {
  const version = ++renderVersion;
  $('#empty').hidden = !!group; $('#review-panel').hidden = !group;
  if (!group) {$('#empty').textContent = 'No matching groups.'; return;}
  $('#group-number').textContent = `GROUP ${group.id.replace('group-', '')} / ${group.files.length} COPIES`;
  $('#group-title').textContent = group.files[0].name;
  $('#group-status').textContent = {pending: 'Pending', reviewed: 'Complete', attention: 'Requires attention'}[group.status];
  $('#group-status').className = `badge ${group.status === 'reviewed' ? 'done' : ''}`;
  $('#evidence-text').textContent = `${group.files.length} files have the same verified hash. Review filenames and original locations.`;
  $('.evidence strong').textContent = group.errors.length ? 'Verification issue' : 'Identical file contents';
  if (group.errors.length) $('#evidence-text').textContent = 'Resolve file errors before selecting a retained file.';
  $('#hash').textContent = `SHA-256: ${group.hash}`;
  $('#group-errors').hidden = !group.errors.length; $('#group-errors').textContent = group.errors.join('\n');
  $('#undo').hidden = !group.can_undo; $('#undo').disabled = busy;
  $('#next').classList.toggle('ready', group.status === 'reviewed');
  $('#selection-note').textContent = group.status === 'reviewed' ? 'One file retained. Not sure? Undo selection to restore all copies.' : 'Select one file to retain, or leave this group pending if unsure.';
  $('#file-cards').replaceChildren();
  group.files.forEach((file, i) => {
    const kept = group.status === 'reviewed' && file.present;
    const card = node('article', `file-card ${kept ? 'kept' : ''} ${!file.present ? 'archived' : ''}`);
    const top = node('div', 'file-top'), label = node('div', 'file-label');
    label.append(node('span', '', `FILE ${String(i + 1).padStart(2, '0')}`), node('span', kept ? 'kept-label' : '', kept ? 'RETAINED' : file.present ? `${Math.round(file.size / 1024)} KB` : file.available ? 'IN RECOVERY' : 'UNAVAILABLE'));
    top.append(label, node('h3', '', file.name));
    const preview = node('div', 'preview'); preview.append(node('span', 'placeholder', 'Loading preview…'));
    const controls = node('div', 'page-controls'), previous = node('button', '', 'Previous'), count = node('span', '', ''), next = node('button', '', 'Next'), open = node('a', '', 'Open file');
    open.href = `/api/file?id=${file.id}`; open.target = '_blank'; open.rel = 'noopener';
    previous.setAttribute('aria-label', 'Previous page'); next.setAttribute('aria-label', 'Next page');
    controls.append(previous, count, next, open);
    const bottom = node('div', 'file-bottom'), source = node('div', 'source'), details = node('details');
    details.append(node('summary', '', 'Original location'), node('p', '', file.original)); source.append(details);
    const keep = node('button', 'keep-button', kept ? 'Retained' : file.present ? 'Retain this file' : 'Restore to select');
    keep.disabled = busy || !file.present || kept || !!group.errors.length;
    keep.onclick = () => action('/api/keep', {group: group.id, id: file.id}, 'File retained; other copies moved to recovery.');
    bottom.append(source, keep); card.append(top, preview, controls, bottom); $('#file-cards').append(card);
    if (!file.available) {preview.replaceChildren(node('span', 'placeholder', 'This file is unavailable.')); controls.hidden = true; return;}
    let page = 0;
    const load = async () => {
      try {
        if (!docs.has(file.id)) docs.set(file.id, await api(`/api/document?id=${file.id}`));
        if (version !== renderVersion) return;
        const doc = docs.get(file.id); preview.replaceChildren();
        const unit = doc.units?.[page];
        if (doc.kind === 'word' || doc.kind === 'spreadsheet') {
          renderOfficePreview(preview, await api(`/api/office-view?id=${file.id}&page=${page}`));
        } else {
          if (unit?.text) preview.append(node('pre', '', unit.text));
        }
        if (!['word', 'spreadsheet'].includes(doc.kind) && (doc.kind !== 'office' || unit?.has_image)) {
          const image = node('img'); image.alt = `${file.name}, page ${page + 1}`; image.src = `/api/preview?id=${file.id}&page=${page}`;
          image.onclick = () => window.open(image.src, '_blank', 'noopener');
          image.onerror = () => preview.replaceChildren(node('span', 'placeholder', 'Preview unavailable. Open the original file to inspect it.'));
          preview.append(image);
        }
        count.textContent = doc.labels?.[page] || `${doc.kind === 'office' ? 'Section' : 'Page'} ${page + 1} of ${doc.pages}`;
        previous.disabled = page === 0; next.disabled = page === doc.pages - 1;
      } catch (error) {preview.replaceChildren(node('span', 'placeholder', error.message)); previous.disabled = next.disabled = true;}
    };
    previous.onclick = () => {page--; load();}; next.onclick = () => {page++; load();}; load();
  });
}

/* File decisions run once at a time; validation never invokes Codex. */
async function action(path, body, message) {
  if (busy) return; busy = true; render();
  try {state = await api(path, body); $('#validation').hidden = true; toast(message);} catch (error) {toast(error.message);} finally {busy = false; render();}
}
$('#undo').onclick = () => action('/api/undo', {group: selected}, 'Selection undone; all files restored.');
$('#next').onclick = () => {const groups = visibleGroups(); selected = groups[(groups.findIndex(g => g.id === selected) + 1) % groups.length]?.id; render();};
$('#search').oninput = render;
root.querySelectorAll('[data-filter]').forEach(button => button.onclick = () => {filter = button.dataset.filter; root.querySelectorAll('[data-filter]').forEach(b => b.classList.toggle('selected', b === button)); render();});
$('#validate').onclick = async () => {
  if (busy) return; busy = true; render();
  try {const result = await api('/api/validate', {}); const panel = $('#validation'); panel.hidden = false; panel.className = `validation ${result.passed ? 'success' : ''}`; $('#validation-text').textContent = result.passed ? 'Exact duplicate review complete.' : `Outstanding issues:\n${result.problems.join('\n')}`; $('#next-content').hidden = !result.passed; state = await api('/api/state'); token = state.token; render();} catch (error) {toast(error.message);} finally {busy = false; render();}
};
function showPreset(data) {
  $('#exact-development-status').textContent = data.saved
    ? `Saved ${data.exact} exact and ${data.content} content decisions on ${new Date(data.at).toLocaleString()}.`
    : 'No saved decisions yet.';
  const cacheInfo = data.cache ? ` Shared cache: ${data.cache.model_results} model results.` : '';
  const status = root.querySelector('#exact-development-status, #development-status');
  if (status) status.textContent += cacheInfo;
  $('#exact-apply').disabled = !data.saved;
}
$('#exact-remember').onclick = async () => {
  try {showPreset(await api('/api/development/remember', {})); toast('Human decisions remembered.');}
  catch (error) {toast(error.message);}
};
$('#exact-apply').onclick = async () => {
  const button = $('#exact-apply'); button.disabled = true;
  $('#exact-development-status').textContent = 'Applying matching decisions…';
  try {
    const result = await api('/api/development/apply', {reviewer: $('#exact-development-reviewer').value});
    showPreset(result.saved);
    state = await api('/api/state'); token = state.token; render();
    $('#validation').hidden = true;
    toast(`Applied ${result.exact_applied} exact and ${result.content_applied} content decisions.`);
  } catch (error) {$('#exact-development-status').textContent = error.message; toast(error.message);}
  finally {button.disabled = false;}
};
api('/api/state').then(async data => {
  state = data; token = data.token; selected = data.groups.find(g => g.status === 'pending')?.id; render();
  try {showPreset(await api('/api/development-decisions'));}
  catch (error) {$('#exact-development-status').textContent = `Unable to load remembered decisions: ${error.message}. Restart the dashboard server and reload.`;}
}).catch(error => {
  $('#empty').textContent = `Unable to load review: ${error.message}`;
  $('#exact-development-status').textContent = 'Unable to load saved decisions. Reload the dashboard.';
});

}
