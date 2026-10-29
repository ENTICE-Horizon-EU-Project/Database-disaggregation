"""Prepare the scoped 13-region extension; this command does not run a solver."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from database_disaggregation.core.paths import PROJECT_ROOT, project_data_root
from database_disaggregation.reconciliation.additional_sectors import prepare_additional


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='Fresh local preparation directory.')
    parser.add_argument('--config', type=Path, default=PROJECT_ROOT/'config/additional-sectors-13.json')
    parser.add_argument('--data-root', type=Path, help='Defaults to paths.local.json / ENTICE_DATA_ROOT.')
    parser.add_argument('--baseline-run', type=Path, help='Existing completed database; relative to Data split or absolute.')
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    data = args.data_root.resolve() if args.data_root else project_data_root(required=True)
    baseline = args.baseline_run or Path(config['baseline_run'])
    if not baseline.is_absolute():
        baseline = data/baseline
    if not (baseline/'state.json').is_file():
        parser.error(f'Completed baseline checkpoint is unavailable: {baseline}')
    rules = deepcopy(config['sectors'])
    for sector, components in config.get('country_components', {}).items():
        if sector in rules:
            rules[sector]['country_components'] = components
    expected = set(config['scope']['new']) | set(config['scope']['rebuild'])
    if set(rules) != expected or set(rules) & set(config['scope']['excluded_by_owner']):
        parser.error('Configured sectors disagree with the explicitly authorised scope.')
    root = prepare_additional(args.output, data, baseline, rules,
        matching=PROJECT_ROOT/'data/GTAP12_matching.xlsx',
        geography_file=PROJECT_ROOT/'data/geographies/gtap13.json',
        rebuild_sectors=config['scope']['rebuild'])
    decisions = dict(active=rules, scope=config['scope'], labels=config['labels'],
        other_residual_labels='Rest of + original parent description',
        config_sha256=hashlib.sha256(args.config.read_bytes()).hexdigest())
    (root/'source-decisions.json').write_text(json.dumps(decisions, indent=2)+'\n')
    (root/'additional-sectors-config.json').write_text(json.dumps(config, indent=2)+'\n')
    print(json.dumps(dict(prepared=str(root.resolve()), baseline=str(baseline),
                          steps=list(rules), optimisation_run=False), indent=2))


if __name__ == '__main__':
    main()
