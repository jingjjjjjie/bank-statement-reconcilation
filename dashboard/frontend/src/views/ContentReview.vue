<script setup>
import { ref } from 'vue';
import { usePage } from '../page.js';
import initialize from '../controllers/ContentReview.js';
import WorkflowProgress from '../components/WorkflowProgress.vue';

const root = ref(null);
usePage(root, initialize);
</script>

<template>
  <div ref="root" class="page-view">
<main>
    <header><div class="breadcrumb">Workspace <span>/</span> Content review</div><a class="header-settings" href="/review">Exact review</a></header>
    <WorkflowProgress />
    <section class="page-heading"><div><div class="eyebrow">STEP 02 / CONTENT DUPLICATES</div><h1>Review possible copies</h1><p>First extract every document, then check for possible duplicates and record admin decisions.</p></div><a class="button secondary" href="/documents">View all document statuses</a></section>
    <div id="content-message" class="validation" role="status"></div>
    <section id="content-controls" class="settings-card" hidden>
      <h2>Review progress</h2><p id="content-progress"></p>
      <div class="content-actions"><button class="button dark" id="prepare-content" type="button" hidden>Prepare documents</button><button class="button dark" id="run-content" type="button" hidden>Run next review batch</button><button class="button secondary" id="check-content" type="button" hidden>Check content review</button><a class="button context-next" id="content-next" href="/bank" hidden>Continue to bank statement</a><span id="content-running" hidden>Model review is running. This page updates automatically.</span></div>
      <p id="content-check-note" role="status"></p>
      <p>Preparation reads the files locally. A review batch uses your logged-in Codex subscription and the call limit in Settings.</p>
    </section>
    <section id="candidate-section" hidden>
      <div class="content-toolbar"><div><h2>Candidate pairs <span id="candidate-count"></span></h2><p>Model findings are evidence. Only an admin can approve a duplicate.</p></div><label>Admin name<input id="admin-name" autocomplete="name" placeholder="Your name"></label></div>
      <div id="candidate-list"></div>
    </section>
  </main>
  <div id="content-loading" class="content-loading" role="status" aria-live="polite" hidden>
    <div class="content-loading-card"><span class="content-spinner" aria-hidden="true"></span><h2 id="content-loading-title">Starting content review</h2><p id="content-loading-progress">Checking saved progress…</p><button class="button secondary" id="stop-content" type="button">Stop review</button><small>This page updates as each result is saved.</small></div>
  </div>
  </div>
</template>
