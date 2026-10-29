"""Assemble cumulative input packages without solving or editing checkpoints."""
from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path

import pandas as pd


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@dataclass(frozen=True)
class InventoryStage:
    checkpoint: Path
    source: Path
    applied: Path
    state: dict


def checkpoint_history(checkpoint, *, _seen=None):
    """Follow published relative links or a local controlled trial's checkpoints.

    Missing history is an error, never a reason to publish an incomplete package
    under a cumulative sector count. Historical relocated paths are not guessed.
    """
    checkpoint = Path(checkpoint).resolve()
    seen = set() if _seen is None else _seen
    if checkpoint in seen:
        raise ValueError('Cycle in inventory checkpoint history.')
    seen.add(checkpoint)
    state = json.loads((checkpoint/'state.json').read_text())
    if (checkpoint/'run.json').is_file():
        run = json.loads((checkpoint/'run.json').read_text())
        inventory = (checkpoint/run['inventory_directory']).resolve()
        applied = inventory/'step_add_sectors.xlsx'
        if not applied.is_file():
            applied = inventory/'add_sectors.xlsx'  # Legacy incremental publication.
        previous = run.get('source_database_directory')
        history = checkpoint_history(checkpoint/previous, _seen=seen) if previous else []
        return history + [InventoryStage(checkpoint, inventory/'source_add_sectors.xlsx', applied, state)]
    trial = checkpoint.parent.parent
    manifest = json.loads((trial/'trial.json').read_text())
    previous = manifest.get('source_checkpoint')
    history = checkpoint_history(previous, _seen=seen) if previous else []
    for path in sorted((trial/'checkpoints').glob('*/state.json')):
        current = json.loads(path.read_text())
        if current['step_index'] > state['step_index']:
            continue
        source = path.parent/'source_add_sectors.xlsx'
        if not source.is_file():
            source = trial/'add_sectors.xlsx'
        history.append(InventoryStage(path.parent, source, path.parent/'step_add_sectors.xlsx', current))
    if not history or history[-1].checkpoint != checkpoint:
        raise ValueError(f'Checkpoint missing from its controlled trial: {checkpoint}')
    return history


def _select(workbook, sectors):
    master = workbook.master_sheet.loc[workbook.master_sheet.Sector.isin(sectors)].copy()
    if set(master.Sector) != set(sectors):
        raise ValueError('Source workbook is missing executed sectors.')
    names = set(master['Inventory sheet'].dropna())
    support = {k: v.copy() for k, v in (workbook.split_info or {}).items()}
    for name, column in (('Total outputs', 'Sector'), ('Trades', 'Sector_from')):
        support[name] = support[name].loc[support[name][column].isin(sectors)].copy()
    return replace(workbook, master_sheet=master,
                   inventories_by_sheet={k: v for k, v in workbook.inventories_by_sheet.items() if k in names},
                   split_info=support, intermediate_steps=None)


def _expanded(value, mapping, trail=()):
    if not isinstance(value, str) or value not in mapping:
        return value
    if value in trail:
        raise ValueError(f'Cyclic cluster: {value}')
    members = []
    for item in mapping[value]:
        expanded = _expanded(item, mapping, (*trail, value))
        members.extend(expanded if isinstance(expanded, tuple) else (expanded,))
    return tuple(sorted(set(members)))


def _sorted(frame):
    frame = frame.reset_index(drop=True).copy()
    frame = frame.astype(object).where(frame.notna(), None)
    # Sort by stable representations, retaining numerical values for comparison.
    order = sorted(range(len(frame)), key=lambda i: repr(tuple(frame.iloc[i].fillna('<NA>'))))
    return frame.iloc[order].reset_index(drop=True)


def assert_step_equivalent(actual, expected):
    """Compare model inputs, resolving renamed sheet/cluster aliases.

    Human input labels and sheet names are not numerical constraints. All
    quantities, units, coordinates, modes and split support tables are checked.
    """
    def equal(a, b):
        pd.testing.assert_frame_equal(_sorted(a), _sorted(b), check_dtype=False,
                                      check_exact=False, rtol=1e-12, atol=1e-14)

    equal(actual.master_sheet.drop(columns='Inventory sheet'), expected.master_sheet.drop(columns='Inventory sheet'))
    def profiles(workbook):
        result = {}
        for row in workbook.master_sheet.to_dict('records'):
            frame = workbook.inventories_by_sheet[row['Inventory sheet']].copy()
            for kind, mapping in (('Sector', workbook.item_clusters),
                                  ('Factor of production', workbook.factors_clusters)):
                mask = frame['Item type'].eq(kind)
                frame.loc[mask, 'DB Item'] = frame.loc[mask, 'DB Item'].map(
                    lambda v: _expanded(v, mapping))
            frame['DB Region'] = frame['DB Region'].map(lambda v: _expanded(v, workbook.regions_clusters))
            result[(row['Region'], row['Sector'])] = frame.drop(columns=['Input'], errors='ignore')
        return result
    left, right = profiles(actual), profiles(expected)
    if left.keys() != right.keys():
        raise ValueError('Compiled inventory coordinate coverage changed.')
    for target in left:
        try:
            equal(left[target], right[target])
        except AssertionError as exc:
            raise ValueError(f'Compiled inventory changed for {target}.') from exc
    if (actual.split_info or {}).keys() != (expected.split_info or {}).keys():
        raise ValueError('Split support tables changed.')
    for name in (actual.split_info or {}):
        equal(actual.split_info[name].drop_duplicates(), expected.split_info[name].drop_duplicates())
    if actual.uncertainty_values != expected.uncertainty_values:
        raise ValueError('Inventory uncertainty settings changed.')


