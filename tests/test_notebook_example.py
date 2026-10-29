"""The public workshop notebook must retain its deliberately small code cells."""
from pathlib import Path
import json

NOTEBOOK = Path(__file__).resolve().parents[1] / 'examples/disaggregation.ipynb'


def test_example_has_two_code_lines_per_cell_without_synthetic_table_construction():
    notebook = json.loads(NOTEBOOK.read_text())
    for cell in notebook['cells']:
        if cell['cell_type'] != 'code':
            continue
        source = ''.join(cell['source'])
        assert len(source.splitlines()) <= 2
        assert 'MultiIndex' not in source and 'pd.DataFrame' not in source
        assert cell['execution_count'] is None and cell['outputs'] == []


def test_default_example_keeps_expensive_preparation_and_solves_commented():
    notebook = json.loads(NOTEBOOK.read_text())
    phases = ('prepare_inputs(', 'build_model(', 'solve_model(', 'assemble_database(', 'export_database(')
    for phase in phases:
        cells = [''.join(c['source']) for c in notebook['cells'] if c['cell_type'] == 'code'
                 and phase in ''.join(c['source'])]
        assert cells, phase
        assert all(all(line.lstrip().startswith('#') for line in code.splitlines()) for code in cells)
