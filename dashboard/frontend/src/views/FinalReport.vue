<script setup>
import { computed, nextTick, onActivated, onDeactivated, ref } from 'vue';
import { api } from '../api.js';
import ReportEvidence from '../components/ReportEvidence.vue';
import '../styles/final-report.css';
const data = ref(null), error = ref(''), loading = ref(false), query = ref(''), filter = ref('all');
const selected = ref(null), itemId = ref(''), dialog = ref(null);
let opener, request = 0;
const rows = computed(() => (data.value?.banks || []).filter(b =>
  (filter.value === 'all' || b.support_status === filter.value) &&
  `${b.id} ${b.date} ${b.parties.join(' ')} ${b.description} ${b.amount}`.toLowerCase().includes(query.value.toLowerCase())));
const pending = computed(() => data.value?.banks.filter(b => b.review_status === 'pending').length || 0);
const allocations = computed(() => selected.value?.review_status === 'approved' ? selected.value.decision.allocations : []);
const item = computed(() => data.value?.items.find(i => i.id === itemId.value));
// Refresh the authoritative ledger whenever this cached page is revisited.
async function refresh() {
  const current = ++request; loading.value = true; error.value = ''; data.value = null;
  try { const result = await api('/api/matching'); if (current === request) data.value = result; }
  catch (e) { if (current === request) error.value = e.message; }
  finally { if (current === request) loading.value = false; }
}
// Native modal dialogs contain keyboard focus and keep the report in place.
async function openEvidence(bank, event) {
  opener = event.currentTarget; selected.value = bank;
  itemId.value = bank.review_status === 'approved' ? bank.decision.allocations[0]?.item_id || '' : '';
  await nextTick(); dialog.value.showModal();
}
function closeEvidence() { /* Restore the exact report control after dismissal. */ dialog.value?.close(); selected.value = null; opener?.focus(); }
function containFocus(event) {
  /* Wrap keyboard navigation within the popup, including Shift+Tab. */
  if (event.key !== 'Tab') return;
  const controls = [...dialog.value.querySelectorAll('button:not(:disabled), a[href], select:not(:disabled)')].filter(el => el.getClientRects().length);
  const first = controls[0], last = controls.at(-1);
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
}
function money(value, currency) { /* Format display values without recalculating allocations. */ return value === '' || value == null ? 'Not recorded' : `${currency || 'Currency unknown'} ${Number(value).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`; }
function decisionLabel(value) { /* Use the same human decision wording as final review. */ return {approved: 'Approved', denied: 'Rejected', pending: 'Pending'}[value]; }
onActivated(refresh);
onDeactivated(() => { request++; closeEvidence(); });
</script>

<template>
  <main class="final-report">
    <header class="report-heading"><div><a href="/matching">← Back to review</a><h1>Final report</h1><p>{{ data?.workspace || 'Reviewed bank statement' }}</p></div><a v-if="data" class="button dark" href="/api/matching-export" download="reviewed-statement.csv">Export CSV</a></header>
    <p v-if="loading" role="status">Loading saved review decisions…</p>
    <div v-if="error" role="alert" class="report-notice">{{ error }} <button type="button" @click="refresh">Retry</button></div>
    <template v-if="data">
      <div class="report-summary"><strong>{{ data.banks.length }} transactions</strong><span>{{ data.banks.filter(b => b.support_status === 'Supporting').length }} supporting</span><span>{{ data.banks.filter(b => b.support_status !== 'Supporting').length }} without full support</span></div>
      <p v-if="pending" class="report-notice">{{ pending }} {{ pending === 1 ? 'transaction still needs' : 'transactions still need' }} review. This report includes them as No supporting.</p>
      <p v-else class="report-caption">All transactions reviewed. Evidence and notes reflect your saved decisions.</p>
      <div class="report-filters"><label>Find a transaction<input v-model="query" type="search" placeholder="Name, amount or reference…"></label><label>Support status<select v-model="filter" aria-label="Support status"><option value="all">All transactions</option><option>Supporting</option><option>No supporting</option></select></label><span>{{ rows.length }} shown</span></div>
      <div class="report-table-wrap"><table class="report-table"><caption class="sr-only">Final reconciliation with saved approval decisions</caption><thead><tr><th>Transaction</th><th>Bank amount</th><th>Support status</th><th>Review</th><th>Evidence</th></tr></thead><tbody>
        <tr v-for="bank in rows" :key="bank.id"><td><strong>{{ bank.parties.join(' / ') }}</strong><small>{{ bank.date }} · {{ bank.id }}</small><span>{{ bank.description }}</span></td><td data-label="Bank amount">{{ money(bank.amount, bank.currency) }}</td><td data-label="Support"><span class="report-status" :class="{supported: bank.support_status === 'Supporting'}">{{ bank.support_status }}</span><small v-if="bank.stale">Evidence changed — recheck required</small></td><td data-label="Review">{{ decisionLabel(bank.review_status) }}</td><td><button type="button" class="text-button" :aria-label="`View evidence for ${bank.id}`" @click="openEvidence(bank, $event)">View evidence</button></td></tr>
      </tbody></table><p v-if="!rows.length" class="report-caption">No transactions match these filters.</p></div>
    </template>
    <dialog ref="dialog" class="evidence-dialog" aria-labelledby="report-evidence-title" @cancel.prevent="closeEvidence" @keydown="containFocus">
      <template v-if="selected">
        <header class="dialog-heading"><div><h2 id="report-evidence-title">{{ selected.parties.join(' / ') }}</h2><p>{{ selected.id }} · {{ selected.date }} · {{ selected.support_status }}</p></div><button type="button" class="dialog-close" aria-label="Close evidence" autofocus @click="closeEvidence">×</button></header>
        <p v-if="selected.stale" class="report-notice" role="alert">Evidence changed or is unavailable. Return to review before relying on this pairing.</p>
        <div class="evidence-columns">
          <ReportEvidence kind="bank" :id="selected.id" title="Bank statement" :preferred="selected.page" />
          <section class="supporting-pane" aria-label="Approved supporting evidence"><div v-if="allocations.length" class="evidence-switcher" role="group" aria-label="Choose approved document"><button v-for="(allocation, index) in allocations" :key="allocation.item_id" type="button" :aria-pressed="itemId === allocation.item_id" @click="itemId = allocation.item_id">{{ index + 1 }}. {{ data.items.find(i => i.id === allocation.item_id)?.filename || allocation.item_id }} <small>{{ money(allocation.amount, selected.currency) }} allocated</small></button></div>
            <ReportEvidence v-if="item" :key="item.id" kind="item" :id="item.id" :title="item.filename" :preferred="Math.max(0, item.unit)" />
            <p v-else class="report-caption">No approved supporting evidence for this transaction.</p>
          </section>
        </div>
        <footer class="evidence-summary"><div><span>Bank amount</span><strong>{{ money(selected.amount, selected.currency) }}</strong></div><div><span>Allocated</span><strong>{{ money(selected.decision?.allocated_total || '0', selected.currency) }}</strong></div><div><span>Difference</span><strong>{{ money(selected.decision?.difference ?? selected.amount, selected.currency) }}</strong></div><p><strong>Review notes:</strong> {{ selected.decision?.note || 'No notes recorded.' }}</p><p v-for="flag in selected.decision?.flags || []" :key="flag">{{ flag }}</p></footer>
      </template>
    </dialog>
  </main>
</template>
