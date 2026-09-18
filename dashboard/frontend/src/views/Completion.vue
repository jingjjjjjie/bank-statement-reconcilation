<script setup>
import { ref } from 'vue';
import { usePage } from '../page.js';
import initialize from '../controllers/Completion.js';
import WorkflowProgress from '../components/WorkflowProgress.vue';

const root = ref(null);
usePage(root, initialize);
</script>

<template>
  <div ref="root" class="page-view">
<main>
    <header><div class="breadcrumb">Workspace <span>/</span> Completion</div><a class="header-settings" href="/review">Back to review</a></header>
    <WorkflowProgress />
    <section class="page-heading"><div><div class="eyebrow">FINAL WORKFLOW STATUS</div><h1 id="completion-title">Checking completion…</h1><p id="completion-note">Reading saved review and bank results.</p></div></section>
    <section class="settings-card"><h2>Workflow checks</h2><p id="completion-steps"></p></section>
    <section class="settings-card" id="final-usage" hidden><h2>Total recorded Codex usage</h2><strong id="final-total"></strong><p id="final-details"></p><pre id="final-breakdown"></pre><p>These are cumulative reported tokens for this document-review workflow since tracking began. Cached input is included in input tokens. Unknown attempts may make the reported total incomplete.</p></section>
    <div id="completion-error" class="validation" role="alert" hidden></div>
  </main>
  </div>
</template>
