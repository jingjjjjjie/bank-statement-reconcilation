<script setup>
import { appState } from '../api.js';
const links = [
  ['/source', 'Workspace selection'], ['/review', 'Exact duplicates'],
  ['/content-review', 'Content review'], ['/documents', 'Document status'],
  ['/bank', 'Bank statement'], ['/matching', 'Final review'], ['/settings', 'Settings'], ['/complete', 'Completion'],
];
</script>

<template>
  <aside class="rail">
    <RouterLink class="brand" to="/">Bank Statement Reconciliation</RouterLink>
    <div class="workspace"><span class="eyebrow">RECONCILIATION</span><strong>{{ appState.workspace.name }}</strong><span>{{ appState.workspace.period }}</span></div>
    <div class="rail-label">WORKFLOW</div>
    <RouterLink v-for="[path, label] in links" :key="path" :to="path" class="nav-item" active-class="active">{{ label }}</RouterLink>
    <div class="rail-bottom">Local review workspace</div>
  </aside>
</template>
