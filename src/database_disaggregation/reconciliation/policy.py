"""Validate and freeze the assumptions of a reconciliation run."""
import copy
import hashlib
from importlib.metadata import distribution
import json
from pathlib import Path
import sys

from database_disaggregation.core.paths import PROJECT_ROOT


def default_policy_path():
    path = PROJECT_ROOT/'config/cleaning-policy.json'
    if path.exists():
        return path
    for item in distribution('database-disaggregation').files or []:
        if str(item).endswith('share/database-disaggregation/config/cleaning-policy.json'):
            return Path(distribution('database-disaggregation').locate_file(item))
    return Path(sys.prefix)/'share/database-disaggregation/config/cleaning-policy.json'


def load_policy(value=True):
    if value is True:
        value = default_policy_path()
    document = copy.deepcopy(value) if isinstance(value, dict) else json.loads(Path(value).read_text())
    if document.get('schema_version') != 1 or not document.get('id') or not document.get('sectors'):
        raise ValueError('A cleaning policy needs schema_version=1, id and explicit sector decisions.')
    if document.get('parent_policy') != 'reviewed_or_scoped_else_declared':
        raise ValueError('Unsupported cleaning parent policy.')
    for sector, record in document['sectors'].items():
        source = record['output_source']
        if source['kind'] not in ('purdue','template','template_share','legacy_share'):
            raise ValueError(f'{sector}: unsupported output source.')
        if source['kind'].startswith('template') and (not source.get('file') or not source.get('column')):
            raise ValueError(f'{sector}: an explicit template file and value column are required.')
        if float(source.get('factor',1)) <= 0:
            raise ValueError('Unit conversion factors must be positive.')
    for group in document.get('overlap_groups',[]):
        if set(group['members']) - document['sectors'].keys() or group['reference'] not in group['members']:
            raise ValueError('An overlap group must refer to known sector identities.')
        if len(group['weights']) != len(group['members']) or any(w < 0 for w in group['weights']) or abs(sum(group['weights'])-1)>1e-12:
            raise ValueError('Overlap allocation weights must be nonnegative and sum to one.')
    if document['output'] != {'missing':'macroregion_parent_share','all_missing':'legacy_global_parent_share','cap':'proportional'}:
        raise ValueError('Unsupported output reconciliation rules.')
    if any(float(v)<=0 for v in document['trade']['weights'].values()):
        raise ValueError('Trade reliability weights must be positive.')
    if document['profiles']['negative_factors'] != 'preserve':
        raise ValueError('Signed negative factor priors must be preserved.')
    canonical = json.dumps(document, sort_keys=True, allow_nan=False).encode()
    return document, hashlib.sha256(canonical).hexdigest()
