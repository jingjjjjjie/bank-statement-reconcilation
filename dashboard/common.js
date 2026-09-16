/* Shared local API helpers; model calls never originate from these pages. */
const $ = s => document.querySelector(s);
let token;
const node = (tag, cls, text) => {const el = document.createElement(tag); if (cls) el.className = cls; if (text !== undefined) el.textContent = text; return el;};
async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Review-Token': token}, body: JSON.stringify(body)});
  const data = await response.json(); if (!response.ok) throw Error(data.error || 'Request failed'); return data;
}
function toast(message) {$('#toast').textContent = message; $('#toast').hidden = false; clearTimeout(toast.timer); toast.timer = setTimeout(() => $('#toast').hidden = true, 5000);}
if ($('.workspace')) api('/api/workspace').then(info => {
  $('.workspace strong').textContent = info.name;
  $('.workspace > span:last-child').textContent = info.period;
  if ($('.breadcrumb')) $('.breadcrumb').append(node('span', 'review-context', `${info.name} · ${info.period}`));
}).catch(() => {});

/* Summarize saved workflow state without competing with each page's main action. */
function renderWorkflow(data) {
  const header = document.querySelector('main > header');
  if (!header) return;
  let progress = $('#workflow-progress');
  if (!progress) {
    progress = node('nav', 'workflow-progress');
    progress.id = 'workflow-progress';
    progress.setAttribute('aria-label', 'Workflow progress');
    header.after(progress);
  }
  progress.replaceChildren();
  const path = location.pathname.replace(/\/$/, '') || '/';
  data.steps.forEach((step, index) => {
    const current = step.href === path;
    const item = node('a', `workflow-step ${step.checked ? 'done' : 'pending'} ${current ? 'current' : ''}`);
    item.href = step.href || '/complete';
    if (current) item.setAttribute('aria-current', 'step');
    item.append(node('span', 'workflow-step-number', step.checked ? '✓' : String(index + 1)),
                node('span', '', step.name));
    progress.append(item);
  });
}
api('/api/workflow-checks').then(renderWorkflow).catch(() => {});
