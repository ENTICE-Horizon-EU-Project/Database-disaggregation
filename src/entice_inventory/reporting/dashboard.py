"""Standalone HTML reports from monetary IOT results and explicit references."""
from pathlib import Path
from importlib.resources import files
import base64
import html
import json
import pandas as pd
from entice_inventory.analysis.flows import FD_GROUPS, final_demand_mapping, use_profile, trade_matrix
from entice_inventory.analysis.labels import sector_labels

def write_dashboard(database, output, *, checks=None, references=None, labels=None,
                    title="Sector disaggregation results", subtitle=None):
    """One offline HTML report; product selector updates the three result views."""
    from plotly.offline import get_plotlyjs
    labels = sector_labels() if labels is None else labels
    if checks is None:
        checks = pd.DataFrame(columns=['product','origin','kind','target','passed','absolute_error'])
    if references is None:
        references = {'rows': [], 'sources': [], 'input_groups': [], 'currency': {}}
    subtitle = subtitle or f"{len(database.get_index('Region'))} regions · {len(database.get_index('Sector'))} sectors"

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    products = list(database.get_index("Sector"))
    regions = list(database.get_index("Region"))
    payload = {}
    for product in products:
        profile = use_profile(database, product)
        shares, uses, total = profile.shares.T, profile.amounts.T, profile.totals
        x = database.X.iloc[:, 0]
        mask = x.index.get_level_values(-1) == product
        production = x.loc[mask].groupby(level="Region").sum().reindex(regions)
        subset = checks.loc[checks["product"] == product]
        targets = subset.loc[subset["kind"] == "Output"].set_index("origin")["target"]
        payload[product] = {
            "name": labels.get(product, product), "output": production.tolist(),
            "output_target": [float(targets.loc[r]) if r in targets.index else None for r in regions],
            "shares": shares.astype(object).where(shares.notna(), None).values.tolist(),
            "uses": uses.astype(object).where(uses.notna(), None).values.tolist(),
            "totals": total.tolist(), "trade": trade_matrix(database, product).values.tolist(),
            "checks": {"count": len(subset), "passed": int(subset.passed.sum()),
                       "max_error": float(subset.absolute_error.max()) if len(subset) else None},
        }
    fd = final_demand_mapping(database)
    missing = fd.loc[~fd["Included in denominator"] & fd.Use.isin(FD_GROUPS), "Use"].tolist()
    data = json.dumps(dict(products=products, regions=regions, uses=shares.columns.tolist(),
                           use_names=[labels.get(item, item) for item in shares.columns],
                           payload=payload, missing=missing, references=references), allow_nan=False).replace("</", "<\\/")
    resource = files(__package__)
    page = resource.joinpath('templates/dashboard.html').read_text()
    panel = resource.joinpath('templates/comparisons.html').read_text().replace('__REFERENCE_YEAR__', html.escape(str(references.get('year', ''))))
    script = resource.joinpath('templates/comparisons.js').read_text()
    replacements = {'__PLOTLY__': get_plotlyjs(), '__TITLE__': html.escape(title),
                    '__SUBTITLE__': html.escape(subtitle), '__REFERENCE_PANEL__': panel,
                    '__REFERENCE_SCRIPT__': script, '__DATA__': data}
    for token, name, mime in [('__ENTICE_LOGO__', 'entice.svg', 'image/svg+xml'),
                              ('__MARIO_LOGO__', 'mario-logo.png', 'image/png')]:
        replacements[token] = 'data:' + mime + ';base64,' + base64.b64encode(resource.joinpath('assets', name).read_bytes()).decode('ascii')
    for token, value in replacements.items():
        page = page.replace(token, value)
    if not references['rows']:
        page = page.replace('id="show-references"', 'id="show-references" hidden')
    output.write_text(page)
    return output
