"""Build a private, static evidence viewer from a frozen matching experiment."""
import argparse
import csv
from html import escape
import json
from pathlib import Path
import re
import shutil

from dashboard import office_preview
from reconciliation.duplicate_workflow import fingerprint
from scripts.benchmark_matching import number


CSS = """*{box-sizing:border-box}body{margin:0;font:15px system-ui;color:#172b40;background:#f4f7fb}header{padding:18px 24px;background:#142b43;color:white}h1{font-size:23px;margin:0 0 8px}h2{font-size:19px}p{line-height:1.5}a{color:#1761a0}header a{color:#c7e8ff}.shell{display:grid;grid-template-columns:310px 1fr;height:calc(100vh - 108px)}nav{overflow:auto;background:white;padding:12px}nav a{display:block;text-decoration:none;padding:12px;border-bottom:1px solid #e2e8ef}nav a:hover{background:#e9f2fb}iframe{width:100%;height:100%;border:0;background:white}.review{display:grid;grid-template-columns:minmax(300px,40%) 1fr;gap:16px;padding:16px;height:100vh}.details{overflow:auto}.preview{height:100%;border:1px solid #d9e2ec;border-radius:10px;overflow:hidden}.card{background:white;border:1px solid #d9e2ec;border-radius:10px;padding:16px;margin-bottom:14px}.reason{background:#fff5d9;border-left:4px solid #c18900}.muted{color:#62758a;font-size:13px}.money{font-size:25px;font-weight:700}.pill{display:inline-block;background:#e5eff8;padding:4px 8px;border-radius:5px;font-size:12px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:13px ui-monospace;line-height:1.5}img{max-width:100%;height:auto}table{border-collapse:collapse;font-size:13px}td,th{border:1px solid #cbd5df;padding:7px;white-space:pre-wrap;min-width:65px}.document{padding:20px;overflow:auto}.document iframe{height:85vh}.diff{color:#a33b16;font-weight:600}@media(max-width:850px){.shell{grid-template-columns:220px 1fr}.review{display:block;height:auto}.preview{height:85vh}}"""


def read(path):
    """Read a saved UTF-8 snapshot."""
    return json.loads(path.read_text(encoding='utf-8'))


def page(title, body):
    """Escape page metadata and share a local stylesheet."""
    return f'<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title)}</title><link rel="stylesheet" href="style.css"><body>{body}</body></html>'


def office_html(source):
    """Display original Office cells and paragraphs without model paraphrasing."""
    sections = []
    info = office_preview.describe(source)
    for n in range(info['pages']):
        data = office_preview.page(source,n)
        sections.append(f'<h2>{escape(info["labels"][n])}</h2>')
        if data['kind']=='spreadsheet':
            rows = [[str(data['start']+r)] + [c['text'] for c in cells] for r,cells in enumerate(data['rows'])]
            sections.append('<p class="muted">Original worksheet values; first column below is the row number. Simplified formatting.</p>')
            sections.append('<table>'+''.join('<tr>'+''.join(f'<td>{escape(c)}</td>' for c in row)+'</tr>' for row in rows)+'</table>')
        else:
            for block in data['blocks']:
                if block['type']=='paragraph':
                    sections.append('<p>'+escape(''.join(r['text'] for r in block['runs']))+'</p>')
                else:
                    sections.append('<table>'+''.join('<tr>'+''.join(f'<td>{escape(c)}</td>' for c in row)+'</tr>' for row in block['rows'])+'</table>')
    return ''.join(sections)


def export_document(digest, document, output):
    """Copy a hash-verified original and expose its original visual or structured evidence."""
    source = Path(document['paths'][0])
    if fingerprint(source)!=digest:
        raise ValueError(f'Source changed: {source}')
    name = digest+source.suffix.lower()
    shutil.copyfile(source,output/name)
    body = f'<main class="document"><h1>{escape(source.name)}</h1><p class="muted">{escape(str(source))}</p><p><a href="{name}" target="_blank">Open / download original</a></p>'
    if source.suffix.lower()=='.pdf':
        body += f'<iframe title="Original PDF" src="{name}"></iframe>'
    elif source.suffix.lower() in {'.xlsx','.docx'}:
        body += office_html(source)
    elif source.suffix.lower() in {'.jpg','.jpeg','.png','.webp','.gif','.bmp'}:
        body += f'<a href="{name}" target="_blank"><img src="{name}" alt="Original supporting evidence"></a>'
    else:
        body += '<p>Use the original-file link to view this format.</p>'
    body += '<details><summary>Prepared source text and page images</summary>'
    for n,unit in enumerate(document['units']):
        body += f'<h2>{escape(unit["label"])}</h2><pre>{escape(unit.get("text", ""))}</pre>'
        if unit.get('image'):
            image = Path(unit['image'])
            image_name = f'{digest}-{n}{image.suffix}'
            shutil.copyfile(image,output/image_name)
            body += f'<img loading="lazy" src="{image_name}" alt="Prepared source page {n+1}">'
    (output/f'{digest}.html').write_text(page(source.name,body+'</details></main>'),encoding='utf-8')


