"""Standalone HTML reports from monetary IOT results and explicit references."""
from pathlib import Path
from importlib.resources import files
import base64
import html
import json
import pandas as pd
from database_disaggregation.analysis.flows import FD_GROUPS, final_demand_mapping, use_profile, trade_matrix, cost_profile
from database_disaggregation.analysis.labels import sector_labels, region_labels

def _sector_types(products, workbook, labels):
    """Classify the current sectors from explicit add/split workbook metadata."""
    if workbook is None:
        return {product: None for product in products}
    master = pd.read_excel(workbook, sheet_name='Master',
                           usecols=['Sector', 'Parent Sector', 'Add or Split'])[
                               ['Sector', 'Parent Sector', 'Add or Split']].drop_duplicates()
    parents, residuals = {}, set()
    for sector, parent, action in master.itertuples(index=False, name=None):
        if pd.isna(sector) or sector not in products:
            continue
        action = str(action).strip().casefold()
        if action not in {'add', 'split'}:
            raise ValueError(f'Unknown Add or Split value for {sector}: {action}')
        if action == 'split' and pd.isna(parent):
            raise ValueError(f'Split sector {sector} requires a Parent Sector.')
        parents.setdefault(sector, set())
        if pd.notna(parent):
            parents[sector].add(parent)
            if action == 'split':
                residuals.add(parent)
    labels_by_kind = {'new': 'New sector', 'residual_parent': 'Residual parent',
                      'original': 'Original sector'}
    result = {}
    for product in products:
        kind = 'residual_parent' if product in residuals else 'new' if product in parents else 'original'
        result[product] = {'kind': kind, 'label': labels_by_kind[kind],
            'parents': [{'code': parent, 'name': labels.get(parent, parent)}
                        for parent in sorted(parents.get(product, ()))]}
    return result


def dashboard_payload(database, *, checks=None, references=None, labels=None, workbook=None, region_names=None,
                      sector_metadata=None, target_profiles=None):
    """One offline HTML report; product selector updates the three result views.

    ``workbook`` is the complete MARIO add/split input workbook for this result.
    It supplies sector status and parent metadata; no classification is guessed
    when the workbook is omitted.
    """
    labels = sector_labels() if labels is None else labels
    if checks is None:
        checks = pd.DataFrame(columns=['product','origin','kind','target','passed','absolute_error'])
    if references is None:
        references = {'rows': [], 'sources': [], 'input_groups': [], 'currency': {}}
    products = list(database.get_index("Sector"))
    regions = list(database.get_index("Region"))
    if region_names is not None and set(regions) - set(region_names):
        raise ValueError('Region names must cover the exact saved regions.')
    names = region_labels() if region_names is None else region_names
    sector_types = _sector_types(products, workbook, labels) if sector_metadata is None else sector_metadata
    if set(sector_types) != set(products):
        raise ValueError('Explicit sector metadata must cover the exact saved sectors.')
    target_profiles = target_profiles or {}
    payload = {}
    cost_items = []
    for product in products:
        profile = use_profile(database, product)
        shares, uses, total = profile.shares.T, profile.amounts.T, profile.totals
        x = database.X.iloc[:, 0]
        mask = x.index.get_level_values(-1) == product
        production = x.loc[mask].groupby(level="Region").sum().reindex(regions)
        subset = checks.loc[checks["product"] == product]
        targets = subset.loc[subset["kind"] == "Output"].set_index("origin")["target"]
        recorded = target_profiles.get(product, {})
        archived_targets = recorded.get('output_targets', {})
        verified = recorded.get('constraints_verified', False)
        cost = cost_profile(database, product) if getattr(database, 'V', None) is not None else None
        if cost is not None:
            cost_items = cost.shares.index.tolist()
        def numeric(frame):
            return frame.astype(object).where(frame.notna(), None).values.tolist()
        trade_targets = recorded.get('trade_targets', {}) if verified else {}
        trade_cells = recorded.get('trade_cells', {}) if verified else {}
        payload[product] = {
            "name": labels.get(product, product), "sector_type": sector_types[product],
            "output": production.tolist(),
            "output_target": [archived_targets[r] if verified and r in archived_targets else
                              float(targets.loc[r]) if r in targets.index else archived_targets.get(r) for r in regions],
            "output_reference_kind": 'Constraint' if verified else 'Prepared reference',
            "output_cells": [recorded.get('output_cells', {}).get(r) for r in regions],
            "input_provenance": {key: recorded[key] for key in ('step', 'step_index', 'input_href', 'input_sha256', 'archive_member') if key in recorded},
            "trade_constraint": [[trade_targets.get(origin, {}).get(destination) for destination in regions] for origin in regions],
            "trade_cells": [[trade_cells.get(origin, {}).get(destination) for destination in regions] for origin in regions],
            "trade_delta": recorded.get('trade_delta', 0.),
            "cost_shares": numeric(cost.shares.T) if cost is not None else None,
            "cost_amounts": numeric(cost.amounts.T) if cost is not None else None,
            "cost_totals": cost.totals.tolist() if cost is not None else None,
            "shares": shares.astype(object).where(shares.notna(), None).values.tolist(),
            "uses": uses.astype(object).where(uses.notna(), None).values.tolist(),
            "totals": total.tolist(), "trade": trade_matrix(database, product).values.tolist(),
            "checks": {key: recorded.get(key) for key in ('count','passed','max_error')} if recorded else {"count": len(subset), "passed": int(subset.passed.sum()),
                       "max_error": float(subset.absolute_error.max()) if len(subset) else None},
        }
    fd = final_demand_mapping(database)
    missing = fd.loc[~fd["Included in denominator"] & fd.Use.isin(FD_GROUPS), "Use"].tolist()
    return dict(format='entice-workshop-dashboard-v1', products=products, regions=regions,
                region_names={region: names.get(region, region) for region in regions},
                uses=shares.columns.tolist(),use_names=[labels.get(item,item) for item in shares.columns],
                cost_items=cost_items,cost_names=[labels.get(item,item) for item in cost_items],
                payload=payload,missing=missing,references=references)


