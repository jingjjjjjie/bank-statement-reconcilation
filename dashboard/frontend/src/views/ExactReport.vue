<script setup>
import { ref } from 'vue';
import { usePage } from '../page.js';
import initialize from '../controllers/ExactReport.js';
import WorkflowProgress from '../components/WorkflowProgress.vue';

const root = ref(null);
usePage(root, initialize);
</script>

<template>
  <div ref="root" class="page-view">
<main>
    <header><div class="breadcrumb">Workspace <span>/</span> Duplicate report</div><a href="/content-review">Content review</a></header>
    <WorkflowProgress />
    <section class="page-heading"><div><div class="eyebrow">STEP 01 / AUTOMATIC EXACT DUPLICATES</div><h1>Exact duplicate report</h1><p>Verified by SHA-256 and full byte comparison. No manual selection is needed.</p></div><a class="button dark" href="/content-review">Continue to content review</a></section>
    <section class="stats"><div><span>Source files</span><strong id="source-files">...</strong></div><div><span>Duplicate groups</span><strong id="duplicate-groups">...</strong></div><div><span>Extra copies</span><strong id="extra-copies">...</strong></div><div><span>Unique documents</span><strong id="unique-documents">...</strong></div></section>
    <section class="settings-card"><h2>Grouped copies</h2><p>Every copy is included below. Originals stay in documents/; content review processes one document per hash.</p><p id="report-summary" role="status">Loading report...</p><p><strong>Output folder: </strong><code id="output-folder"></code></p><div id="report-groups"></div></section>
  </main>
  </div>
</template>
