"""Declared-but-not-built ATS platforms.

Every name here is part of the target 165-source universe and is kept in the
registry, but no adapter module exists yet. registry.get() returns a subclass
whose fetch() raises NotImplementedError until someone builds adapters/<name>.py.
Seeded from the knit/freehire ATS lists; extend freely.
"""

# Platforms we have NOT built yet (the long tail). Real Tier-1 adapters
# (greenhouse, lever, ashby, smartrecruiters, workable, recruitee, teamtailor,
# personio, workday) are NOT in this list.
STUB_PLATFORMS = [
    "oracle", "oracle_taleo", "icims", "ukg", "successfactors", "bamboohr",
    "jazzhr", "breezy", "jobvite", "jobadder", "dayforce", "vincere",
    "zoho_recruit", "adp_workforcenow", "bullhorn", "keka", "darwinbox",
    "sage_ats", "recruiterflow", "recruit_crm", "hibob", "personio_de",
    "pinpoint", "loxo", "peoplestrong", "hr_works", "jobdiva", "ceipal",
    "eploy", "fountain", "workday_cxs_legacy", "icims_v2", "paylocity",
    "paycom", "cornerstone", "brassring", "taleo", "avature", "phenom",
    "eightfold", "beamery", "gem", "rippling", "deel", "factorial",
    "smartrecruiters_sandbox", "jobscore", "comeet", "homerun", "trakstar",
]


def make_stub(platform: str):
    """Return a concrete Adapter subclass for an unbuilt platform."""
    from ..base import Adapter

    class _Stub(Adapter):
        PLATFORM = platform

        def fetch(self, board_token):
            raise NotImplementedError(
                f"adapter '{platform}' declared but not built; "
                f"implement scripts/ats_harvest/adapters/{platform}.py"
            )

    _Stub.__name__ = f"Stub_{platform}"
    return _Stub