def build(base, bank_csv, statement):
    """Publish every tentative row with selected, mentioned and contextual candidate evidence."""
    facts, index = read(base/'facts.json'), read(base/'index.json')
    rows = [r for r in read(base/'decisions.json') if r['assessment']=='tentative']
    banks = {b['id']:b for b in facts['banks']}
    items = {i['id']:i for i in facts['items']}
    output = base/'viewer'
    output.mkdir(exist_ok=True)
    (output/'style.css').write_text(CSS,encoding='utf-8')
    if fingerprint(statement)!=facts['statement_hash'] or fingerprint(bank_csv)!=facts['bank_hash']:
        raise ValueError('Bank source differs from the frozen benchmark')
    shutil.copyfile(statement,output/'statement.pdf')
    with bank_csv.open(encoding='utf-8-sig') as stream:
        pages = {'B'+r['sequence']:r['page'] for r in csv.DictReader(stream)}
    candidates = {}
    for stage in ('matching','contextual'):
        for path in (base/stage).glob('input-*.json'):
            for bank in read(path)['banks']:
                candidates.setdefault(bank['id'],[]).extend(bank['candidate_ids'])
    exported, links = set(), []
    for row in rows:
        bank = banks[row['bank_id']]
        name = ' / '.join(bank['parties'])
        links.append(f'<a href="{bank["id"]}.html" target="review"><b>{escape(name)}</b><br>{bank["currency"]} {bank["amount"]} <span class="muted">· {bank["id"]} · {bank["date"]}</span></a>')
        allocated = {a['item_id']:a['amount'] for a in row['allocations']}
        mentioned = re.findall(r'\bD\d+\b',row['reason'])
        keys = list(dict.fromkeys([*allocated,*mentioned,*candidates.get(bank['id'],[])]))
        body = f'<div class="review"><section class="details"><div class="card"><span class="pill">{bank["id"]} · Possible match</span><h1>{escape(name)}</h1><div class="money">{bank["currency"]} {bank["amount"]}</div><p>{bank["date"]} · {"Outgoing" if bank["direction"]=="out" else "Incoming"}</p><pre>{escape(bank["description"])}</pre><a href="statement.pdf#page={pages[bank["id"]]}" target="evidence">View bank statement · page {pages[bank["id"]]}</a></div><div class="card reason"><b>Why it needs review</b><p>{escape(row["reason"])}</p></div>'
        first = None
        for key in keys:
            if key not in items:
                continue
            item = items[key]
            digest = item['document']
            doc = index['documents'][digest]
            if digest not in exported:
                export_document(digest,doc,output)
                exported.add(digest)
            first = first or digest
            label = 'Suggested allocation' if key in allocated else 'Mentioned in review' if key in mentioned else 'Other shortlisted evidence — not selected'
            amount = f'{item["currency"] or "Currency unknown"} {item["amount"] or "Amount unknown"}'
            body += f'<div class="card"><span class="pill">{key} · {label}</span><h2>{escape(Path(doc["paths"][0]).name)}</h2><p><b>Extracted amount:</b> {escape(amount)}</p><p>{escape(item["location"])}</p><p>{escape(item["description"])}</p>'
            if key in allocated:
                body += f'<p>Proposed allocation: {escape(allocated[key])}</p>'
            if item['currency']==bank['currency'] and number(item['amount']) is not None:
                difference = number(bank['amount'])-number(item['amount'])
                body += f'<p class="diff">Bank minus this item: {bank["currency"]} {difference:.2f}</p>' if difference else '<p>Amount matches this item.</p>'
            body += f'<a href="{digest}.html" target="evidence">View original evidence →</a></div>'
        body += '</section><section class="preview">'
        body += f'<iframe name="evidence" title="Supporting evidence" src="{first}.html"></iframe>' if first else '<p>No document candidate was saved for this line.</p>'
        (output/f'{bank["id"]}.html').write_text(page(bank['id'],body+'</section></div>'),encoding='utf-8')
    header = f'<header><h1>Possible matches <span class="pill">{len(rows)}</span></h1><div>Temporary evidence viewer · 20-line benchmark · proposals only · <a href="http://127.0.0.1:8765">Dashboard</a></div></header>'
    body = header+'<div class="shell"><nav>'+''.join(links)+f'</nav><iframe name="review" title="Bank entry and evidence" src="{rows[0]["bank_id"]}.html"></iframe></div>'
    (output/'index.html').write_text(page('Possible matches',body),encoding='utf-8')
    print(f'Built {len(rows)} possible matches with {len(exported)} original evidence documents: {output}',flush=True)


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('base',type=Path)
    parser.add_argument('--bank',type=Path,required=True)
    parser.add_argument('--statement',type=Path,required=True)
    args = parser.parse_args()
    build(args.base,args.bank,args.statement)
