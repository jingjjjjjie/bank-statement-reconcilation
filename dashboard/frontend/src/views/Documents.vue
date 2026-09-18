<script setup>
import { ref } from 'vue';
import { usePage } from '../page.js';
import initialize from '../controllers/Documents.js';
import WorkflowProgress from '../components/WorkflowProgress.vue';

const root = ref(null);
usePage(root, initialize);
</script>

<template>
  <div ref="root" class="page-view">
<main>
    <header><div class="breadcrumb">Workspace <span>/</span> Document status</div><a class="header-settings" href="/matching">Final matching &rarr;</a></header>
    <WorkflowProgress />
    <section class="page-heading"><div><div class="eyebrow">STEP 02 / DOCUMENT STATUS</div><h1>Documents</h1><p>Extract your documents, then open a file to review its receipts.</p></div></section>
    <section class="settings-card"><div class="content-actions"><button id="run-documents" class="button dark" type="button">Run all documents</button><button id="stop-documents" class="button secondary" type="button" disabled>Stop</button></div><div class="document-progress"><div><strong id="document-progress-stage">Not started</strong><span id="document-progress-count"></span></div><progress id="document-progress-bar" max="100" value="0" aria-labelledby="document-progress-stage" aria-describedby="document-progress-count"></progress><div id="document-progress-track" class="progress-track" aria-hidden="true"><span class="progress-fill"></span><span class="progress-activity"></span></div></div><p id="document-run-status" role="status">Your progress is saved automatically.</p></section>
    <section class="stats document-stats"><div><span>Documents</span><strong id="document-total">—</strong></div><div><span>Needs review</span><strong id="document-admin">—</strong></div><div><span>Complete</span><strong id="document-complete">—</strong></div></section>
    <section class="settings-card">
      <div class="document-toolbar"><div><h2>All documents</h2><p id="document-summary" role="status">Loading saved progress…</p></div><div class="document-filters"><label>Search documents<input id="document-search" type="search" placeholder="Filename or path"></label><label>Status<select id="document-filter"><option value="all">All statuses</option><option value="Queued">Queued</option><option value="Processing">Processing</option><option value="Needs review">Needs review</option><option value="Complete">Complete</option><option value="Needs attention">Needs attention</option></select></label></div></div>
      <label><input id="hide-duplicates" type="checkbox"> Hide approved duplicates</label>

      <div class="document-table-wrap"><table class="document-table"><thead><tr><th>Document</th><th>Status</th><th>Actions</th></tr></thead><tbody id="document-rows"></tbody></table></div>
      <p id="document-empty" class="document-empty" hidden></p>
    </section>
    <p id="receipt-error" class="validation" role="alert" hidden></p>
  </main>
  </div>
</template>
