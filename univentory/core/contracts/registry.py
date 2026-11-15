"""Resolve contract adapters through configuration (Section 16).

Owners replace a labelled test adapter with the real implementation by
changing ``UNIVENTORY_CONTRACT_ADAPTERS``; no consumer code changes.
"""
from functools import lru_cache

from django.conf import settings
from django.utils.module_loading import import_string


@lru_cache(maxsize=None)
def _load(path: str):
    return import_string(path)()


def get_adapter(name: str):
    return _load(settings.UNIVENTORY_CONTRACT_ADAPTERS[name])


def reset_adapters() -> None:
    _load.cache_clear()
