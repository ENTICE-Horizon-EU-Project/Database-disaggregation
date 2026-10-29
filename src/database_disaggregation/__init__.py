"""ENTICE inventory preparation, disaggregation and monetary IOT analysis.

Workflow APIs load lazily. MARIO remains the database/split engine; optional
analysis and reporting modules do not configure environments or start runs.
"""

from database_disaggregation.core.paths import DATA_DIR, PROJECT_ROOT

__all__ = ['DATA_DIR', 'PROJECT_ROOT', 'Geography', 'SplitPlan', 'PreprocessedData', 'prepare_inputs', 'prepare_model_inputs', 'analysis', 'reporting']


def __getattr__(name):
    """Expose workflow APIs without importing MARIO or optional analysis at startup."""
    from importlib import import_module
    if name in ('analysis', 'reporting'):
        value = import_module(f'{__name__}.{name}')
        globals()[name] = value
        return value
    exports = {
        'Geography': ('database_disaggregation.core.geography', 'Geography'),
        'SplitPlan': ('database_disaggregation.inputs', 'SplitPlan'),
        'PreprocessedData': ('database_disaggregation.core.disaggregation', 'PreprocessedData'),
        'prepare_inputs': ('database_disaggregation.core.disaggregation', 'prepare_inputs'),
        'prepare_model_inputs': ('database_disaggregation.reconciliation.model_inputs', 'prepare_model_inputs'),
    }
    if name not in exports:
        raise AttributeError(name)
    module, attribute = exports[name]
    value = getattr(import_module(module), attribute)
    globals()[name] = value
    return value
