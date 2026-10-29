"""Read-only monetary IOT analysis; computation is separate from rendering."""
from dataclasses import dataclass
from pathlib import Path
import numpy as np
import pandas as pd

FD_GROUPS = {
    "Households": ("hhd", "Households", "Household final consumption expenditure"),
    "Government": ("gov", "Government", "Government final consumption expenditure"),
    "NPISH": ("NPISH", "npish", "Non-profit institutions serving households"),
}

def final_demand_groups(database):
    """Keep familiar consumption groups and include every other native Y category."""
    groups = dict(FD_GROUPS)
    known = {str(a).casefold() for aliases in groups.values() for a in aliases}
    for category in database.Y.columns.get_level_values(-1).unique():
        if str(category).casefold() not in known:
            groups[str(category)] = (str(category),)
    return groups


def final_demand_mapping(database):
    present = list(database.Y.columns.get_level_values(-1).unique())
    records = []
    groups = final_demand_groups(database)
    for label, aliases in groups.items():
        matched = [name for name in present if str(name).casefold() in {a.casefold() for a in aliases}]
        records.append({"Use": label, "Source categories": ", ".join(matched) or "Not separately available",
                        "Included in denominator": bool(matched)})
    for name in present:
        if not any(str(name).casefold() in {a.casefold() for a in aliases} for aliases in groups.values()):
            records.append({"Use": str(name), "Source categories": str(name), "Included in denominator": False})
    return pd.DataFrame(records)

def _selected_uses(database, product, *, final_demand=None, minimum_total=1e-6):
    """Destination x users; all origins; all native final demand by default.

    Missing FD groups stay NaN. Zero/negative total use is undefined, not zero.
    Signed observations are retained; no clipping or redistribution is applied.
    """
    sectors = list(database.get_index("Sector"))
    regions = list(database.get_index("Region"))
    if product not in sectors:
        raise KeyError(product)
    z = database.Z.loc[database.Z.index.get_level_values(-1) == product].sum(axis=0)
    row_region = z.index.get_level_values("Region")
    row_item = z.index.get_level_values(-1)
    z.index = pd.MultiIndex.from_arrays([row_region, row_item], names=["Destination", "Use"])
    uses = z.groupby(level=[0, 1]).sum().unstack("Use").reindex(index=regions, columns=sectors)
    y = database.Y.loc[database.Y.index.get_level_values(-1) == product].sum(axis=0)
    for label, aliases in (final_demand_groups(database) if final_demand is None else final_demand).items():
        selected = y.index.get_level_values(-1).astype(str).str.casefold().isin([a.casefold() for a in aliases])
        name = "FD · " + label
        uses[name] = (y[selected].groupby(level="Region").sum().reindex(regions, fill_value=0)
                      if selected.any() else np.nan)
    total = uses.sum(axis=1, min_count=1)
    shares = uses.div(total.where(total > minimum_total), axis=0) * 100
    valid = total > minimum_total
    np.testing.assert_allclose(shares.loc[valid].sum(axis=1), 100, atol=1e-8, rtol=0)
    return shares, uses, total

def trade_matrix(database, product):
    rows = database.Z.index.get_level_values(-1) == product
    z = database.Z.loc[rows].T.groupby(level="Region").sum().T
    y = database.Y.loc[rows].T.groupby(level="Region").sum().T
    result = z.add(y, fill_value=0)
    result.index = result.index.get_level_values("Region")
    regions = list(database.get_index("Region"))
    return result.groupby(level=0).sum().reindex(index=regions, columns=regions)

def check_targets(database, workbook):
    """Check the prepared observations; these are not independent validation."""
    output = pd.read_excel(workbook, sheet_name="Total outputs")
    trades = pd.read_excel(workbook, sheet_name="Trades")
    output = output.dropna(subset=["Sector", "Region", "Quantity"])
    trades = trades.dropna(subset=["Sector_from", "Region_from", "Region_to", "Quantity"])
    x = database.X.iloc[:, 0]
    x.index = pd.MultiIndex.from_arrays([x.index.get_level_values("Region"), x.index.get_level_values(-1)])
    results = []
    for row in output.to_dict("records"):
        if row["Unit"] != "M USD":
            raise ValueError(f"Unexpected output target unit: {row['Unit']}")
        actual = float(x.loc[(row["Region"], row["Sector"])])
        if not np.isfinite(actual) or not np.isfinite(float(row["Quantity"])):
            raise ValueError('Output observations and results must be finite.')
        results.append(dict(kind="Output", product=row["Sector"], origin=row["Region"], destination="",
                            target=float(row["Quantity"]), actual=actual))
    matrices = {p: trade_matrix(database, p) for p in trades["Sector_from"].unique()}
    for row in trades.to_dict("records"):
        if row["Unit"] != "M USD":
            raise ValueError(f"Unexpected trade target unit: {row['Unit']}")
        actual = float(matrices[row["Sector_from"]].loc[row["Region_from"], row["Region_to"]])
        if not np.isfinite(actual) or not np.isfinite(float(row["Quantity"])):
            raise ValueError('Trade observations and results must be finite.')
        results.append(dict(kind="Trade", product=row["Sector_from"], origin=row["Region_from"],
                            destination=row["Region_to"], target=float(row["Quantity"]), actual=actual))
    frame = pd.DataFrame(results, columns=['kind','product','origin','destination','target','actual'])
    frame["absolute_error"] = (frame.actual - frame.target).abs()
    frame["passed"] = frame.absolute_error <= 1e-6 + 1e-8 * frame.target.abs()
    return frame

@dataclass(frozen=True)
class UseProfile:
    """Rows are using sectors/final consumers; columns are destinations.

    Amounts retain signed observations. Missing demand groups and nonpositive
    denominators are unavailable, never inferred as zero. Totals cover only
    intermediate use and all final-demand categories (or explicit selected groups).
    """
    product: str
    shares: pd.DataFrame
    amounts: pd.DataFrame
    totals: pd.Series


def use_profile(database, product, *, final_demand=None, minimum_total=1e-6):
    """Combine all supplying origins and normalise selected uses to 100%.

    The default includes every Y category: consumption, investment, stocks,
    margins and other native categories. An explicit mapping can select groups.
    ``minimum_total`` is in database units.
    """
    if not np.isfinite(minimum_total) or minimum_total < 0:
        raise ValueError('minimum_total must be nonnegative.')
    shares, amounts, totals = _selected_uses(database, product,
        final_demand=final_demand, minimum_total=minimum_total)
    return UseProfile(product, shares.T, amounts.T, totals)
