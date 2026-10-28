"""ENTICE inventory preparation, disaggregation and monetary IOT analysis.

Workflow APIs load lazily. MARIO remains the database/split engine; optional
analysis and reporting modules do not configure environments or start runs.
"""

from entice_inventory.core.paths import DATA_DIR, PROJECT_ROOT

__all__ = ['DATA_DIR', 'PROJECT_ROOT', 'Geography', 'SplitPlan', 'prepare_inputs']


def __getattr__(name):
    """Expose workflow APIs without importing MARIO or optional analysis at startup."""
    from importlib import import_module
    exports = {
        'Geography': ('entice_inventory.core.geography', 'Geography'),
        'SplitPlan': ('entice_inventory.inputs', 'SplitPlan'),
        'prepare_inputs': ('entice_inventory.core.disaggregation', 'prepare_inputs'),
    }
    if name not in exports:
        raise AttributeError(name)
    module, attribute = exports[name]
    value = getattr(import_module(module), attribute)
    globals()[name] = value
    return value
