"""Create an explicitly reconciled preparation for a controlled model comparison."""
import argparse
import json
from pathlib import Path
from database_disaggregation.reconciliation.factor_domains import reconcile_prepared_factors

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--prepared', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--sectors', nargs='+', required=True, help='Only these sectors are eligible for factor reconciliation.')
    a = p.parse_args()
    audit = reconcile_prepared_factors(a.prepared, a.output, a.sectors)
    print(json.dumps(dict(output=str(a.output), profiles=audit['profiles'], changed_zip_members=audit['changed_zip_members']), indent=2))
