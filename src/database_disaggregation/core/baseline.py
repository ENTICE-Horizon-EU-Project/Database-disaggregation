"""Select a native MARIO reader without changing parsing or accounting rules."""
from pathlib import Path

from database_disaggregation.core.paths import data_path, local_config


def load_baseline(path=None, input_format=None, *, geography=None):
    import mario

    path = Path(path) if path is not None else data_path('baseline', required=True)
    input_format = input_format or local_config().get('baseline_format', 'mario_parquet')
    if geography is not None and input_format == 'mario_parquet':
        from database_disaggregation.core.geography import load_regional_baseline
        return load_regional_baseline(path, geography)
    if input_format == 'mario_parquet':
        return mario.parse_from_parquet(str(path), table='IOT', mode='flows')
    if input_format in {'gtap_csv', 'gtap_gdx'}:
        if path.suffix.lower() == '.zip':
            raise ValueError('Extract the original GTAP bundle first and select its directory.')
        db = mario.parse_gtap(str(path), table='IOT', variant='power',
                             layout='MRIO', input_format=input_format.removeprefix('gtap_'), year=2023)
        if geography is not None:
            geography.validate(db.get_index('Region'))
            db.aggregate(None, levels='Region', region_aggregation=geography.mapping,
                         zero_output_epsilon=None)
        return db
    raise ValueError('baseline_format must be mario_parquet, gtap_csv or gtap_gdx')
