# Source data explorer

`write_source_dashboard` makes one local HTML file for browsing the original
files in `Data collection/Final`. It is independent of the solved database,
MARIO, the optimisation model and the notebook. No web service is required.

```python
from pathlib import Path
from entice_inventory.reporting import write_source_dashboard

data_root = Path("/your/local/Data split")
write_source_dashboard(
    data_root / "Data collection/Final",
    "results/ENTICE_data_sources.html",
    database_url="MARIO_workshop_dashboard.html",  # optional link
)
```

Open the HTML in a current browser. Choose a file and sheet, search the displayed
table, or open its original file. Excel column letters and source row numbers
are retained. Long cells show their full content on hover. The interface is in
Italian and uses the ENTICE branding. No supporting files are written.

Excel and CSV tables are embedded, compressed and decoded when selected.
The catalogue also includes other file formats. GDX contents are not decoded;
where a same-named Excel/CSV file exists, a button opens that file's tables.
This pairing does not establish numerical equivalence between the two files.

Values are read literally: no currency, year or unit conversion, reconciliation,
aggregation or formula recalculation takes place. Excel number formats and date
styles are not applied. Cached formula values, when present, are the values saved
by the source workbook. Missing caches remain distinct from zeros and are marked
`ƒx`; “Mostra formule” displays their expressions. Empty cells appear as `—`.
Search normally omits rows containing only formulas without cached values;
turning on formulas includes them. All saved formula cells remain embedded.
Hidden sheets remain selectable and are labelled. File read failures are shown.

The HTML is a snapshot and embeds source tables. Regenerate it after editing
the inputs, and share it under the same conditions as those inputs. The original
file links refer to the creator's local paths and may differ on another machine.

Verification:

```bash
PYTHONPATH=src python -m pytest -q tests/test_source_dashboard.py
node tests/source_dashboard_smoke.cjs /path/to/ENTICE_data_sources.html
```

The JavaScript smoke check exercises loading each file, searches, pagination,
formula selection, binary alternatives and stale asynchronous loads. It tests
the UI logic with a minimal DOM, not a rendered browser layout.
