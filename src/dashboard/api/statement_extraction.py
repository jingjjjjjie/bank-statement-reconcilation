"""Extract uploaded statements without opening or writing a reconciliation project."""

import base64
import binascii
import tempfile
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel, Field

from statement_extraction.excel import export
from statement_extraction.statement import extract, payees, write_master

router = APIRouter()


class StatementUpload(BaseModel):
    """Bound the standalone PDF upload and its extraction settings."""

    filename: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=40 * 1024 * 1024)
    year: int = Field(ge=1900, le=2100, strict=True)
    bank: str = 'auto'
    company: str = Field(min_length=1, max_length=200)


@router.post('/api/statement-extraction')
def statement_extraction(body: StatementUpload):
    """Validate a temporary PDF and return its preview and downloadable outputs."""
    if not body.company.strip():
        raise ValueError('Enter the company name for the workbook')
    filename = body.filename.replace('\\', '/').rsplit('/', 1)[-1]
    if not filename.lower().endswith('.pdf') or any(ord(c) < 32 for c in filename):
        raise ValueError('Choose a PDF bank statement')
    try:
        content = base64.b64decode(body.content, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError('Invalid PDF upload') from error
    if len(content) > 25 * 1024 * 1024:
        raise ValueError('Choose a PDF smaller than 25 MB')
    if b'%PDF-' not in content[:1024]:
        raise ValueError('Choose a readable PDF bank statement')
    with tempfile.TemporaryDirectory(prefix='statement-extraction-') as directory:
        root = Path(directory)
        source = root / filename
        source.write_bytes(content)
        data = extract(source, body.year, body.bank)
        master = root / 'transactions.csv'
        write_master(data, master)
        workbook = root / 'transactions.xlsx'
        export(master, body.company, workbook)
        # Keep evidence filenames portable and show the same payees the downloads contain.
        for row, party in zip(data['transactions'], payees(data['transactions'], data['bank'])):
            row['source'] = filename
            row.update(party)
        data['source'] = filename
        csv_text = master.read_text(encoding='utf-8-sig').replace(str(source), filename)
        return {
            'statement': data,
            'csv': base64.b64encode(csv_text.encode('utf-8-sig')).decode(),
            'xlsx': base64.b64encode(workbook.read_bytes()).decode(),
        }