def assemble_inventory_history(stages, destination):
    """Write all completed children and the executed plan; verify every stage.

    This is an assembled input reference, not proof of a new optimisation or
    numeric replay. The exact stage workbooks remain authoritative run inputs.
    """
    from mario.ops.add_sector_workbook import load_add_sector_workbook_input, merge_add_sector_workbooks
    from mario.ops.add_sector_steps import compile_step, validate_plan, write_workbook_payload

    def read(path):
        return load_add_sector_workbook_input(path, table='IOT', read_inventories=True, split=True)[0]

    if not stages:
        raise ValueError('No accepted stages to assemble.')
    payloads, originals, plan, completed, sources = [], [], {}, [], []
    initial_existing = None
    for i, stage in enumerate(stages, 1):
        state, sectors = stage.state, stage.state['step_sectors']
        if set(completed) & set(sectors):
            raise ValueError('Executed sector appears in multiple stages.')
        completed += sectors
        if completed != state['completed_sectors']:
            raise ValueError('Incomplete or unordered checkpoint history.')
        database = stage.checkpoint/state.get('database_directory', 'database')
        x = pd.read_parquet(database/'flows/X.parquet')
        existing = set(x.index.get_level_values(-1)) - set(sectors)
        if initial_existing is None:
            initial_existing = existing
        if existing != initial_existing | (set(completed) - set(sectors)):
            raise ValueError('Stage sector universe does not match its history.')
        source = read(stage.source)
        payloads.append(_select(source, sectors))
        originals.append((read(stage.applied), existing))
        name = state['step_name']
        if name in plan:
            name = f'{i}: {name}'
        plan[name] = sectors
        sources.append(dict(step=name, sectors=sectors,
                            source=dict(path=str(stage.source), sha256=_digest(stage.source)),
                            applied=dict(path=str(stage.applied), sha256=_digest(stage.applied))))
    pending = set(source.master_sheet.Sector) - set(completed)
    if pending:
        payloads.append(_select(source, pending))
        for name, group in (source.intermediate_steps or {}).items():
            group = [s for s in group if s in pending]
            if group:
                if name in plan:
                    name = f'Pending: {name}'
                plan[name] = group
        if set(s for group in plan.values() for s in group) != set(completed) | pending:
            raise ValueError('Pending source sectors need an explicit step plan.')
    merged = merge_add_sector_workbooks(payloads)
    support = {k: v.drop_duplicates().reset_index(drop=True) for k, v in merged.split_info.items()}
    merged = replace(merged, split_info=support, intermediate_steps=plan)
    _, parents = validate_plan(merged, initial_existing)
    for stage, payload, (expected, existing) in zip(stages, payloads, originals):
        # Preserve finer supplier observations used by deferred refinement too,
        # not merely the projected constraints of the first step.
        assert_step_equivalent(_select(merged, stage.state['step_sectors']), payload)
        actual = compile_step(merged, stage.state['step_sectors'], existing, parents)
        assert_step_equivalent(actual, expected)
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError(destination)
    write_workbook_payload(merged, destination)
    # Round-trip through the same parser MARIO uses, with no solver invocation.
    restored = read(destination)
    validate_plan(restored, initial_existing)
    for stage, (expected, existing) in zip(stages, originals):
        assert_step_equivalent(compile_step(restored, stage.state['step_sectors'], existing, parents), expected)
    for record in sources:
        for role in ('source', 'applied'):
            if _digest(record[role]['path']) != record[role]['sha256']:
                raise ValueError('A source workbook changed during assembly.')
    return dict(format='entice-cumulative-inventories-v1', completed_sectors=completed,
                planned_sectors=list(dict.fromkeys(merged.master_sheet.Sector)),
                regions=sorted(merged.master_sheet.Region.unique()), profiles=len(merged.master_sheet),
                output_targets=len(support['Total outputs']), trade_targets=len(support['Trades']),
                plan=plan, stages=sources, sha256=_digest(destination),
                sha256_scope='Workbook bytes immediately after assembly/read-back verification; Office container metadata updates can change the byte hash.',
                verification='Each stage recompiles to equivalent saved inputs; no optimisation was run.',
                limitation='Assembled reference; use original stage workbooks and historical code for an exact run replay.')
