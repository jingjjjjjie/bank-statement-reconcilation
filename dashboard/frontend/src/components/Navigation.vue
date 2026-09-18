<script setup>
import { computed } from 'vue';
import { appState } from '../api.js';
const links = [
  ['/source', 'Workspace selection'], ['/review', 'Exact duplicates'],
  ['/documents', 'Documents'], ['/extraction-review', 'Review results'],
  ['/bank', 'Bank statement'], ['/matching', 'Final review'], ['/final-report', 'Final report'], ['/settings', 'Settings'], ['/complete', 'Completion'],
];
const visibleLinks = computed(() => links.filter(([path]) =>
  path !== '/review' || appState.session?.mode !== 'exact_report'));
</script>

<template>
  <aside class="rail">
    <RouterLink class="brand" to="/">Bank Statement Reconciliation</RouterLink>
    <div class="workspace"><span class="eyebrow">RECONCILIATION</span><strong>{{ appState.workspace.name }}</strong><span>{{ appState.workspace.period }}</span></div>
    <div class="rail-label">WORKFLOW</div>
    <RouterLink v-for="[path, label] in visibleLinks" :key="path" :to="path" class="nav-item" active-class="active">{{ label }}</RouterLink>
    <div class="rail-bottom">Local review workspace</div>
  </aside>
</template>
