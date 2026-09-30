import { node } from '../dom.js';
import { renderOfficePreview } from '../office.js';

// Scope screen state and handlers to this cached Vue view.
export default function initialize(page) {
const { root, $, api, toast, pollVisible, showDevelopmentMode, navigate, routeQuery } = page;
let token;
/* Show cumulative tokens only after all three workflow gates pass. */
async function showCompletion() {
  try {
    const result = await api('/api/completion');
    const steps = [['Exact duplicates', result.exact_done], ['Document extraction', result.content_done], ['Bank matching', result.bank_done]];
    $('#completion-steps').textContent = steps.map(([name, done]) => `${done ? 'Complete' : 'Pending'} · ${name}`).join('\n');
    $('#completion-steps').style.whiteSpace = 'pre-line';
    $('#completion-title').textContent = result.complete ? 'All workflows complete.' : 'Workflow in progress.';
    $('#completion-note').textContent = result.complete ? 'The final token total is below.' : 'The final token total appears when every workflow check is complete.';
    $('#final-usage').hidden = !result.complete;
    if (!result.complete) return;
    const usage = result.token_usage, totals = usage.totals;
    $('#final-total').textContent = (totals.input_tokens + totals.output_tokens).toLocaleString() + ' tokens';
    $('#final-details').textContent = `Input ${totals.input_tokens.toLocaleString()} (cached ${totals.cached_input_tokens.toLocaleString()}); output ${totals.output_tokens.toLocaleString()} (reasoning ${totals.reasoning_output_tokens.toLocaleString()}). ${usage.attempts} attempts; ${usage.unknown_attempts} with unknown usage; ${usage.cache_hits} cache hits.`;
    $('#final-breakdown').textContent = ['By stage:', ...Object.entries(usage.by_stage).map(([name, value]) => `  ${name}: ${(value.input_tokens + value.output_tokens).toLocaleString()}`), 'By model:', ...Object.entries(usage.by_model).map(([name, value]) => `  ${name}: ${(value.input_tokens + value.output_tokens).toLocaleString()}`)].join('\n');
  } catch (error) {
    $('#completion-error').hidden = false;
    $('#completion-error').textContent = error.message;
    $('#completion-title').textContent = 'Completion unavailable.';
  }
}
/* Download the prepared archive while keeping export failures on this page. */
async function exportUnmatched() {
  const button = $('#export-unmatched'), status = $('#unmatched-export-status');
  button.disabled = true; status.textContent = 'Preparing ZIP...';
  try {
    const response = await fetch('/api/unmatched-documents-export');
    if (!response.ok) {
      const result = await response.json();
      throw Error(result.error || 'Unable to export unmatched documents');
    }
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement('a');
    link.href = url; link.download = 'unmatched-documents.zip';
    document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    status.textContent = 'ZIP downloaded.';
  } catch (error) {
    status.textContent = error.message;
  } finally { button.disabled = false; }
}
$('#export-unmatched').onclick = exportUnmatched;
showCompletion();


page.onRefresh(showCompletion);
}
