<script setup>
import { ref } from 'vue';
import { usePage } from '../page.js';
import initialize from '../controllers/ExactReview.js';
import WorkflowProgress from '../components/WorkflowProgress.vue';

const root = ref(null);
usePage(root, initialize);
</script>

<template>
  <div ref="root" class="page-view">
<main>
    <header><div class="breadcrumb">Workspace <span>/</span> Document review</div><a class="header-settings" href="/settings">Settings</a></header>
    <WorkflowProgress />
    <section class="page-heading"><div><div class="eyebrow">STEP 01 / EXACT DUPLICATES</div><h1>Exact duplicate review</h1><p>Verify each group and select one file to retain.</p></div><button class="button dark" id="validate">Validate exact review</button></section>
    <section class="stats"><div><span>Duplicate groups</span><strong id="total">—</strong><small>Identical file hashes</small></div><div><span>Pending groups</span><strong id="pending">—</strong><small id="attention">One selection per group</small></div><div><span>Completed groups</span><strong id="reviewed">—<em>/ —</em></strong><div class="progress"><i id="progress"></i></div></div><div class="recovery-note"><div><strong>Reversible decisions</strong><p>Unselected files are stored in recovery.</p></div></div></section>
    <div id="validation" class="validation" hidden><p id="validation-text"></p><a id="next-content" class="button context-next" href="/content-review" hidden>Continue to content review</a></div>
    <section class="settings-card exact-development" data-development-tools hidden><h2>Development cache</h2><p>Model outputs and human choices are cached across test reviews. Remember current decisions to pin a preset. Apply replays matching human choices only when you press it.</p><p id="exact-development-status" role="status">Loading remembered decisions…</p><div class="content-actions"><label class="setting-field"><strong>Your name for replayed content decisions</strong><input id="exact-development-reviewer" autocomplete="name" placeholder="Admin name"></label><button class="button secondary" id="exact-remember" type="button">Remember current decisions</button><button class="button secondary" id="exact-apply" type="button" disabled>Apply remembered decisions</button></div></section>
    <section class="review-layout">
      <aside class="groups"><div class="groups-top"><h2>Duplicate groups</h2><span id="queue-count">—</span></div><label class="search"><input id="search" type="search" placeholder="Search files or groups" aria-label="Search groups"></label><div class="filters"><button data-filter="all" class="selected">All</button><button data-filter="pending">Pending</button><button data-filter="reviewed">Completed</button></div><div id="group-list" class="group-list" aria-label="Duplicate groups"></div></aside>
      <section class="comparison"><div id="empty" class="empty">Loading duplicate groups…</div><div id="review-panel" hidden><div class="comparison-heading"><div><div class="eyebrow" id="group-number"></div><h2 id="group-title"></h2></div><div class="group-heading-actions"><span id="group-status" class="badge"></span><button class="button secondary" id="undo" hidden>Undo selection</button></div></div><div class="evidence"><div><strong>Identical file contents</strong><span id="evidence-text"></span></div><details><summary>SHA-256 verification</summary><code id="hash"></code></details></div><div id="group-errors" class="validation" hidden></div><div id="file-cards" class="file-cards"></div><footer class="review-footer"><span id="selection-note">Select one file to retain.</span><div><button class="button secondary" id="next">Next group</button></div></footer></div></section>
    </section>
    <footer class="page-footer"><span>BANK STATEMENT RECONCILIATION / DOCUMENT REVIEW</span><span id="folder"></span></footer>
  </main>
  </div>
</template>
