"""Profile one real GTAP Power 2023 monetary split on prepared CFDHub inputs."""
import argparse
import cProfile
from contextlib import ExitStack
from datetime import datetime, timezone
from functools import wraps
import hashlib
from importlib.metadata import version
import json
import marshal
import os
from pathlib import Path
import platform
import pstats
import resource
import signal
import sys
import tempfile
import time
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
CONFIG = HERE.parents[1] / "config" / "model-trials"


def read_json(path):
    return json.loads(path.read_text())


def check_workflow(data_root):
    """Exercise the installed stack and resolve source roles through the project API."""
    import cvxlab
    import cvxpy
    import database_disaggregation
    import mario
    import pyarrow.parquet as parquet
    from database_disaggregation.core.paths import PROJECT_ROOT, data_path
    from database_disaggregation.reconciliation.policy import load_policy

    if PROJECT_ROOT != HERE.parents[1]:
        raise RuntimeError(f"Activate the environment for this checkout: imported {PROJECT_ROOT}")
    if not hasattr(cvxlab, "Model") or not callable(getattr(mario.Database, "add_sectors", None)):
        raise RuntimeError("The installed MARIO/CVXLab checkouts do not expose the split model APIs")
    for package in (database_disaggregation, mario, cvxlab):
        print(f"{package.__name__}: {package.__file__}")
    solvers = set(cvxpy.installed_solvers())
    if not {"CLARABEL", "HIGHS"} <= solvers:
        raise RuntimeError(f"Missing benchmark solvers; detected {sorted(solvers)}")
    for role in ("baseline", "classifications", "gtap_totals", "mario_inventories", "value_added",
                 "purdue_trade", "purdue_split_targets", "exioiot", "copcosts", "copper_sectors"):
        data_path(role, required=True, data_root=data_root)
    source = data_path("resolved_inventories", required=True, data_root=data_root)
    templates = data_path("partner_templates", required=True, data_root=data_root)
    policy, _ = load_policy()
    for sector, definition in policy["sectors"].items():
        if not (source / f"{sector}.xlsx").is_file():
            raise FileNotFoundError(source / f"{sector}.xlsx")
        template = definition["output_source"].get("file")
        if template and not (templates / template).is_file():
            raise FileNotFoundError(templates / template)
    baseline = data_path("baseline", required=True, data_root=data_root)
    native_rows = parquet.ParquetFile(baseline / "Z.parquet").metadata.num_rows
    if len(policy["sectors"]) != 67 or native_rows != 163 * 76:
        raise ValueError("Unexpected source policy or native GTAP baseline")
    print(f"Sources: {data_root}; {native_rows} baseline rows; 67 source inventories; CLARABEL, HIGHS.")


def verify_inputs(directory, case):
    for name, expected in case["sha256"].items():
        path = directory / name
        with path.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != expected:
            raise ValueError(f"Input has changed: {path} (expected SHA-256 {expected})")


class RunProfile:
    """Persist completed phases before starting the next expensive operation."""

    def __init__(self, directory, report):
        self.directory = directory
        self.report = report
        self.report["phases"] = []
        self.started = time.monotonic()
        self.profile = None
        self.stats = None

    def save(self):
        self.report["elapsed_seconds"] = time.monotonic() - self.started
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        self.report["peak_process_rss_mib"] = rss / (2**20 if sys.platform == "darwin" else 1024)
        tmp = self.directory / "run.json.tmp"
        tmp.write_text(json.dumps(self.report, indent=2, allow_nan=False) + "\n")
        tmp.replace(self.directory / "run.json")

    def snapshot(self, _signal, _frame):
        # cProfile's on-disk format is a marshalled mapping. Take a snapshot
        # without disabling the active profiler or closing its call stack.
        if self.profile is None:
            return
        self.profile.snapshot_stats()
        tmp = self.directory / "current-phase.prof.tmp"
        with tmp.open("wb") as stream:
            marshal.dump(self.profile.stats, stream)
        tmp.replace(self.directory / "current-phase.prof")
        self.save()

    def stop_phase(self, completed):
        if self.profile is None:
            return
        signal.setitimer(signal.ITIMER_REAL, 0)
        self.profile.disable()
        end = time.monotonic()
        self.report["phases"].append(dict(name=self.report["phase"], completed=completed,
                                          seconds=end - self.phase_start))
        if self.stats is None:
            self.stats = pstats.Stats(self.profile)
        else:
            self.stats.add(self.profile)
        tmp = self.directory / "run.prof.tmp"
        self.stats.dump_stats(str(tmp))
        tmp.replace(self.directory / "run.prof")
        (self.directory / "current-phase.prof").unlink(missing_ok=True)
        self.profile = None

    def phase(self, name):
        self.stop_phase(completed=True)
        self.report["phase"] = name
        self.save()
        print(f"[{name}]", flush=True)
        self.phase_start = time.monotonic()
        self.profile = cProfile.Profile()
        self.profile.enable()
        signal.setitimer(signal.ITIMER_REAL, 60, 60)

    def observe_entry(self, stack, module, function, name):
        # These hooks time the normal calls in the pinned MARIO revision.
        original = getattr(module, function)

        @wraps(original)
        def timed(*args, **kwargs):
            self.phase(name)
            return original(*args, **kwargs)

        stack.enter_context(patch.object(module, function, timed))

    def finish(self, status):
        self.stop_phase(completed=status == "success")
        self.report["status"] = status
        self.save()
        if self.stats:
            with (self.directory / "profile.txt").open("w") as stream:
                self.stats.stream = stream
                self.stats.sort_stats("cumulative").print_stats()


