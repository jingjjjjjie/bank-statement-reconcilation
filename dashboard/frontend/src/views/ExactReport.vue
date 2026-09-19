<script setup>
import PageHelp from '../components/PageHelp.vue';
import { ref } from 'vue';
import { usePage } from '../page.js';
import initialize from '../controllers/ExactReport.js';

const root = ref(null);
usePage(root, initialize);
</script>

<template>
  <div ref="root" class="page-view">
<main>
    <section class="page-heading"><div><div class="page-title"><h1>Exact duplicate report</h1><PageHelp page="ExactReport" /></div></div></section>
    <section class="stats"><div><span>Source files</span><strong id="source-files">...</strong></div><div><span>Duplicate groups</span><strong id="duplicate-groups">...</strong></div><div><span>Extra copies</span><strong id="extra-copies">...</strong></div><div><span>Unique documents</span><strong id="unique-documents">...</strong></div></section>
    <section class="settings-card"><h2>Grouped copies</h2><p id="report-summary" role="status">Loading report...</p><p><strong>Output folder: </strong><code id="output-folder"></code></p><div id="report-groups"></div></section>
  </main>
  </div>
</template>
