<script setup>
import PageHelp from '../../components/PageHelp.vue';
import { computed, nextTick, onActivated, onDeactivated, ref } from 'vue';
import { api } from '../../api.js';
import ReportEvidence from './ReportEvidence.vue';
import ExportDownloads from './ExportDownloads.vue';
import './final-report.css';
const data = ref(null), error = ref(''), loading = ref(false), query = ref(''), filter = ref('all');
const exportDialog = ref(null), exportButton = ref(null);
const selected = ref(null), itemId = ref(''), dialog = ref(null);
const downloading = ref(false), downloadError = ref('');
let opener, request = 0;
const evidencePositions = new Map();
const selectedItems = new Map();
const rows = computed(() => (data.value?.banks || []).filter(b =>
  (filter.value === 'all' || b.support_status === filter.value) &&
  `${b.id} ${b.date} ${b.parties.join(' ')} ${b.description} ${b.amount}`.toLowerCase().includes(query.value.toLowerCase())));
const pending = computed(() => data.value?.banks.filter(b => b.review_status === 'pending').length || 0);
const allocations = computed(() => selected.value?.review_status === 'approved' ? selected.value.decision.allocations : []);
const item = computed(() => data.value?.items.find(i => i.id === itemId.value));
const documents = computed(() => {
  // Group approved pieces by original document while retaining each saved allocation.
  const groups = new Map();
  for (const allocation of allocations.value) {
    const source = data.value?.items.find(item => item.id === allocation.item_id);
    if (!source) continue;
    if (!groups.has(source.document)) groups.set(source.document, {item: source, allocations: []});
    groups.get(source.document).allocations.push(allocation);
  }
  return [...groups.values()];
});
// The server rechecks approval and original bytes before choosing a file or ZIP.
async function downloadEvidence() {
  if (!selected.value || downloading.value) return;
  const bankId = selected.value.id;
  downloading.value = true; downloadError.value = '';
  try {
    const response = await fetch(`/api/matching-evidence-download?${new URLSearchParams({bank_id: bankId})}`);
    if (!response.ok) { const result = await response.json(); throw Error(result.error || 'Unable to download evidence'); }
    const disposition = response.headers.get('Content-Disposition') || '';
    const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i);
    const plain = disposition.match(/filename="([^"]+)"/i);
    const filename = encoded ? decodeURIComponent(encoded[1]) : plain?.[1] || 'evidence.zip';
    const url = URL.createObjectURL(await response.blob()), link = document.createElement('a');
    link.href = url; link.download = filename; document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (e) { if (selected.value?.id === bankId) downloadError.value = e.message; }
  finally { downloading.value = false; }
}

// Keep rows visible while checking the ledger, including changes from other tabs.
async function refresh() {
  const current = ++request; loading.value = true; error.value = '';
  try { const result = await api('/api/matching'); if (current === request) data.value = result; }
  catch (e) { if (current === request) error.value = e.message; }
  finally { if (current === request) loading.value = false; }
}
// Native modal dialogs contain keyboard focus and keep the report in place.
async function openEvidence(bank, event) {
  opener = event.currentTarget; selected.value = bank; downloadError.value = '';
  const approved = bank.review_status === 'approved' ? bank.decision.allocations : [];
  itemId.value = approved.find(item => item.item_id === selectedItems.get(bank.id))?.item_id || approved[0]?.item_id || '';
  await nextTick(); dialog.value.showModal();
}
function closeEvidence() {
  /* Retain evidence choice and restore the report control after dismissal. */
  if (selected.value && itemId.value) selectedItems.set(selected.value.id, itemId.value);
  dialog.value?.close(); selected.value = null; opener?.focus();
}
function closeExport() {
  /* Restore focus to the export button after dismissal or download. */
  if (!exportDialog.value?.open) return;
  exportDialog.value.close(); exportButton.value?.focus();
}
function containFocus(event) {
  /* Wrap keyboard navigation within the popup, including Shift+Tab. */
  if (event.key !== 'Tab') return;
  const controls = [...event.currentTarget.querySelectorAll('button:not(:disabled), a[href], select:not(:disabled), summary')].filter(el => el.getClientRects().length);
  const first = controls[0], last = controls.at(-1);
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
}
function money(value, currency) { /* Format display values without recalculating allocations. */ return value === '' || value == null ? 'Not recorded' : `${currency || 'Currency unknown'} ${Number(value).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`; }
function decisionLabel(value) { /* Use the same human decision wording as final review. */ return {approved: 'Approved', denied: 'Rejected', pending: 'Pending'}[value]; }
onActivated(refresh);
onDeactivated(() => { request++; loading.value = false; closeEvidence(); closeExport(); });
</script>

