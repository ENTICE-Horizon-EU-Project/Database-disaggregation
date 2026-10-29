"""Benchmark a completed monetary checkpoint against its exact pre-split baseline.

No solver is imported or run. Paths may be absolute or relative to Data split.
"""
import argparse
import os
from pathlib import Path

for variable in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS'):
    os.environ.setdefault(variable, '2')

from database_disaggregation.core.paths import project_data_root
from database_disaggregation.core.benchmark import build_report, write_report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--output', type=Path, help='Defaults to DATABASE/benchmarking.html.')
    parser.add_argument('--overwrite', action='store_true', help='Refresh only the three generated benchmark files.')
    parser.add_argument('--skip-system', action='store_true', help='Skip Leontief linear algebra; mark it unavailable.')
    args = parser.parse_args()
    def resolve(path):
        return path.resolve() if path.is_absolute() else (project_data_root() / path).resolve()
    database, baseline = resolve(args.database), resolve(args.baseline)
    print('Reading saved matrices and verifying provenance...', flush=True)
    report = build_report(baseline, database, system=not args.skip_system)
    paths = write_report(report, resolve(args.output) if args.output else database / 'benchmarking.html',
                         overwrite=args.overwrite)
    for path in paths:
        print(path)
    print(f"Hard checks: {'PASS' if report['summary']['hard_checks_passed'] else 'FAIL'}; "
          f"review flags: {report['summary']['review_flags']}; system: {report['systems']['status']}")
    return 0 if report['summary']['hard_checks_passed'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