def write_dashboard(database, output, *, checks=None, references=None, labels=None, workbook=None, region_names=None,
                    title="Sector disaggregation results", subtitle=None, benchmark=None):
    """Write the offline dashboard from a MARIO database or saved checkpoint.

    A checkpoint path uses the existing validated loader, preserving saved
    independent production and restoring computational sector identifiers.
    ``benchmark`` must describe the same run; its checks and comparisons are
    reused without rerunning preparation, disaggregation or external parsers.
    """
    if isinstance(database, (str, Path)):
        from database_disaggregation.core.residual_labels import load_checkpoint_with_codes
        database = load_checkpoint_with_codes(database)
    from .render import render_dashboard
    audit_stem="benchmarking"
    if benchmark is not None:
        from .saved import benchmark_context
        if isinstance(benchmark,(str,Path)):
            report_path=Path(benchmark).resolve()
            audit_stem=report_path.with_suffix('').as_uri()
            benchmark=json.loads(report_path.read_text())
        context=benchmark_context(benchmark)
        if set(database.get_index('Region'))!=set(benchmark['dimensions']['regions']):
            raise ValueError('Saved benchmark regions differ from the current database.')
        if set(database.get_index('Sector'))!={row['sector'] for row in benchmark['sectors']}:
            raise ValueError('Saved benchmark sectors differ from the current database.')
        actual=database.X.iloc[:,0].copy()
        actual.index=pd.MultiIndex.from_arrays([actual.index.get_level_values('Region'),
            actual.index.get_level_values(-1)],names=['region','sector'])
        expected=pd.DataFrame(benchmark['sectors']).set_index(['region','sector'])['output']
        if not actual.sort_index().equals(expected.reindex(actual.index).sort_index()):
            raise ValueError('Saved benchmark outputs differ from the current database.')
        payload=dashboard_payload(database,**context)
    else:
        payload=dashboard_payload(database,checks=checks,references=references,labels=labels,workbook=workbook,region_names=region_names)
    subtitle=subtitle or f"{len(payload['regions'])} regions · {len(payload['products'])} sectors"
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(render_dashboard(payload,title=title,subtitle=subtitle,benchmark=benchmark,audit_stem=audit_stem))
    return output
