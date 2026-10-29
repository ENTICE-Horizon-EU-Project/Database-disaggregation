"""Versioned, auditable preparation of ENTICE output, trade and technology priors."""

def reconcile_inventories(*args, **kwargs):
    from .pipeline import reconcile_inventories as run
    return run(*args, **kwargs)

__all__ = ['reconcile_inventories']
