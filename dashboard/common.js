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

/* Check saved work and expose the next available step on every dashboard page. */
function renderWorkflow(data) {
  const header = document.querySelector('main > header');
  if (!header) return;
  let guide = $('#workflow-guide');
  if (!guide) {
    guide = node('section', 'workflow-guide');
    guide.id = 'workflow-guide';
    guide.setAttribute('aria-label', 'Workflow checks');
    header.after(guide);
  }
  guide.replaceChildren();
  const nextIndex = data.steps.findIndex(step => !step.checked);
  data.steps.forEach((step, index) => {
    const item = node('div', `workflow-check ${step.checked ? 'checked' : 'pending'}`);
    const title = node('span', 'workflow-check-name', `${index + 1}. ${step.name}`);
    const button = node('button', `workflow-check-button ${step.checked ? 'checked' : ''}`, step.checked ? 'Checked' : 'Check');
    button.type = 'button';
    button.setAttribute('aria-label', `Check ${step.name}`);
    button.onclick = async () => {
      button.disabled = true;
      try { renderWorkflow(await api('/api/workflow-checks')); }
      catch (error) { button.textContent = error.message; button.disabled = false; }
    };
    item.append(title, button);
    if (index === nextIndex - 1 && step.next) {
      const next = node('a', 'workflow-next', `Next: ${data.steps[nextIndex].name}`);
      next.href = step.next;
      item.append(next);
    }
    if (step.checked && ['Exact duplicates', 'Content review'].includes(step.name)) {
      const undo = node('a', 'workflow-revise', step.name === 'Exact duplicates' ?
        'Review / undo selections' : 'Review / undo decisions');
      undo.href = step.href; item.append(undo);
    }
    guide.append(item);
  });
}
api('/api/workflow-checks').then(renderWorkflow).catch(() => {});
