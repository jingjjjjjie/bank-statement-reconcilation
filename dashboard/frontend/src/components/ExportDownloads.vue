<script setup>
import { onActivated, ref } from 'vue';
import { api } from '../api.js';

const busy = ref(''), messages = ref({}), completion = ref(null), error = ref('');
const archives = [
  { id: 'matched', title: 'Matched documents', detail: 'Confirmed supporting originals.', endpoint: '/api/source-export?kind=matched', filename: 'matched-documents.zip' },
  { id: 'unmatched', title: 'Unmatched documents', detail: 'Duplicates and confirmed matches excluded.', endpoint: '/api/unmatched-documents-export', filename: 'unmatched-documents.zip' },
  { id: 'original', title: 'Original documents', detail: 'All supporting documents, as uploaded.', endpoint: '/api/source-export?kind=original', filename: 'original-documents.zip' },
  { id: 'project', title: 'Original project', detail: 'Statement and supporting input folders.', endpoint: '/api/source-export?kind=project', filename: 'original-project.zip' },
];
// Download existing server archives without changing sources or review decisions.
async function download(archive) {
  busy.value = archive.id; messages.value[archive.id] = 'Preparing ZIP…';
  try {
    const response = await fetch(archive.endpoint);
    if (!response.ok) { const result = await response.json(); throw Error(result.error || 'Unable to export documents'); }
    const url = URL.createObjectURL(await response.blob()), link = document.createElement('a');
    link.href = url; link.download = archive.filename; document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    messages.value[archive.id] = 'ZIP downloaded.';
  } catch (e) { messages.value[archive.id] = e.message; }
  finally { busy.value = ''; }
}
// Keep workflow and recorded usage available without blocking the report or downloads.
async function refresh() {
  error.value = '';
  try { completion.value = await api('/api/completion'); }
  catch (e) { error.value = e.message; }
}
onActivated(refresh);
</script>

<template>
  <aside class="export-downloads" aria-label="Downloads">
    <section class="workbook-download">
      <div class="download-section-heading"><h2>Bank statement</h2><span class="download-type">XLSX</span></div>
      <p>The final report in your bank statement format.</p>
      <slot />
    </section>
    <section class="archive-downloads">
      <div class="download-section-heading"><h2>Document folders</h2><span class="download-type">ZIP</span></div>
      <div v-for="archive in archives" :key="archive.id" class="archive-download">
        <div class="archive-description"><strong>{{ archive.title }}</strong><p>{{ archive.detail }}</p></div>
        <button :id="`export-${archive.id}`" class="button secondary" type="button" :disabled="!!busy" :aria-label="`Export ${archive.title.toLowerCase()}`" @click="download(archive)"><span class="download-word">{{ busy === archive.id ? 'Preparing…' : 'Download' }}</span></button>
        <p v-if="messages[archive.id]" :id="`${archive.id}-export-status`" role="status" class="download-message">{{ messages[archive.id] }}</p>
      </div>
    </section>
    <details class="export-run-details">
      <summary>Workflow &amp; usage</summary>
      <template v-if="completion">
        <dl class="export-checks"><template v-for="(done, name) in { 'Exact duplicates': completion.exact_done, 'Document workflow': completion.content_done, 'Bank workflow': completion.bank_done }" :key="name"><dt>{{ name }}</dt><dd>{{ done ? 'Complete' : 'Pending' }}</dd></template></dl>
        <template v-if="completion.complete && completion.token_usage">
          <strong>{{ (completion.token_usage.totals.input_tokens + completion.token_usage.totals.output_tokens).toLocaleString() }} recorded tokens</strong>
          <p>{{ completion.token_usage.attempts }} attempts · {{ completion.token_usage.unknown_attempts }} with unknown usage · {{ completion.token_usage.cache_hits }} cache hits.</p>
          <p>Input {{ completion.token_usage.totals.input_tokens.toLocaleString() }} (cached {{ completion.token_usage.totals.cached_input_tokens.toLocaleString() }}) · Output {{ completion.token_usage.totals.output_tokens.toLocaleString() }} (reasoning {{ completion.token_usage.totals.reasoning_output_tokens.toLocaleString() }})</p>
          <dl class="export-checks" v-for="(groups, label) in { 'By stage': completion.token_usage.by_stage, 'By model': completion.token_usage.by_model }" :key="label"><dt><strong>{{ label }}</strong></dt><dd></dd><template v-for="(total, name) in groups" :key="name"><dt>{{ name }}</dt><dd>{{ (total.input_tokens + total.output_tokens).toLocaleString() }}</dd></template></dl>
        </template>
        <p v-else>Usage totals appear when workflow checks are complete.</p>
      </template>
      <p v-if="error" role="alert">{{ error }}</p>
    </details>
  </aside>
</template>
