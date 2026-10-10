import { node } from '../dom.js';
import { renderOfficePreview } from '../office.js';

// Scope screen state and handlers to this cached Vue view.
export default function initialize(page) {
const { root, $, api, toast, pollVisible, navigate, routeQuery } = page;
let token;
/* Settings page: changes are explicit and never start document processing. */
let savedSettings, draftConfig, dirty = false;
const stages = [
  ['pdf', 'PDF reading', 'Uses the PDF processing option above: extracted text, vision fallback, or full vision.'],
  ['images', 'JPG / image reading', 'Vision only for now, including PNG and other supported images. No separate OCR step. Picture processing must be on.'],
  ['excel', 'Excel reading', 'Python extracts cells, formulas and cached values from XLSX files. This model reads that text and any allowed embedded pictures.'],
  ['word', 'Word reading (inactive)', 'DOCX files are currently listed as not accepted. This setting is retained for future use.']
];
function callExample() {
  const n = Number($('#max-calls').value);
  const parallel = Number($('#max-parallel').value);
  $('#call-example').textContent = Number.isInteger(n) && n >= 1 && n <= 1000
    ? `Up to ${n} new request${n === 1 ? '' : 's'} in this run, with up to ${Math.min(n, parallel || 1)} at once. If more work remains, pause before request ${n + 1}. Run again to continue with up to ${n} more.`
    : 'Enter a whole number from 1 to 1000.';
}
function updateReasoning(stage, selected = 'default') {
  const model = savedSettings.models.find(m => m.id === $(`#${stage}-model`).value);
  const levels = model?.reasoning || [];
  const input = $(`#${stage}-reasoning`);
  input.replaceChildren(new Option('Model default', 'default'), ...levels.map(r => new Option(r[0].toUpperCase() + r.slice(1), r)));
  if (selected !== 'default' && !levels.includes(selected)) input.add(new Option(`${selected} (no longer listed)`, selected));
  input.value = selected;
  input.disabled = !model;
}
function refreshModels(models) {
  // Rebuild model lists from a refreshed catalog, keeping each current (even unsaved) choice.
  savedSettings.models = models;
  for (const [stage] of stages) {
    const select = $(`#${stage}-model`), model = select.value, reasoning = $(`#${stage}-reasoning`).value;
    const options = models.map(m => new Option(m.name, m.id));
    if (model && !models.some(m => m.id === model)) options.push(new Option(`${model} (no longer listed)`, model));
    select.replaceChildren(new Option('Codex default', ''), ...options);
    select.value = model;
    updateReasoning(stage, reasoning);
  }
}
function renderStages(data) {
  $('#stage-settings').replaceChildren();
  for (const [stage, title, description] of stages) {
    const section = document.createElement('section');
    section.className = 'stage-setting';
    // Only fixed stage identifiers enter markup; catalog labels use Option text.
    section.innerHTML = `<h3>${title}</h3><div class="settings-grid"><label class="setting-field"><strong>Model</strong><select id="${stage}-model" aria-label="${title} model"></select></label><label class="setting-field"><strong>Reasoning effort</strong><select id="${stage}-reasoning" aria-label="${title} reasoning"></select></label></div>`;
    $('#stage-settings').append(section);
    const choice = data.config.stages?.[stage] || data.config;
    const select = $(`#${stage}-model`);
    select.replaceChildren(new Option('Codex default', ''), ...data.models.map(m => new Option(m.name, m.id)));
    if (choice.model && !data.models.some(m => m.id === choice.model)) select.add(new Option(`${choice.model} (no longer listed)`, choice.model));
    select.value = choice.model;
    updateReasoning(stage, choice.reasoning);
    select.onchange = () => {updateReasoning(stage); markDirty();};
  }
}
function showSettings(data, draft = false) {
  if (!draft) savedSettings = data;
  draftConfig = data.config;
  $('#pdf-mode').value = data.config.pdf_mode;
  $('#pdf-whole-document-max-pages').value = data.config.pdf_whole_document_max_pages;
  $('#pictures-enabled').checked = data.config.pictures_enabled;
  $('#codex-enabled').checked = data.config.codex_enabled;
  $('#max-calls').value = data.config.max_calls;
  $('#max-parallel').value = data.config.max_parallel;
  renderStages(data);
  showUsage(data.token_usage);
  $('#settings-refresh').hidden = !data.requires_refresh;
  $('#settings-fields').disabled = false;
  $('#settings-error').hidden = true;
  dirty = false;
  $('#save-state').textContent = 'All settings saved';
  $('#save-settings').disabled = $('#discard-settings').disabled = true;
  $('#reset-settings').disabled = false;
  callExample();
  if (draft) markDirty();
}
function markDirty() {
  dirty = true;
  $('#save-state').textContent = 'Unsaved changes';
  $('#save-settings').disabled = $('#discard-settings').disabled = false;
  callExample();
}
$('#settings-form').oninput = markDirty;
$('#discard-settings').onclick = () => showSettings(savedSettings);
$('#reset-settings').onclick = () => {
  // Stage canonical defaults; Save commits them and Discard restores the saved revision.
  showSettings({...savedSettings, config: structuredClone(savedSettings.defaults)}, true);
  $('#save-state').textContent = 'Defaults restored — save to apply';
};

/* Preserve backend validation and stale-tab protection when saving. */
$('#settings-form').onsubmit = async event => {
  event.preventDefault();
  if (!savedSettings || !token) return;
  $('#settings-fields').disabled = true;
  $('#save-settings').disabled = $('#discard-settings').disabled = true;
  $('#reset-settings').disabled = true;
  try {
    const choices = {...draftConfig.stages};
    for (const [stage] of stages) {
      const choice = {model: $(`#${stage}-model`).value, reasoning: $(`#${stage}-reasoning`).value};
      if (stage in choices || choice.model !== draftConfig.model || choice.reasoning !== draftConfig.reasoning) choices[stage] = choice;
    }
    const config = {...draftConfig, pdf_mode: $('#pdf-mode').value, pdf_whole_document_max_pages: Number($('#pdf-whole-document-max-pages').value), pictures_enabled: $('#pictures-enabled').checked, codex_enabled: $('#codex-enabled').checked, max_calls: Number($('#max-calls').value), max_parallel: Number($('#max-parallel').value), stages: choices};
    showSettings(await api('/api/config', {config, revision: savedSettings.revision}));
    toast('Settings saved. No review was started.');
  } catch (error) {
    $('#settings-error').hidden = false; $('#settings-error').textContent = error.message;
    $('#settings-fields').disabled = false; markDirty();
    $('#reset-settings').disabled = false;
  }
};
Promise.all([api('/api/session'), api('/api/config')]).then(([session, config]) => {token = session.token; showSettings(config);}).catch(error => {$('#settings-error').hidden = false; $('#settings-error').textContent = error.message; $('#save-state').textContent = 'Unable to load settings'; $('#call-example').textContent = 'Saved limit unavailable'; $('#token-usage').textContent = 'Usage unavailable';});
page.dirty(() => dirty);


page.onRefresh(async () => showSettings(await api('/api/config')), ['/api/config']);

function showUsage(usage) {
  // Update accounting without resetting unsaved form fields.
  if (usage?.totals) {
    const totals = usage.totals;
    $('#token-usage').textContent = `${usage.complete === false ? "Partial workspace total" : "Workspace total"} ${(totals.input_tokens + totals.output_tokens).toLocaleString()} · Input ${totals.input_tokens.toLocaleString()} (cached ${totals.cached_input_tokens.toLocaleString()}) · Output ${totals.output_tokens.toLocaleString()} (reasoning ${totals.reasoning_output_tokens.toLocaleString()}) · ${usage.attempts} attempts · ${usage.unknown_attempts} unknown · ${usage.cache_hits} cache hits`;
    const lines = ['By stage:', ...Object.entries(usage.by_stage || {}).map(([name, value]) => `  ${name}: ${(value.input_tokens + value.output_tokens).toLocaleString()}`), 'By model:', ...Object.entries(usage.by_model || {}).map(([name, value]) => `  ${name}: ${(value.input_tokens + value.output_tokens).toLocaleString()}`)];
    $('#token-breakdown').textContent = usage.attempts ? lines.join('\n') : 'No tracked Codex calls yet.';
  } else {
    $('#token-usage').textContent = 'Token tracking is unavailable until the dashboard server is restarted.';
    $('#token-breakdown').textContent = '';
  }
}
pollVisible(async () => showUsage((await api('/api/config')).token_usage), 10000);

/* Codex account: one status line with a dot (green working, blue busy, red problem). Works without a workspace. */
let codex, check = null, checking = false, codexTimer, checkedAt = null;
function codexState() {
  if (!codex) return ['busy', 'Checking Codex…'];
  if (codex.update.running) return ['busy', `Installing Codex ${codex.latest}…`];
  if (codex.login.running) return ['busy', 'Waiting for you to sign in…'];
  if (checking) return ['busy', 'Sending a test request…'];
  if (!codex.available) return ['problem', 'Codex is not installed'];
  if (codex.method === 'api key') return ['problem', 'Logged in with an API key; this workflow needs ChatGPT'];
  if (!codex.logged_in) return ['problem', 'Not logged in'];
  if (check && !check.ok) return ['problem', `Connection failed: ${check.error || 'unexpected reply'}`];
  return ['ok', check ? 'Connected with ChatGPT' : 'Logged in with ChatGPT'];
}
function showCodex() {
  const [tone, text] = codexState();
  $('#codex-dot').className = `status-dot ${tone}`;
  $('#codex-status').textContent = text;
  $('#codex-version').textContent = !codex?.installed ? '' : codex.update_available ? `${codex.installed} · ${codex.latest} available` : `${codex.installed} (latest)`;
  const time = at => at.toLocaleTimeString([], {hour: 'numeric', minute: '2-digit'});
  $('#codex-detail').textContent = [checkedAt && `Last check ${time(checkedAt)}`, check?.ok && `test request answered in ${check.seconds} s`].filter(Boolean).join(' · ');
  const login = codex?.login || {running: false, lines: [], exit_code: null};
  const update = codex?.update || {running: false, lines: [], exit_code: null};
  $('#codex-login').hidden = !login.running;
  $('#codex-login-url').textContent = $('#codex-login-url').href = login.url || '';
  $('#codex-login-code').textContent = login.code || '';
  // Raw output appears only when a login or update fails.
  const failed = [login, update].find(job => !job.running && job.exit_code !== null && job.exit_code !== 0);
  $('#codex-output').hidden = !failed;
  $('#codex-output').textContent = failed ? failed.lines.join('\n') : '';
  $('#codex-update').textContent = codex?.update_available && codex.can_update ? `Update to ${codex.latest}` : 'Check for updates';
  $('#codex-update').disabled = update.running || login.running;
  $('#codex-login-start').textContent = codex?.logged_in ? 'Log in again' : 'Log in with ChatGPT';
  $('#codex-login-start').hidden = login.running;
  $('#codex-login-cancel').hidden = !login.running;
  $('#codex-check').disabled = checking || login.running || update.running;
  clearTimeout(codexTimer);
  if (login.running || update.running) codexTimer = setTimeout(() => loadCodex(), 2000);
}
async function loadCodex(refresh = false) {
  const wasRunning = codex?.update.running || codex?.login.running;
  try {
    codex = await api(`/api/codex/status${refresh ? '?refresh=true' : ''}`); checkedAt = new Date();
    if (wasRunning && !codex.update.running && !codex.login.running) {
      codex = await api('/api/codex/status?refresh=true');
      if (savedSettings) {
        const fresh = await api('/api/config');
        refreshModels(fresh.models);
      }
    }
  }
  catch (error) { codex = null; $('#codex-status').textContent = error.message; return; }
  showCodex();
}
$('#codex-check').onclick = async () => {
  checking = true; showCodex();
  try { await loadCodex(); check = await api('/api/codex/check', {}); }
  catch (error) { check = {ok: false, error: error.message}; }
  finally { checking = false; showCodex(); }
};
$('#codex-update').onclick = async () => {
  if (!(codex?.update_available && codex.can_update)) {
    $('#codex-update').disabled = true;
    await loadCodex(true);
    let models = '';
    if (savedSettings) {
      const fresh = await api('/api/config').catch(() => null);
      if (fresh) { refreshModels(fresh.models); models = ` Model list refreshed (${fresh.models.length} models).`; }
    }
    if (codex && !codex.update_available) toast((codex.latest ? `Codex ${codex.installed} is the latest version.` : `Could not check for updates: ${codex.latest_error}.`) + models);
    showCodex();
    return;
  }
  if (!confirm(`Install Codex ${codex.latest}? New requests will use it; running requests are not interrupted.`)) return;
  try { await api('/api/codex/update', {}); await loadCodex(); } catch (error) { toast(error.message); }
};
$('#codex-login-start').onclick = async () => {
  if (codex?.logged_in && !confirm('Replace the current Codex login?')) return;
  try { await api('/api/codex/login', {}); check = null; await loadCodex(); } catch (error) { toast(error.message); }
};
$('#codex-login-cancel').onclick = async () => {
  try { await api('/api/codex/login/cancel', {}); await loadCodex(); } catch (error) { toast(error.message); }
};
loadCodex();
pollVisible(() => loadCodex(), 60000);
}
