/* Resolve extracted citations against the original preview page labels. */
export function evidenceLocation(item, info) {
  const text = item.amount_location || item.location || '';
  const fallback = Math.min(info.pages - 1, Math.max(0, Number(item.unit) || 0));
  if (info.kind !== 'spreadsheet') {
    const page = /(?:page|image)\s*(\d+)/i.exec(text);
    return {page: page ? Math.min(info.pages - 1, Math.max(0, Number(page[1]) - 1)) : fallback};
  }
  const qualified = /(?:'((?:[^']|'')+)'|([^!;,]+))!\$?[A-Z]+\$?\d+/i.exec(text);
  const sheet = qualified ? (qualified[1] || qualified[2]).trim().replaceAll("''", "'") :
    /sheet\s+(.+?)(?:\s*\(|\s*\/|$)/i.exec(text)?.[1]?.trim();
  const refs = [...text.matchAll(/(?:^|[^A-Za-z0-9])\$?([A-Z]{1,3})\$?(\d+)(?::\$?([A-Z]{1,3})\$?(\d+))?/gi)];
  const column = value => [...value.toUpperCase()].reduce((n, c) => n * 26 + c.charCodeAt(0) - 64, 0);
  const cells = refs.map(ref => ({start: Number(ref[2]), end: Number(ref[4] || ref[2]),
    left: column(ref[1]), right: column(ref[3] || ref[1])}));
  if (!cells.length) return {page: fallback};
  const page = info.labels.findIndex(label => {
    const range = /^(.*) \u00b7 rows (\d+)[\u2013-](\d+)$/.exec(label);
    return range && (!sheet || range[1].toLowerCase() === sheet.toLowerCase()) &&
      cells[0].start >= Number(range[2]) && cells[0].start <= Number(range[3]);
  });
  return page < 0 ? {page: fallback} : {page, highlight: {cells}};
}
