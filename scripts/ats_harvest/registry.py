"""Lazy adapter registry.

All platforms are declared here (real + stub) but a real adapter module is
imported only when registry.get() is called for it — so none of the ~60 adapter
modules load at import time.
"""
import importlib
from typing import Type

from .base import Adapter
from .adapters import _stubs

# platform -> "module:Class" for built adapters.
REGISTRY = {
    "greenhouse": "ats_harvest.adapters.greenhouse:Greenhouse",
    "lever": "ats_harvest.adapters.lever:Lever",
    "ashby": "ats_harvest.adapters.ashby:Ashby",
    "smartrecruiters": "ats_harvest.adapters.smartrecruiters:SmartRecruiters",
    "workable": "ats_harvest.adapters.workable:Workable",
    "recruitee": "ats_harvest.adapters.recruitee:Recruitee",
    "teamtailor": "ats_harvest.adapters.teamtailor:Teamtailor",
    "personio": "ats_harvest.adapters.personio:Personio",
    "workday": "ats_harvest.adapters.workday:Workday",
    "oraclecx": "ats_harvest.adapters.oraclecx:OracleCX",
}

# Stub platforms (declared, not built) resolve to a generated NotImplemented class.
for _p in _stubs.STUB_PLATFORMS:
    REGISTRY.setdefault(_p, "STUB")


def platforms() -> list:
    """All declared platform names (real + stub)."""
    return sorted(REGISTRY)


def real_platforms() -> list:
    """Only the platforms with a built adapter."""
    return sorted(p for p, v in REGISTRY.items() if v != "STUB")


def get(platform: str) -> Type[Adapter]:
    """Return the Adapter class for a platform, importing it lazily. Stub platforms
    return a generated class whose fetch() raises NotImplementedError."""
    try:
        target = REGISTRY[platform]
    except KeyError:
        raise KeyError(f"unknown ATS platform '{platform}'")
    if target == "STUB":
        return _stubs.make_stub(platform)
    module_path, cls_name = target.split(":")
    module = importlib.import_module(module_path)
    return getattr(module, cls_name)
