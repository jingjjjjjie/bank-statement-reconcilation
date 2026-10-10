<script setup>
import PageHelp from '../components/PageHelp.vue';
import { ref } from 'vue';
import { usePage } from '../page.js';
import initialize from '../controllers/Documents.js';

const root = ref(null);
usePage(root, initialize);
</script>

<template>
  <div ref="root" class="page-view">
<main>
    <div class="document-workspace">
    <section class="page-heading"><div><div class="page-title"><h1>Documents</h1><PageHelp page="Documents" /></div></div><div class="content-actions"><button id="run-documents" class="button dark" type="button">Extract documents</button><button id="stop-documents" class="button secondary" type="button" disabled>Stop</button></div></section>
    <section class="settings-card"><div class="document-progress"><div><strong id="document-progress-stage">Not started</strong><span id="document-progress-count"></span></div><progress id="document-progress-bar" max="100" value="0" aria-labelledby="document-progress-stage" aria-describedby="document-progress-count"></progress><div id="document-progress-track" class="progress-track" aria-hidden="true"><span class="progress-fill"></span><span class="progress-activity"></span></div></div><p id="document-run-status" role="status">Your progress is saved automatically.</p><p id="receipt-error" class="validation" role="alert" hidden></p></section>
    <section class="stats document-stats"><div><span>Documents</span><strong id="document-total">—</strong></div><div><span>Needs review</span><strong id="document-admin">—</strong></div><div><span>Complete</span><strong id="document-complete">—</strong></div></section>
    <section class="settings-card">
      <div class="document-toolbar"><div><h2>All documents</h2><p id="document-summary" role="status">Loading saved progress…</p></div><div class="document-filters"><label>Search documents<input id="document-search" type="search" placeholder="Filename or folder"></label><label>Status<select id="document-filter"><option value="all">All documents</option><option value="review">To review</option><option value="complete">Complete</option><option value="attention">Needs attention</option><option value="excluded">Excluded</option></select></label></div></div>
      <span id="document-folder-icon" hidden><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M3 7V5a1 1 0 0 1 1-1h5l2 3h9a1 1 0 0 1 1 1v11H3V7Z"/></svg></span>
      <div class="document-table-wrap"><table class="document-table"><thead><tr><th>Document</th><th>Status</th><th>Actions</th></tr></thead><tbody id="document-rows"></tbody></table></div>
      <p id="document-empty" class="document-empty" hidden></p>
    </section>
    </div>
  </main>
  </div>
</template>
