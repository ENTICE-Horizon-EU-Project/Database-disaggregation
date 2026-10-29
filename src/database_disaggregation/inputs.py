"""Read the sector list and named split groups from a MARIO input workbook."""
from dataclasses import dataclass
from pathlib import Path
from openpyxl import load_workbook


@dataclass(frozen=True)
class SplitPlan:
    sectors: tuple[str, ...]
    steps: dict[str, list[str]]

    @classmethod
    def read(cls, path):
        """Read metadata only; MARIO remains responsible for inventory parsing."""
        with Path(path).open('rb') as stream:
            book = load_workbook(stream, read_only=True, data_only=True)
            try:
                if 'Master' not in book:
                    raise ValueError('A MARIO workbook requires the Master sheet.')
                rows = iter(book['Master'].values)
                header = next(rows)
                if 'Sector' not in header:
                    raise ValueError('The Master sheet requires a Sector column.')
                position = header.index('Sector')
                sectors = tuple(dict.fromkeys(row[position] for row in rows
                    if len(row) > position and row[position] is not None))
                if not sectors or any(not isinstance(s, str) or not s.strip() for s in sectors):
                    raise ValueError('Master requires non-empty sector codes.')
                steps = {}
                if 'Intermediate steps' in book:
                    values = list(book['Intermediate steps'].values)
                    if values:
                        for i, name in enumerate(values[0]):
                            members = [r[i] for r in values[1:] if len(r) > i and r[i] is not None]
                            if name is None and not members:
                                continue
                            if not isinstance(name, str) or not name.strip() or name in steps:
                                raise ValueError('Step names must be non-empty and unique.')
                            if not members or any(s not in sectors for s in members):
                                raise ValueError(f'Step {name!r} contains an empty or unknown sector selection.')
                            steps[name] = members
                        flattened = [s for members in steps.values() for s in members]
                        if len(flattened) != len(set(flattened)) or set(flattened) != set(sectors):
                            raise ValueError('Intermediate steps must partition the workbook sectors exactly once.')
            finally:
                book.close()
        return cls(sectors, steps)
