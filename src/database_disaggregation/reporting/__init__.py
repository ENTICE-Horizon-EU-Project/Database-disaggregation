"""Optional standalone reporting; source browsing needs no model database."""
__all__ = ['write_dashboard', 'write_source_dashboard', 'SourceCollection']


def __getattr__(name):
    from importlib import import_module
    modules = {'write_dashboard': '.dashboard', 'write_source_dashboard': '.source_dashboard',
               'SourceCollection': '.collection'}
    if name not in modules:
        raise AttributeError(name)
    value = getattr(import_module(modules[name], __name__), name)
    globals()[name] = value
    return value
