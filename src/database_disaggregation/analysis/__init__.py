"""Read-only analysis; optional plotting/reference modules load on demand."""
from importlib import import_module
__all__ = ['UseProfile', 'use_profile', 'cost_profile', 'trade_matrix', 'check_targets',
           'final_demand_mapping', 'plot_use_profile', 'sector_labels', 'ReferenceSet']
def __getattr__(name):
    modules = {**{n:'.flows' for n in ('UseProfile','use_profile','cost_profile','trade_matrix','check_targets','final_demand_mapping')},
               'plot_use_profile':'.plots','sector_labels':'.labels','ReferenceSet':'.references'}
    if name not in modules: raise AttributeError(name)
    value=getattr(import_module(modules[name],__name__),name);globals()[name]=value;return value
