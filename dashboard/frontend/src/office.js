import { node } from './dom.js';

/* Build safe visual Office previews from structured local document data. */
export function renderOfficePreview(target, data) {
  target.replaceChildren();
  if (data.kind === 'word') {
    const page = node('div', 'word-page');
    for (const block of data.blocks) {
      if (block.type === 'table') {
        const table = node('table', 'office-table');
        for (const row of block.rows) {
          const tr = node('tr');
          for (const value of row) tr.append(node('td', '', value));
          table.append(tr);
        }
        page.append(table);
      } else {
        const heading = /^Heading[1-6]$/.test(block.style) ? block.style.toLowerCase() : '';
        const paragraph = node('p', `word-paragraph ${heading}`);
        if (['center', 'right', 'both'].includes(block.align)) paragraph.style.textAlign = block.align === 'both' ? 'justify' : block.align;
        for (const run of block.runs) {
          const span = node('span', '', run.text);
          if (run.bold) span.style.fontWeight = '700';
          if (run.italic) span.style.fontStyle = 'italic';
          paragraph.append(span);
        }
        page.append(paragraph);
      }
    }
    target.append(page);
    return;
  }
  const sheet = node('div', 'sheet-page');
  sheet.append(node('div', 'sheet-title', data.sheet));
  const scroll = node('div', 'sheet-scroll'), table = node('table', 'office-table sheet-table');
  for (let rowIndex = 0; rowIndex < data.rows.length; rowIndex++) {
    const tr = node('tr');
    tr.append(node('th', 'row-number', String(data.start + rowIndex)));
    for (const cell of data.rows[rowIndex]) {
      const td = node('td', '', cell.text);
      if (cell.bold) td.style.fontWeight = '700';
      if (cell.fill) td.style.backgroundColor = cell.fill;
      tr.append(td);
    }
    table.append(tr);
  }
  scroll.append(table); sheet.append(scroll);
  if (data.truncated_columns) sheet.append(node('small', 'preview-note', 'Showing the first 40 columns. Open the file for the full worksheet.'));
  target.append(sheet);
}
