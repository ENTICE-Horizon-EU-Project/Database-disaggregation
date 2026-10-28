"""Render the common production, cost and trade data model as one local page."""
import base64
import gzip
from importlib.resources import files
import json
from pathlib import Path

from .collection import SourceCollection


def write_source_dashboard(collection, output):
    """Render a SourceCollection; file formats and source readers stay upstream."""
    if not isinstance(collection, SourceCollection):
        raise TypeError('Pass SourceCollection.from_pipeline(), followed by the output HTML path.')
    metadata = dict(collection.metadata)
    metadata['chunks'] = {}
    chunks = []
    for sector, payload in collection.sectors.items():
        data = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()
        encoded = base64.b64encode(gzip.compress(data, mtime=0)).decode()
        metadata['chunks'][sector] = 'chunk-' + sector
        chunks.append(f'<script type="application/octet-stream" id="chunk-{sector}">{encoded}</script>')
    resources = files(__package__)
    logo = 'data:image/svg+xml;base64,' + base64.b64encode(resources.joinpath('assets/entice.svg').read_bytes()).decode()
    replacements = {'__ENTICE_LOGO__':logo,
        '__MANIFEST__':json.dumps(metadata, ensure_ascii=False, allow_nan=False, separators=(',', ':')).replace('</','<\\/'),
        '__TABLE_CHUNKS__':''.join(chunks),
        '__EXPLORER_SCRIPT__':resources.joinpath('templates/source_dashboard.js').read_text()}
    page = resources.joinpath('templates/source_dashboard.html').read_text()
    for token, value in replacements.items():
        page = page.replace(token,value)
    output = Path(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(page,encoding='utf-8')
    return output
