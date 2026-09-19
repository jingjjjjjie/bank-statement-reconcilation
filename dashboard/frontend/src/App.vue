<script setup>
import Navigation from './components/Navigation.vue';
import { onMounted, onBeforeUnmount } from 'vue';
import { router } from './router.js';
import { appState, pages, refreshNavigation, toast } from './api.js';

// Keep source-file downloads and new-tab links native; route only application links.
function navigate(event) {
  if (event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
  const link = event.target.closest('a[href]');
  if (!link || link.hasAttribute('download') || (link.target && link.target !== '_self')) return;
  const url = new URL(link.href);
  if (url.origin !== location.origin || !router.resolve(url.pathname).matched.length) return;
  event.preventDefault();
  router.push(url.pathname + url.search + url.hash).catch(error => toast(error.message));
}
function beforeUnload(event) {
  if ([...pages].some(page => page.isDirty())) { event.preventDefault(); event.returnValue = ''; }
}
onMounted(() => {
  window.addEventListener('beforeunload', beforeUnload);
  refreshNavigation().catch(error => toast(error.message));
});
onBeforeUnmount(() => window.removeEventListener('beforeunload', beforeUnload));
</script>

<template>
  <div class="application" @click="navigate">
    <Navigation />
    <RouterView v-slot="{ Component, route }">
      <KeepAlive :key="appState.session.review_id" :max="10">
        <component :is="Component" :key="route.path" />
      </KeepAlive>
    </RouterView>
    <div id="toast" role="status" aria-live="polite" :hidden="!appState.toast">{{ appState.toast }}</div>
  </div>
</template>
