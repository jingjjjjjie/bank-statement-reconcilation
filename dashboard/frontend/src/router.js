import { createRouter, createWebHistory } from 'vue-router';
import { watch } from 'vue';
import { appState, loadSession } from './api.js';

// Code-split the larger evidence screens; each view is downloaded only when opened.
export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/source' },
    { path: '/source', component: () => import('./views/Source.vue'), meta: { title: 'Workspace selection', body: 'workspace-page', public: true } },
    { path: '/bank', component: () => import('./views/Bank.vue'), meta: { title: 'Bank statement', public: true } },
    { path: '/documents', component: () => import('./views/Documents.vue'), meta: { title: 'Document status', body: 'documents-page', public: true } },
    { path: '/review', component: () => import('./views/Review.vue'), meta: { title: 'Exact duplicates' } },
    { path: '/exact-report', redirect: '/review' },
    { path: '/content-review', redirect: '/documents' },
    { path: '/settings', component: () => import('./views/Settings.vue'), meta: { title: 'Settings' } },
    { path: '/complete', component: () => import('./views/Completion.vue'), meta: { title: 'Completion' } },
    { path: '/extraction-review', component: () => import('./views/ExtractionReview.vue'), meta: { title: 'Step 2 · Review results', body: 'extraction-workspace', fullscreen: true } },
    { path: '/final-report', component: () => import('./views/FinalReport.vue'), meta: { title: 'Final report', fullscreen: true } },
    { path: '/matching', component: () => import('./views/Matching.vue'), meta: { title: 'Final review', body: 'matching-app', fullscreen: true } },
  ],
  scrollBehavior(to, from, saved) { return saved || positions.get(to.fullPath) || { top: 0 }; },
});
const positions = new Map();
watch(() => appState.session?.review_id, () => { positions.clear(); appState.resumePath = '/documents'; }, { flush: 'sync' });
router.beforeEach(async (to, from) => {
  if (!appState.session) await loadSession();
  positions.set(from.fullPath, { left: window.scrollX, top: window.scrollY });
  if (!to.meta.public && !appState.session.active) return '/source';
});
router.afterEach((to, from, failure) => {
  if (!failure && to.path !== '/source' && appState.session?.active) appState.resumePath = to.fullPath;
  document.title = `${to.meta.title} · Bank Statement Reconciliation`;
  document.body.className = to.meta.body || '';
});
