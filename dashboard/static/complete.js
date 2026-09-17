/* Show cumulative tokens only after all three workflow gates pass. */
async function showCompletion() {
  try {
    const result = await api('/api/completion');
    const steps = [['Exact duplicate review', result.exact_done], ['Content review', result.content_done], ['Bank matching', result.bank_done]];
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
showCompletion();
