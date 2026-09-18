import { node } from '../dom.js';
import { renderOfficePreview } from '../office.js';

// Scope screen state and handlers to this cached Vue view.
export default function initialize(page) {
const { root, $, api, toast, pollVisible, showDevelopmentMode, navigate, routeQuery } = page;
let token;
/* Settings page: changes are explicit and never start document processing. */
let savedSettings, dirty = false;
$('#development-mode').onchange = async event => {
  const enabled = event.target.checked;
  event.target.disabled = true;
  try {
    if (!token) token = (await api('/api/session')).token;
    showDevelopmentMode(await api('/api/development-mode', {enabled}));
    showDevelopment(await api('/api/development-decisions'));
  } catch (error) {
    showDevelopmentMode({enabled: !enabled});
    toast(error.message);
  }
};
const stages = [
  ['pdf', 'PDF reading', 'Uses the PDF processing option above: extracted text, vision fallback, or full vision.'],
  ['images', 'JPG / image reading', 'Vision only for now, including PNG and other supported images. No separate OCR step. Picture processing must be on.'],
  ['excel', 'Excel reading', 'Python extracts cells, formulas and cached values from XLSX files. This model reads that text and any allowed embedded pictures.'],
  ['word', 'Word reading (inactive)', 'DOCX files are currently listed as not accepted. This setting is retained for future use.'],
  ['comparison', 'Document comparison', 'Screens summaries and compares candidate originals across all file types, including PDF against JPG. May use vision when originals contain pictures.']
];
function callExample() {
  const n = Number($('#max-calls').value);
  const parallel = Number($('#max-parallel').value);
  $('#call-example').textContent = Number.isInteger(n) && n >= 1 && n <= 500
    ? `Up to ${n} new request${n === 1 ? '' : 's'} in this run, with up to ${Math.min(n, parallel || 1)} at once. If more work remains, pause before request ${n + 1}. Run again to continue with up to ${n} more.`
    : 'Enter a whole number from 1 to 500.';
}
function updateReasoning(stage, selected = 'default') {
  const model = savedSettings.models.find(m => m.id === $(`#${stage}-model`).value);
  const levels = model?.reasoning || [];
  const input = $(`#${stage}-reasoning`);
  input.replaceChildren(new Option('Model default', 'default'), ...levels.map(r => new Option(r[0].toUpperCase() + r.slice(1), r)));
  input.value = levels.includes(selected) ? selected : 'default';
  input.disabled = !model;
}
function renderStages(data) {
  $('#stage-settings').replaceChildren();
  for (const [stage, title, description] of stages) {
    const section = document.createElement('section');
    section.className = 'stage-setting';
    // Only fixed stage identifiers enter markup; catalog labels use Option text.
    section.innerHTML = `<h3>${title}</h3><p>${description}</p><div class="settings-grid"><label class="setting-field"><strong>Model</strong><select id="${stage}-model" aria-label="${title} model"></select></label><label class="setting-field"><strong>Reasoning effort</strong><select id="${stage}-reasoning" aria-label="${title} reasoning"></select></label></div>`;
    $('#stage-settings').append(section);
    const choice = data.config.stages?.[stage] || data.config;
    const select = $(`#${stage}-model`);
    select.replaceChildren(new Option('Codex default', ''), ...data.models.map(m => new Option(m.name, m.id)));
    select.value = choice.model;
    updateReasoning(stage, choice.reasoning);
    select.onchange = () => {updateReasoning(stage); markDirty();};
  }
}
function showSettings(data) {
  savedSettings = data;
  $('#pdf-mode').value = data.config.pdf_mode;
  $('#pictures-enabled').checked = data.config.pictures_enabled;
  $('#codex-enabled').checked = data.config.codex_enabled;
  $('#max-calls').value = data.config.max_calls;
  $('#max-parallel').value = data.config.max_parallel;
  renderStages(data);
  const usage = data.token_usage;
  if (usage?.totals) {
    const totals = usage.totals;
    $('#token-usage').textContent = `Total ${(totals.input_tokens + totals.output_tokens).toLocaleString()} · Input ${totals.input_tokens.toLocaleString()} (cached ${totals.cached_input_tokens.toLocaleString()}) · Output ${totals.output_tokens.toLocaleString()} (reasoning ${totals.reasoning_output_tokens.toLocaleString()}) · ${usage.attempts} attempts · ${usage.unknown_attempts} unknown · ${usage.cache_hits} cache hits`;
    const lines = ['By stage:', ...Object.entries(usage.by_stage || {}).map(([name, value]) => `  ${name}: ${(value.input_tokens + value.output_tokens).toLocaleString()}`), 'By model:', ...Object.entries(usage.by_model || {}).map(([name, value]) => `  ${name}: ${(value.input_tokens + value.output_tokens).toLocaleString()}`)];
    $('#token-breakdown').textContent = usage.attempts ? lines.join('\n') : 'No tracked Codex calls yet.';
  } else {
    $('#token-usage').textContent = 'Token tracking is unavailable until the dashboard server is restarted.';
    $('#token-breakdown').textContent = '';
  }
  $('#settings-refresh').hidden = !data.requires_refresh;
  $('#settings-fields').disabled = false;
  $('#use-defaults').disabled = false;
  $('#settings-error').hidden = true;
  dirty = false;
  $('#save-state').textContent = 'All settings saved';
  $('#save-settings').disabled = $('#discard-settings').disabled = true;
  callExample();
}
function markDirty() {
  dirty = true;
  $('#save-state').textContent = 'Unsaved changes';
  $('#save-settings').disabled = $('#discard-settings').disabled = false;
  callExample();
}
$('#settings-form').oninput = markDirty;
$('#discard-settings').onclick = () => showSettings(savedSettings);
$('#use-defaults').onclick = () => {
  if (!savedSettings) return;
  const defaults = savedSettings.defaults;
  $('#pdf-mode').value = defaults.pdf_mode;
  $('#pictures-enabled').checked = defaults.pictures_enabled;
  $('#codex-enabled').checked = defaults.codex_enabled;
  $('#max-calls').value = defaults.max_calls;
  $('#max-parallel').value = defaults.max_parallel;
  renderStages({...savedSettings, config: defaults});
  markDirty();
};

/* Preserve backend validation and stale-tab protection when saving. */
$('#settings-form').onsubmit = async event => {
  event.preventDefault();
  if (!savedSettings || !token) return;
  $('#settings-fields').disabled = true;
  $('#save-settings').disabled = $('#discard-settings').disabled = true;
  try {
    const choices = Object.fromEntries(stages.map(([stage]) => [stage, {model: $(`#${stage}-model`).value, reasoning: $(`#${stage}-reasoning`).value}]));
    const config = {...savedSettings.config, pdf_mode: $('#pdf-mode').value, pictures_enabled: $('#pictures-enabled').checked, codex_enabled: $('#codex-enabled').checked, max_calls: Number($('#max-calls').value), max_parallel: Number($('#max-parallel').value), stages: choices};
    showSettings(await api('/api/config', {config, revision: savedSettings.revision}));
    toast('Settings saved. No review was started.');
  } catch (error) {
    $('#settings-error').hidden = false; $('#settings-error').textContent = error.message;
    $('#settings-fields').disabled = false; markDirty();
  }
};
Promise.all([api('/api/session'), api('/api/config')]).then(([session, config]) => {token = session.token; showSettings(config);}).catch(error => {$('#settings-error').hidden = false; $('#settings-error').textContent = error.message; $('#save-state').textContent = 'Unable to load settings';});
function showDevelopment(data) {
  $('#development-status').textContent = data.saved
    ? `Saved ${data.exact} exact and ${data.content} content decisions on ${new Date(data.at).toLocaleString()}.`
    : 'No saved decisions yet.';
  const cacheInfo = data.cache ? ` Shared cache: ${data.cache.model_results} model results.` : '';
  const status = root.querySelector('#exact-development-status, #development-status');
  if (status) status.textContent += cacheInfo;
  $('#apply-decisions').disabled = !data.saved;
}
$('#remember-decisions').onclick = async () => {
  try {showDevelopment(await api('/api/development/remember', {})); toast('Human decisions remembered.');}
  catch (error) {toast(error.message);}
};
$('#apply-decisions').onclick = async () => {
  const button = $('#apply-decisions'); button.disabled = true;
  $('#development-status').textContent = 'Applying matching decisions…';
  try {
    const result = await api('/api/development/apply', {reviewer: $('#development-reviewer').value});
    showDevelopment(result.saved);
    toast(`Applied ${result.exact_applied} exact and ${result.content_applied} content decisions.`);
  } catch (error) {$('#development-status').textContent = error.message; toast(error.message);}
  finally {button.disabled = false;}
};
api('/api/development-decisions').then(showDevelopment).catch(error => {
  $('#development-status').textContent = `Unable to load remembered decisions: ${error.message}. Restart the dashboard server and reload.`;
});

page.dirty(() => dirty);


page.onRefresh(async () => showSettings(await api('/api/config')));
}
