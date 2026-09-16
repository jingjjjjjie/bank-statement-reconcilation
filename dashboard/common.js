/* Shared local API helpers; model calls never originate from these pages. */
const $ = s => document.querySelector(s);
let token;
const node = (tag, cls, text) => {const el = document.createElement(tag); if (cls) el.className = cls; if (text !== undefined) el.textContent = text; return el;};
async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Review-Token': token}, body: JSON.stringify(body)});
  const data = await response.json(); if (!response.ok) throw Error(data.error || 'Request failed'); return data;
}
function toast(message) {$('#toast').textContent = message; $('#toast').hidden = false; clearTimeout(toast.timer); toast.timer = setTimeout(() => $('#toast').hidden = true, 5000);}
