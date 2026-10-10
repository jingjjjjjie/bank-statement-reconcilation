import { createRouter, createWebHistory } from 'vue-router';
import { watch } from 'vue';
import { appState, loadSession, refreshNavigation, toast } from './api.js';

// Code-split the larger evidence screens; each view is downloaded only when opened.
export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/home' },
    { path: '/accounting-finance', redirect: '/home' },
    { path: '/home', component: () => import('./features/projects/Portal.vue'), meta: { title: 'Home', body: 'portal-page directory-page', public: true, portal: true } },
    { path: '/projects', component: () => import('./features/projects/Projects.vue'), meta: { title: 'Bank Statement Reconciliation', body: 'portal-page', public: true, portal: true } },
    { path: '/source', component: () => import('./features/projects/Source.vue'), meta: { title: 'Workspace selection', body: 'workspace-page', public: true } },
    { path: '/bank', component: () => import('./features/bank/Bank.vue'), meta: { title: 'Bank statement', public: true } },
    { path: '/documents', component: () => import('./features/extraction/Documents.vue'), meta: { title: 'Document status', body: 'documents-page', public: true } },
    { path: '/review', component: () => import('./features/duplicates/Review.vue'), meta: { title: 'Exact duplicates' } },
    { path: '/exact-report', redirect: '/review' },
    { path: '/content-review', redirect: '/documents' },
    { path: '/settings', component: () => import('./features/settings/Settings.vue'), meta: { title: 'Settings' } },
    { path: '/complete', redirect: '/final-report' },
    { path: '/extraction-review', component: () => import('./features/extraction/ExtractionReview.vue'), meta: { title: 'Review Extraction', body: 'extraction-workspace', fullscreen: true } },
    { path: '/final-report', component: () => import('./features/export/FinalReport.vue'), meta: { title: 'Export', fullscreen: true } },
    { path: '/matching', component: () => import('./features/matching/Matching.vue'), meta: { title: 'Review Matching', body: 'matching-app', fullscreen: true } },
  ],
  scrollBehavior(to, from, saved) { return saved || positions.get(to.fullPath) || { top: 0 }; },
});
const positions = new Map();
watch(() => appState.session?.review_id, () => { positions.clear(); appState.resumePath = '/documents'; }, { flush: 'sync' });
router.beforeEach(async (to, from) => {
  if (!appState.session) await loadSession();
  positions.set(from.fullPath, { left: window.scrollX, top: window.scrollY });
  if (!to.meta.public && !appState.session.active) return '/source';
  if (['/matching', '/extraction-review'].includes(to.path)) {
    try {
      // Reuse the current workspace's saved readiness; actions refresh it in the background.
      if (appState.navigationReviewId !== appState.session.review_id) await refreshNavigation();
      const step = appState.steps.find(step => step.href === to.path);
      if (!step || step.available === false) {
        toast(step?.blocked_reason || 'This page is not ready yet.');
        return step?.redirect || '/documents';
      }
    } catch { toast('Unable to check workflow readiness. Please try again.'); return '/documents'; }
  }
});
router.afterEach((to, from, failure) => {
  if (!failure && to.path !== '/source' && !to.meta.portal && appState.session?.active) appState.resumePath = to.fullPath;
  document.title = `${to.meta.title} · Accounting Copilot`;
  document.body.className = to.meta.body || '';
});
