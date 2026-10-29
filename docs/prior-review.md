# MCU source-prior review

The 49-region MCU review traces the problematic priors back to their source and
exports two explicit coefficient scenarios. It does not run a solver, modify an
add-sectors workbook, alter the baseline, or enable a new preparation policy.
The proposal helper is deliberately separate from ordinary reconciliation.

## What the audit established

- The negative Capital/Labor observations already exist in Purdue `EXIOIOT.csv`.
  MCU uses the EXIOIOT importer; COPCOSTS supplies other copper activities.
- For Brazil, Capital is FIXCAP + OTHRENT and Labor is the sum of three LAB codes.
  Every contributing source component is negative. The importer aggregates these
  codes without changing their signs.
- The original MARIO workbook scales the normalized monetary profile by 0.99
  and adds a 1% residual-sector cluster. This exactly explains its coefficient
  values; the residual padding does not introduce the negative signs.
- Capital/Labor remain unchanged through the resolved D2.4 export and the
  49-region preparation. `VA_fix` and regional aggregation did not create them.
- OTHTAX is an aggregate mapped to Tax/TTM. Their separate values are an
  allocation, not two independent source observations. The aggregate OTHTAX plus
  signed PRODTAX is preserved by the resolved export.

The raw file contains 122 MCU regional profiles. Brazil and Lithuania have
negative Capital/Labor. Among the 49 prepared regions, Brazil is the only
conflict with positive MCU output; Lithuania has zero MCU output. There are
24 active and 25 zero-output regions at the 1 USD output threshold.

The raw CSV's original values and source line numbers are recorded. Its unit,
valuation and interpretation have not been independently certified; normalized
ratios must not be confused with raw monetary levels.

## Input proposals, not optimized database results

The parent proxy is the regional GTAP OXT (Other Mining Extraction) in Brazil.
Both recipes preserve output/trade targets and the child's relative
intermediate-input composition and origins, while changing the common intensity
of Z so that the monetary coefficient profile closes at Z+V=1. They do not keep
the nearly zero source total of V.

| Coefficient profile | V / output | Z / output | Oil + Gas / intermediate inputs |
| --- | ---: | ---: | ---: |
| Current prepared MCU/Brazil prior | approximately 0% | approximately 100% | 95.71% |
| Parent Capital/Labor, retain current child Tax/TTM | 46.8875% | 53.1125% | 95.71% |
| Parent complete V block | 48.0196% | 51.9804% | 95.71% |
| Regional OXT technology reference | 48.0196% | 51.9804% | 0.523% |

These figures describe **input coefficients**. They are not the 71.8% and 0.68%
VA shares of the previous optimized quadratic databases. No new model was solved
in this review. Capital/Labor remain nonnegative, and Tax/TTM retain signed
model domains; neither recipe relaxes factor-domain constraints.

The parent coefficients are a declared imputation, not newly measured
copper-mining factor payments. The minimal recipe preserves the existing
Tax/TTM allocation, including its inference limitations. The full-V recipe
changes that allocation too. Exact before/after quantities and provenance are
provided in the candidate CSV and JSON.

## The problem extends beyond two negative factors

The current Brazil profile has 95.7% of intermediate inputs in Oil/Gas, versus
0.523% in regional OXT. Neither is independently certified as the correct
copper-mining technology. Replacing V while preserving the child Z composition
leaves this concentration untouched.

Eight of 24 active prepared MCU regions have net factor priors below 1% of
output. These regions represent **75.4% of prepared MCU output**. The 1% cutoff
is a review screen, not a proof of an error or an automatic replacement rule.
The raw Chile/Peru profiles also have low net V (about 0.195%) and high Oil/Gas
input concentration (about 77.5% before residual padding), so they should not be
selected as trusted donors merely on the basis of geography or positive signs.

Before enabling a general repair, clarify the EXIOIOT activity scope, source
valuation/normalization and negative factor values with the source provider.
Then explicitly choose any donor and record which rows are observed versus
imputed. A full regional-parent monetary technology can be used as a broad
control, but should not silently replace the child's technology. Future model
weights should distinguish source-supported priors from donor estimates; the
current experiment does not add such a weighting policy.

## Reproduce and locate the review

From this checkout with the reconciliation dependencies installed:

```bash
PYTHONPATH=src python scripts/review_mcu_priors.py \
  --prepared build/scalability/20261021_exiobase49_mcu_01/prepared \
  --output build/prior_review/my_mcu_review
```

Use the original full preparation, containing `reconciled/complete.json`, the
resolved MCU workbook and the baseline. Operational source paths come from
`paths.local.json`/the existing path configuration. Use a fresh output directory.

The published review is below the matching corrected-quadratic inventory run,
relative to the configured `data_root`:

`Inventories/D2.8 inventories/20261021 2044 - 49 regions and 1 sectors/diagnostics/prior-review/`

It contains the explanatory README, JSON with source hashes and raw factor
coordinates, raw 122-region and prepared 49-region CSVs, both exact candidate
coefficient tables, the code, verification record and draft source-review
questions. No message was sent to the provider. All source hashes were checked
again after reading and publication; the earlier inventories/databases and
preparation policy remain unchanged. Seven focused tests cover both the new
recipes and the preceding net-V-preserving experiment.