def run(inputs, case, profile):
    profile.phase("load runtime")
    import mario
    import pandas as pd
    from database_disaggregation import workflow
    from mario.ops import cvxlab_bridge, split_model

    report = profile.report
    report["packages"] = {p: version(p) for p in (
        "database-disaggregation", "mariopy", "cvxlab", "cvxpy", "highspy", "clarabel", "numpy",
        "pandas", "pyarrow", "scipy", "snakeviz",
    )}
    options = {**read_json(CONFIG / "quadratic.json"), "require_finite_objective": True}
    # Tighten convergence for the Mining case while retaining MARIO's residual test.
    solver_options = {**read_json(CONFIG / "solver-qp-refined.json"), "tol_feas": 1e-12,
                      "tol_gap_rel": 1e-11}
    report.update(solver="CLARABEL", solver_options=solver_options, model_options=options)
    profile.phase("read prepared baseline")
    flows = inputs / "flows"
    db = mario.parse_from_parquet(str(flows), table="IOT", mode="flows", year=2023)
    # MARIO normally derives X from rows. Preserve the prepared independent X.
    output = pd.read_parquet(flows / "X.parquet")
    if not output.index.equals(db.Z.index) or output.shape[1] != 1:
        raise ValueError("Prepared X does not align with Z")
    db.reset_to_flows("baseline")
    db.matrices["baseline"]["X"] = output
    before = set(db.get_index("Sector"))
    regions = set(db.get_index("Region"))
    children = set(case["activities"])
    if len(regions) != case["regions"] or len(before) != case["baseline_sectors"] or before & children:
        raise ValueError("Unexpected baseline classification")
    profile.phase("read prepared inventories")
    db.read_add_sectors_excel(inputs / "add_sectors.xlsx", read_inventories=True, split=True)
    master = db.add_sectors_workbook.master_sheet
    pairs = master[["Region", "Sector"]].drop_duplicates()
    if (len(master) != case["inventory_rows"] or len(pairs) != len(regions) * len(children)
            or set(pairs["Region"]) != regions or set(pairs["Sector"]) != children):
        raise ValueError("Incomplete or mismatched region/activity coverage")

    model = profile.directory / "model"
    model.mkdir()
    profile.phase("build split and optimization problem")
    with ExitStack() as stack:
        profile.observe_entry(stack, cvxlab_bridge, "_solve_initialized_split_model", "feasibility and solve")
        profile.observe_entry(stack, split_model, "verify_model_solution", "validate solution and load results")
        profile.observe_entry(stack, cvxlab_bridge, "_parse_split_results", "assemble database")
        db.add_sectors("inventories", split=True, intermediate_steps=False, cvxlab_path=model,
                       solver=report["solver"], solver_parameters=solver_options, split_model_options=options)

    profile.phase("check final classification and residuals")
    expected = before | children
    if set(db.get_index("Sector")) != expected or set(db.get_index("Region")) != regions:
        raise ValueError("Assembled database differs from the requested classification")
    (solution_path,) = model.glob("*/model_solution.json")
    report["solution"] = read_json(solution_path)
    if not report["solution"] or any(not row["objective_finite"] or row["failed_constraint_cells"]
                                      for row in report["solution"]):
        raise ValueError(f"Invalid optimization result: {solution_path}")
    report["result_sectors"] = len(expected)
    profile.phase("export database")
    workflow.export_database(db, profile.directory / "database", inputs=inputs / "add_sectors.xlsx",
                             notes=f"CFDHub {report['case']} benchmark")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", nargs="?", default="reduced", choices=("reduced", "full"))
    parser.add_argument("--data-root", type=Path, help="local ENTICE data directory (or ENTICE_DATA_ROOT)")
    parser.add_argument("--inputs", type=Path, default=os.environ.get("GTAP_INPUTS"),
                        help="override the prepared input directory (default: <data-root>/gtap-inputs)")
    parser.add_argument("--output-root", type=Path, default=Path("build/cfdhub"))
    checks = parser.add_mutually_exclusive_group()
    checks.add_argument("--check-inputs", action="store_true", help="verify prepared input bytes and exit")
    checks.add_argument("--check-workflow", action="store_true",
                        help="verify the three repositories, solvers, source files and selected inputs")
    args = parser.parse_args()
    case = read_json(HERE / "inputs.json")[args.case]
    if args.data_root:
        os.environ["ENTICE_DATA_ROOT"] = str(args.data_root.resolve())
    if args.check_workflow or args.inputs is None:
        from database_disaggregation.core.paths import project_data_root
        root = project_data_root(required=True)
    if args.check_workflow:
        check_workflow(root)
    inputs = (args.inputs or root / "gtap-inputs").resolve() / args.case
    if args.check_inputs or args.check_workflow:
        verify_inputs(inputs, case)
        print(f"{args.case}: verified {case['regions']} regions, {len(case['activities'])} activities, "
              f"{case['inventory_rows']} region/activity inventories.")
        return
    args.output_root.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    directory = Path(tempfile.mkdtemp(prefix=f"{args.case}-{now:%Y%m%dT%H%M%SZ}-",
                                      dir=args.output_root.resolve()))
    print(f"Results: {directory}", flush=True)
    report = dict(case=args.case, status="running", started_utc=now.isoformat(), platform=platform.platform(),
                  python=sys.version, inputs=str(inputs), regions=case["regions"], activities=case["activities"],
                  inventory_rows=case["inventory_rows"], input_sha256=case["sha256"])
    profile = RunProfile(directory, report)

    def terminate(signum, _frame):
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGALRM, profile.snapshot)
    signal.signal(signal.SIGTERM, terminate)
    try:
        profile.phase("verify input files")
        verify_inputs(inputs, case)
        run(inputs, case, profile)
    except BaseException as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        profile.finish("failed")
        raise
    profile.finish("success")
    print(f"Completed. Profile: {directory / 'run.prof'}", flush=True)


if __name__ == "__main__":
    main()
