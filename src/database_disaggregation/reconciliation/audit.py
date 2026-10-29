"""Streaming provenance: original files are read as immutable byte snapshots."""
from collections import Counter
import hashlib
from io import BytesIO
import json
from pathlib import Path

from openpyxl import load_workbook


def file_sha256(path):
    """Hash large baseline files in bounded memory, including on Python 3.10."""
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):
            digest.update(chunk)
    return digest.hexdigest()


class Audit:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.stream = (self.directory/'changes.jsonl').open('w')
        self.files = {}
        self.counts = Counter()

    def record(self, rule, *, kind, **data):
        self.stream.write(json.dumps({'rule': rule, 'kind': kind, **data}, allow_nan=False)+'\n')
        self.counts[f'{kind}:{rule}'] += 1

    def read(self, path, *, role):
        path = Path(path)
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if str(path) in self.files and self.files[str(path)]['sha256'] != digest:
            raise ValueError(f'Input changed during reconciliation: {path}')
        self.files[str(path)] = {'sha256': digest, 'bytes': len(raw), 'role': role}
        return raw

    def workbook(self, path, *, role, data_only=True, read_only=True):
        return load_workbook(BytesIO(self.read(path, role=role)), data_only=data_only, read_only=read_only)

    def finish(self, summary):
        self.stream.flush()
        (self.directory/'inputs.json').write_text(json.dumps(self.files, indent=2))
        (self.directory/'summary.json').write_text(json.dumps({**summary, 'event_counts':dict(self.counts)},
                                                             indent=2, allow_nan=False))

    def close(self):
        self.stream.close()
