<script setup>
import { computed } from 'vue';
import { appState } from '../api.js';
const links = [
  ['/source', 'Workspace'], ['/review', 'Exact duplicates'], ['/documents', 'Documents'],
  ['/extraction-review', 'Review results'], ['/bank', 'Bank statement'],
  ['/matching', 'Final review'], ['/final-report', 'Final report'],
  ['/complete', 'Completion'],
];
// Pair each header destination with its existing workflow status.
const items = computed(() => links.filter(([path]) =>
  path !== '/review' || appState.session?.mode !== 'exact_report').map(([path, label]) => {
    const index = appState.steps.findIndex(step => (step.href === '/' ? '/source' : step.href) === path);
    return { path, label, step: index >= 0 ? appState.steps[index] : null, number: index + 1 };
  }));
</script>

<template>
  <nav class="app-header" aria-label="Main navigation">
    <span class="app-brand">Bank Statement Reconciliation</span>
    <div class="header-links">
      <RouterLink v-for="item in items" :key="item.path" :to="item.path" class="header-link" active-class="active">
        <span v-if="item.step" class="header-step" :class="{ complete: item.step.checked }"
          :aria-label="item.step.checked ? 'Complete' : `Step ${item.number}`">
          <svg v-if="item.step.checked" viewBox="0 0 16 16" aria-hidden="true"><path d="m4 8 2.5 2.5L12 5" /></svg>
          <template v-else>{{ item.number }}</template>
        </span>
        <span>{{ item.label }}</span>
      </RouterLink>
    </div>
    <RouterLink to="/settings" class="header-settings-icon" active-class="active" aria-label="Settings" title="Settings">
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9.5 3-.6 2.2-1.7 1L5 5.6 2.5 10l1.6 1.6v1.8L2.5 15 5 19.4l2.2-.6 1.7 1 .6 2.2h5l.6-2.2 1.7-1 2.2.6 2.5-4.4-1.6-1.6v-1.8L21.5 10 19 5.6l-2.2.6-1.7-1L14.5 3Z"/><circle cx="12" cy="12.5" r="3"/></svg>
    </RouterLink>
  </nav>
</template>

<style scoped>
.app-header { display: flex; align-items: center; gap: 24px; height: 68px; padding: 0 24px; background: #18392f; color: #fff; }
.app-brand { flex-shrink: 0; font-size: 15px; font-weight: 650; }
.header-links { display: flex; align-self: stretch; margin-left: auto; min-width: 0; overflow-x: auto; scrollbar-width: thin; scrollbar-color: #6a8878 transparent; }
.header-settings-icon { display: inline-flex; align-items: center; justify-content: center; flex: 0 0 36px; width: 36px; height: 36px; border-radius: 9px; color: #cad8cf; }
.header-settings-icon:hover, .header-settings-icon:focus-visible, .header-settings-icon.active { color: #fff; background: #29493b; }
.header-settings-icon:focus-visible { outline: 2px solid #b6d49b; outline-offset: 3px; }
.header-settings-icon svg { width: 20px; height: 20px; fill: none; stroke: currentColor; stroke-width: 1.6; stroke-linecap: round; stroke-linejoin: round; }
.header-link { display: inline-flex; flex-shrink: 0; align-items: center; gap: 7px; padding: 0 12px; border-bottom: 2px solid transparent; color: #cad8cf; text-decoration: none; font-size: 12px; white-space: nowrap; }
.header-link:hover, .header-link:focus-visible { background: #29493b; color: #fff; }
.header-link.active { color: #fff; border-bottom-color: #b6d49b; }
.header-step { display: inline-flex; align-items: center; justify-content: center; width: 20px; height: 20px; border: 1px solid #6c8879; border-radius: 50%; color: #d5e0d8; font-size: 10px; font-weight: 600; }
.header-step.complete { border-color: #a9ca9d; background: #a9ca9d; color: #18392f; }
.header-step svg { width: 14px; height: 14px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
@media (max-width: 1100px) { .app-brand { display: none; } .app-header { gap: 8px; padding: 0 12px; } }
</style>
