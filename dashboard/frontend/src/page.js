import { onMounted, onActivated, onDeactivated, onBeforeUnmount, watch } from 'vue';
import { useRoute, useRouter, onBeforeRouteUpdate } from 'vue-router';
import { api, appState, pages, toast } from './api.js';

// Adapt each existing evidence controller to one Vue-owned root and explicit lifecycle.
export function usePage(root, initialize) {
  const route = useRoute(), router = useRouter();
  const polls = [], observers = [], requests = new Set();
  let active = false, disposed = false, dirty = () => false, refresh, queryChanged, element;
  let previousChanges = appState.changes;
  const reviewId = appState.session.review_id;
  const page = {
    get root() { return element; },
    reviewId,
    $: selector => element.querySelector(selector),
    toast: message => { if (!disposed) toast(message); },
    navigate: path => router.push(path),
    routeQuery: () => new URLSearchParams(route.query).toString(),
    dirty: callback => { dirty = callback; },
    isDirty: () => !disposed && dirty(),
    onRefresh: callback => { refresh = callback; },
    onQuery: callback => { queryChanged = callback; },
    observe(observer, element, options) {
      observers.push(observer);
      observer.observe(element, options);
    },
    showDevelopmentMode(data) {
      appState.development = data.enabled;
      renderDevelopment();
    },
    async api(path, body) {
      const controller = new AbortController();
      requests.add(controller);
      try { return await api(path, body, { signal: controller.signal, reviewId }); }
      finally { requests.delete(controller); }
    },
    pollVisible(callback, milliseconds) {
      const poll = { callback, milliseconds, timer: null, running: false };
      polls.push(poll);
      if (active) schedule(poll);
    },
  };

  function renderDevelopment() {
    if (!root.value) return;
    root.value.querySelectorAll('[data-development-tools]').forEach(element => {
      element.hidden = !appState.development;
    });
    const toggle = page.$('#development-mode');
    if (toggle) { toggle.checked = appState.development; toggle.disabled = false; }
    const status = page.$('#development-mode-status');
    if (status) status.textContent = appState.development
      ? 'Development tools and shared cache are enabled.' : 'Normal mode. Development tools are disabled.';
  }

  function schedule(poll) {
    clearTimeout(poll.timer);
    if (!active || disposed || poll.running || document.hidden) return;
    poll.timer = setTimeout(async () => {
      poll.running = true;
      try { await poll.callback(); }
      catch (error) { page.toast(error.message); }
      finally { poll.running = false; schedule(poll); }
    }, poll.milliseconds);
  }

  function visibility() {
    polls.forEach(schedule);
  }

  onMounted(() => {
    element = root.value;
    pages.add(page);
    try { initialize(page); renderDevelopment(); }
    catch (error) { toast(error.message); console.error(error); }
  });
  onActivated(() => {
    active = true;
    document.addEventListener('visibilitychange', visibility);
    polls.forEach(schedule);
    if (previousChanges !== appState.changes && !dirty() && refresh) {
      Promise.resolve(refresh()).catch(error => page.toast(error.message));
    }
    previousChanges = appState.changes;
  });
  onDeactivated(() => {
    active = false;
    polls.forEach(poll => clearTimeout(poll.timer));
    document.removeEventListener('visibilitychange', visibility);
    root.value?.querySelectorAll('dialog[open]').forEach(dialog => dialog.close());
  });
  onBeforeUnmount(() => {
    disposed = true;
    active = false;
    polls.forEach(poll => clearTimeout(poll.timer));
    requests.forEach(controller => controller.abort());
    observers.forEach(observer => observer.disconnect());
    document.removeEventListener('visibilitychange', visibility);
    pages.delete(page);
  });
  onBeforeRouteUpdate((to, from) => {
    if (to.fullPath !== from.fullPath && dirty()) return confirm('Discard unsaved changes for this document?');
  });
  watch(() => route.query, () => { if (active && queryChanged) queryChanged(); });
  watch(() => appState.development, renderDevelopment);
}
