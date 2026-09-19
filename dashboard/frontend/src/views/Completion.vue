<script setup>
import PageHelp from '../components/PageHelp.vue';
import { ref } from 'vue';
import { usePage } from '../page.js';
import initialize from '../controllers/Completion.js';

const root = ref(null);
usePage(root, initialize);
</script>

<template>
  <div ref="root" class="page-view">
<main>
    <section class="page-heading"><div><div class="page-title"><h1 id="completion-title">Checking completion…</h1><PageHelp page="Completion" /></div><p id="completion-note">Reading saved review and bank results.</p></div></section>
    <section class="settings-card"><h2>Workflow checks</h2><p id="completion-steps"></p></section>
    <section class="settings-card" id="final-usage" hidden><h2>Total recorded Codex usage</h2><strong id="final-total"></strong><p id="final-details"></p><pre id="final-breakdown"></pre></section>
    <div id="completion-error" class="validation" role="alert" hidden></div>
  </main>
  </div>
</template>