<template>
  <main class="final-report" :aria-busy="loading">
    <header class="report-heading"><div class="page-title"><h1 id="completion-title">Final report</h1><PageHelp page="FinalReport" /></div><button ref="exportButton" type="button" class="button dark" @click="exportDialog.showModal()">Export</button></header>
    <div class="export-layout">
      <section class="transaction-report" aria-label="Transaction report">
    <p v-if="loading && !data" role="status">Loading saved review decisions…</p>
    <div v-if="error" role="alert" class="report-empty"><span class="report-eyebrow">TRANSACTION REPORT</span><h2>Report not ready</h2><p>Prepare matching to see the final transaction report here.</p><button type="button" class="button secondary" @click="refresh">Retry</button><details><summary>Error details</summary>{{ error }}</details></div>
    <template v-if="data">
      <div class="report-summary"><div><span>Transactions</span><strong>{{ data.banks.length }}</strong></div><div class="summary-supported"><span>Supporting</span><strong>{{ data.banks.filter(b => b.support_status === 'Supporting').length }}</strong></div><div><span>Without full support</span><strong>{{ data.banks.filter(b => b.support_status !== 'Supporting').length }}</strong></div></div>
      <p v-if="pending" class="report-notice">{{ pending }} {{ pending === 1 ? 'transaction still needs' : 'transactions still need' }} review. This report includes them as No supporting.</p>

      <div class="report-filters"><label>Find a transaction<input v-model="query" type="search" placeholder="Name, amount or reference…"></label><label>Support status<select v-model="filter" aria-label="Support status"><option value="all">All transactions</option><option>Supporting</option><option>No supporting</option></select></label><span>{{ rows.length }} shown</span></div>
      <div class="report-table-wrap"><table class="report-table"><caption class="sr-only">Final reconciliation with saved approval decisions</caption><thead><tr><th>Transaction</th><th>Bank amount</th><th>Support status</th><th>Review</th><th>Evidence</th></tr></thead><tbody>
        <tr v-for="bank in rows" :key="bank.id"><td><strong>{{ bank.parties.join(' / ') }}</strong><span>{{ bank.description }}</span></td><td data-label="Bank amount">{{ money(bank.amount, bank.currency) }}</td><td data-label="Support"><span class="report-status" :class="{supported: bank.support_status === 'Supporting'}">{{ bank.support_status }}</span><small v-if="bank.stale">Evidence changed — recheck required</small></td><td data-label="Review">{{ decisionLabel(bank.review_status) }}</td><td><button v-if="bank.review_status === 'approved' && !bank.stale && bank.decision?.allocations?.length" type="button" class="text-button" :aria-label="`View evidence for ${bank.id}`" @click="openEvidence(bank, $event)">View evidence</button></td></tr>
      </tbody></table><p v-if="!rows.length" class="report-caption">No transactions match these filters.</p></div>
    </template>
      </section>

    </div>
    <dialog ref="exportDialog" class="report-export-dialog" aria-labelledby="report-export-title" @cancel.prevent="closeExport" @keydown="containFocus">
      <header class="dialog-heading"><h2 id="report-export-title">Export</h2><button type="button" class="dialog-close" aria-label="Close export" @click="closeExport">&times;</button></header>
      <ExportDownloads>
        <div v-if="data" class="workbook-options">
          <a class="button dark" href="/api/matching-workbook?include_evidence_paths=true" download="reviewed-statement-with-paths.xlsx" @click="closeExport">With supporting evidence paths</a>
          <a class="button secondary" href="/api/matching-workbook?include_evidence_paths=false" download="reviewed-statement.xlsx" @click="closeExport">Without supporting evidence paths</a>
        </div>
        <p v-else class="workbook-unavailable">Available when the report is ready.</p>
      </ExportDownloads>
    </dialog>
    <dialog ref="dialog" class="evidence-dialog" aria-labelledby="report-evidence-title" @cancel.prevent="closeEvidence" @keydown="containFocus">
      <template v-if="selected">
        <header class="dialog-heading evidence-heading">
          <div><h2 id="report-evidence-title">Supporting evidence</h2><p>{{ documents.length }} {{ documents.length === 1 ? 'document' : 'documents' }} &middot; Approved</p></div>
          <div class="evidence-heading-actions">
            <button class="button dark evidence-download" type="button" aria-label="Download evidence" :disabled="downloading || selected.stale || !documents.length" @click="downloadEvidence">
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3v12m-4-4 4 4 4-4M5 16v4h14v-4" /></svg>
              {{ downloading ? 'Preparing...' : 'Download evidence' }}<span v-if="documents.length > 1 && !downloading" class="evidence-filetype">ZIP</span>
            </button>
            <button type="button" class="dialog-close" aria-label="Close evidence" autofocus @click="closeEvidence">&times;</button>
          </div>
        </header>
        <p v-if="downloadError" class="evidence-download-error" role="alert">{{ downloadError }}</p>
        <p v-if="selected.stale" class="report-notice" role="alert">Evidence changed or is unavailable. Return to review before relying on this pairing.</p>
        <div class="evidence-workspace">
          <aside class="evidence-sidebar" aria-label="Payment and approved documents">
            <section class="evidence-payment">
              <span class="evidence-source-label">From bank statement</span>
              <h3>{{ selected.parties.join(' / ') }}</h3>
              <strong class="evidence-payment-amount">{{ money(selected.amount, selected.currency) }}</strong>
              <p class="evidence-payment-date">{{ selected.date || 'Date not recorded' }}</p>
              <p class="evidence-payment-description">{{ selected.description }}</p>
            </section>
            <section class="evidence-document-list" aria-label="Approved documents">
              <h3>Documents <span>{{ documents.length }}</span></h3>
              <div class="evidence-switcher" role="group" aria-label="Choose approved document">
                <button v-for="(document, index) in documents" :key="document.item.document" type="button" :aria-label="`${index + 1}. ${document.item.filename}`" :aria-pressed="item?.document === document.item.document" @click="itemId = document.item.id">
                  <span class="evidence-document-number">{{ index + 1 }}</span>
                  <span class="evidence-document-copy"><strong>{{ document.item.filename }}</strong>
                    <small v-for="allocation in document.allocations" :key="allocation.item_id">{{ allocation.amount === '' ? 'Supporting only' : `Allocated ${money(allocation.amount, selected.currency)}` }}</small>
                  </span>
                </button>
              </div>
            </section>
            <section class="evidence-summary" aria-label="Saved allocation summary">
              <div><span>Allocated</span><strong>{{ money(selected.decision?.allocated_total || '0', selected.currency) }}</strong></div>
              <div :class="{ 'evidence-difference': Number(selected.decision?.difference ?? selected.amount) !== 0 }"><span>Difference</span><strong>{{ money(selected.decision?.difference ?? selected.amount, selected.currency) }}</strong></div>
              <p v-if="selected.decision?.note" class="evidence-review-note"><span>Review notes</span>{{ selected.decision.note }}</p>
              <p v-for="flag in selected.decision?.flags || []" :key="flag" class="evidence-difference">{{ flag }}</p>
            </section>
          </aside>
          <section class="supporting-pane" aria-label="Approved supporting evidence">
            <ReportEvidence :positions="evidencePositions" v-if="item" :key="item.id" kind="item" :id="item.id" :title="item.filename" :preferred="Math.max(0, item.unit)" />
            <p v-else class="report-caption">No approved supporting evidence for this transaction.</p>
          </section>
        </div>
      </template>
    </dialog>
  </main>
</template>
