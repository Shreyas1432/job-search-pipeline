#!/usr/bin/env python3
"""Plain-assert test suite for the ATS harvester (no pytest — project convention).
Run: python3 scripts/ats_harvest_test.py
Opt-in live test: ATS_LIVE=1 python3 scripts/ats_harvest_test.py
"""
import os
import sys
import json

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # make `ats_harvest` package importable
FIX = os.path.join(HERE, "ats_harvest", "fixtures")


def _fix(name):
    with open(os.path.join(FIX, name)) as f:
        return json.load(f)


# ---------------------------------------------------------------- Task 1
def test_jobposting_defaults():
    from ats_harvest.record import JobPosting
    p = JobPosting(source_platform="greenhouse", company="Acme", board_token="acme",
                   job_id="1", title="Data Analyst", location="Dublin", country="IE",
                   remote=False, posted_date="2026-10-18", updated_date=None,
                   apply_url="https://x/1")
    assert p.jd_text is None and p.raw is None
    assert p.title == "Data Analyst"


def test_parse_date_passthrough_and_none():
    from ats_harvest.base import parse_date
    assert parse_date("2026-10-18T10:00:00Z").startswith("2026-10-18")
    assert parse_date(None) is None
    assert parse_date("") is None
    # epoch ms (Lever) and epoch s both -> ISO
    assert parse_date(1760000000000).startswith("20")
    assert parse_date(1760000000).startswith("20")


def test_parse_workday_date():
    from ats_harvest.base import parse_workday_date
    from datetime import datetime
    now = datetime(2026, 10, 19)
    assert parse_workday_date("Posted Today", now).startswith("2026-10-19")
    assert parse_workday_date("Posted Yesterday", now).startswith("2026-10-18")
    assert parse_workday_date("Posted 5 Days Ago", now).startswith("2026-10-14")
    # 30+ -> treated as 30d ago (not fresh), not invented precise
    assert parse_workday_date("Posted 30+ Days Ago", now).startswith("2026-09-19")
    assert parse_workday_date("garbage", now) is None


def test_concurrent_map_runs_all_in_order():
    from ats_harvest.base import concurrent_map
    assert concurrent_map(lambda x: x * 2, [1, 2, 3, 4], workers=4) == [2, 4, 6, 8]
    assert concurrent_map(lambda x: x, []) == []


def test_registry_lazy_real():
    from ats_harvest import registry
    cls = registry.get("greenhouse")
    assert cls.PLATFORM == "greenhouse"


def test_registry_stub_raises():
    from ats_harvest import registry
    cls = registry.get("icims")  # declared stub, not built
    try:
        cls().fetch("x")
        assert False, "stub should raise"
    except NotImplementedError as e:
        assert "icims" in str(e)


def test_registry_no_import_until_get():
    # importing registry must not import any adapter module
    for m in list(sys.modules):
        if m.startswith("ats_harvest.adapters.greenhouse"):
            del sys.modules[m]
    import importlib
    import ats_harvest.registry as reg
    importlib.reload(reg)
    assert "ats_harvest.adapters.greenhouse" not in sys.modules
    reg.get("greenhouse")
    assert "ats_harvest.adapters.greenhouse" in sys.modules


# ---------------------------------------------------------------- Tasks 2-10 adapters
def _run_json(modname, clsname, fixture, token="acme"):
    import importlib
    mod = importlib.import_module(f"ats_harvest.adapters.{modname}")
    data = _fix(fixture)
    orig = mod.http_json
    mod.http_json = lambda *a, **k: data
    try:
        return getattr(mod, clsname)().fetch(token)
    finally:
        mod.http_json = orig


def _assert_good(posts):
    assert len(posts) == 1, f"expected 1 posting, got {len(posts)}"
    p = posts[0]
    assert p.title and p.apply_url and p.location, "title/url/location must be set"
    assert p.posted_date and p.posted_date.startswith("20"), "real ISO date expected"
    return p


def _assert_nodate(posts):
    assert len(posts) == 1
    assert posts[0].posted_date is None, "missing date must be None, never fabricated"


def test_oraclecx_discover():
    from ats_harvest import registry
    OC = registry.get("oraclecx")
    tok = OC.discover("https://fa-ewnd-saasfaprod1.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_2001/job/561/")
    assert tok == "fa-ewnd-saasfaprod1.fa.ocs.oraclecloud.com|CX_2001", tok
    # non-Oracle host must not match
    assert OC.discover("https://boards.greenhouse.io/acme") is None


def test_oraclecx_parse():
    import importlib
    oc = importlib.import_module("ats_harvest.adapters.oraclecx")
    lst, det = _fix("oraclecx_list.json"), _fix("oraclecx_detail.json")
    orig = oc.http_json
    oc.http_json = lambda url, *a, **k: det if "Details" in url else lst
    try:
        posts = oc.OracleCX().fetch("host.oraclecloud.com|CX_2001")
    finally:
        oc.http_json = orig
    p = _assert_good(posts)
    assert p.job_id == "561" and "job/561/" in p.apply_url, p.apply_url
    assert "Python and SQL" in (p.jd_text or ""), "detail JD must be fetched and joined"


def test_greenhouse_parse(): _assert_good(_run_json("greenhouse", "Greenhouse", "greenhouse.json"))
def test_greenhouse_nodate(): _assert_nodate(_run_json("greenhouse", "Greenhouse", "greenhouse_nodate.json"))
def test_lever_parse(): _assert_good(_run_json("lever", "Lever", "lever.json"))
def test_lever_nodate(): _assert_nodate(_run_json("lever", "Lever", "lever_nodate.json"))
def _run_ashby(jobpage_fixture):
    import ats_harvest.adapters.ashby as ab
    gql = _fix("ashby_graphql.json")
    html = open(os.path.join(FIX, jobpage_fixture)).read()
    oj, ot = ab.http_json, ab.http_text
    ab.http_json = lambda *a, **k: gql
    ab.http_text = lambda *a, **k: html
    try:
        return ab.Ashby().fetch("acme")
    finally:
        ab.http_json, ab.http_text = oj, ot


def test_ashby_parse(): _assert_good(_run_ashby("ashby_jobpage.html"))
def test_ashby_nodate(): _assert_nodate(_run_ashby("ashby_jobpage_nodate.html"))
def test_smartrecruiters_parse(): _assert_good(_run_json("smartrecruiters", "SmartRecruiters", "smartrecruiters.json"))
def test_smartrecruiters_nodate(): _assert_nodate(_run_json("smartrecruiters", "SmartRecruiters", "smartrecruiters_nodate.json"))
def test_workable_parse(): _assert_good(_run_json("workable", "Workable", "workable.json"))
def test_workable_nodate(): _assert_nodate(_run_json("workable", "Workable", "workable_nodate.json"))
def test_recruitee_parse(): _assert_good(_run_json("recruitee", "Recruitee", "recruitee.json"))
def test_recruitee_nodate(): _assert_nodate(_run_json("recruitee", "Recruitee", "recruitee_nodate.json"))


def _run_text(modname, clsname, fixture, token):
    import importlib
    mod = importlib.import_module(f"ats_harvest.adapters.{modname}")
    text = open(os.path.join(FIX, fixture)).read()
    orig = mod.http_text
    mod.http_text = lambda *a, **k: text
    try:
        return getattr(mod, clsname)().fetch(token)
    finally:
        mod.http_text = orig


def test_teamtailor_parse(): _assert_good(_run_text("teamtailor", "Teamtailor", "teamtailor.html", "acme.teamtailor.com"))
def test_teamtailor_nodate(): _assert_nodate(_run_text("teamtailor", "Teamtailor", "teamtailor_nodate.html", "acme.teamtailor.com"))
def test_personio_parse(): _assert_good(_run_text("personio", "Personio", "personio.xml", "acme"))
def test_personio_nodate(): _assert_nodate(_run_text("personio", "Personio", "personio_nodate.xml", "acme"))


def test_workday_parse():
    p = _assert_good(_run_json("workday", "Workday", "workday.json", "aig.wd1.myworkdayjobs.com/External"))
    assert "JR123" in p.job_id or "JR123" in (p.raw or {}).get("bulletFields", [""])[0]


def test_workday_30plus_present_but_old():
    posts = _run_json("workday", "Workday", "workday_nodate.json", "aig.wd1.myworkdayjobs.com/External")
    assert posts[0].posted_date and posts[0].posted_date.startswith("20")  # a floor date, not None


def test_workday_garbage_date_none():
    posts = _run_json("workday", "Workday", "workday_garbage.json", "aig.wd1.myworkdayjobs.com/External")
    assert posts[0].posted_date is None  # unparseable relative text -> None, never invented


def test_discover_greenhouse_url():
    from ats_harvest.adapters.greenhouse import Greenhouse
    assert Greenhouse.discover("https://boards.greenhouse.io/acme") == "acme"


# ---------------------------------------------------------------- Task 11 discovery
def test_detect_url():
    from ats_harvest import discovery
    assert discovery.detect("https://jobs.lever.co/acme") == ("lever", "acme")


def test_detect_from_html_markers():
    from ats_harvest import discovery
    html = '<html><body><a href="https://boards.greenhouse.io/acmecorp/jobs/1">careers</a></body></html>'
    assert discovery.detect("https://acme.com/careers", html=html) == ("greenhouse", "acmecorp")


def test_detect_offdomain_ogurl_not_misattributed():
    from ats_harvest import discovery
    # a board host appears ONLY inside an off-domain og:url (an embedded widget) -> must NOT be attributed
    html = ('<html><head><meta property="og:url" content="https://widget.lever.co/embed">'
            '<meta property="og:url" content="https://jobs.lever.co/someoneelse"></head>'
            '<body>no board on this company page</body></html>')
    plat, tok = discovery.detect("https://acme.com/careers", html=html)
    assert tok != "someoneelse"


def test_detect_unknown_returns_none():
    from ats_harvest import discovery
    assert discovery.detect("https://acme.com", html="<html><body>nothing</body></html>") == (None, None)


# ---------------------------------------------------------------- Task 12 catalog
import tempfile


def _tmpdb():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return path


def test_catalog_upsert_idempotent():
    from ats_harvest import catalog
    db = _tmpdb()
    try:
        catalog.ensure_schema(db)
        catalog.add(db, "Acme", "greenhouse", "acme", market="IE")
        catalog.add(db, "Acme", "greenhouse", "acme", market="IE")  # same key again
        assert len(catalog.list(db)) == 1
    finally:
        os.remove(db)


def test_catalog_list_filter_by_market():
    from ats_harvest import catalog
    db = _tmpdb()
    try:
        catalog.ensure_schema(db)
        catalog.add(db, "A", "lever", "a", market="IE")
        catalog.add(db, "B", "lever", "b", market="IN")
        assert {r["board_token"] for r in catalog.list(db, market="IN")} == {"b"}
    finally:
        os.remove(db)


def test_seed_from_file_uses_discovery(monkeypatch=None):
    from ats_harvest import catalog, discovery
    db = _tmpdb()
    seedf = _tmpdb() + ".csv"
    open(seedf, "w").write("Acme,https://acme.com,IE\nNope,https://nope.com,IE\n")
    orig = discovery.detect
    discovery.detect = lambda d, **k: ("greenhouse", "acme") if "acme" in d else (None, None)
    try:
        catalog.ensure_schema(db)
        added, skipped = catalog.seed_from_file(db, seedf)
        assert added == 1 and skipped == 1
        assert catalog.list(db)[0]["platform"] == "greenhouse"
    finally:
        discovery.detect = orig
        os.remove(db); os.remove(seedf)


# ---------------------------------------------------------------- Task 13 filters
def _post(**kw):
    from ats_harvest.record import JobPosting
    base = dict(source_platform="x", company="c", board_token="t", job_id="1",
                title="Data Analyst", location="Dublin", country="IE", remote=None,
                posted_date=None, updated_date=None, apply_url="u")
    base.update(kw)
    return JobPosting(**base)


def test_in_market_ie_in_remote():
    from ats_harvest import filters
    assert filters.in_market(_post(location="Dublin, Ireland"), ("IE", "IN"))
    assert filters.in_market(_post(location="Hyderabad", country="India"), ("IE", "IN"))
    assert filters.in_market(_post(location="Remote - EU", remote=True), ("IE", "IN"))
    assert not filters.in_market(_post(location="Berlin, Germany", country="Germany"), ("IE", "IN"))


def test_title_match_allow_and_reject():
    from ats_harvest import filters
    assert filters.title_match("Senior Data Engineer")
    assert filters.title_match("Analytics Engineer")
    assert not filters.title_match("Registered Nurse")


def test_is_fresh_true_false_and_none():
    from ats_harvest import filters
    from datetime import datetime, timezone, timedelta
    recent = (datetime.now(timezone.utc) - timedelta(hours=10)).isoformat()
    old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    assert filters.is_fresh(_post(posted_date=recent), 48)
    assert not filters.is_fresh(_post(posted_date=old), 48)
    assert not filters.is_fresh(_post(posted_date=None), 48)  # unknown date is NEVER fresh


# ---------------------------------------------------------------- Task 14 harvest
def _recent_iso(h=5):
    from datetime import datetime, timezone, timedelta
    return (datetime.now(timezone.utc) - timedelta(hours=h)).isoformat()


class _FakeAdapter:
    def __init__(self, posts):
        self._posts = posts

    def fetch(self, token):
        return self._posts


def _harvest_env(platform_posts, failing=()):
    """Return (run_fn, db, index_dir) with registry.get monkeypatched."""
    from ats_harvest import harvest, catalog
    db = _tmpdb()
    catalog.ensure_schema(db)
    for plat in platform_posts:
        catalog.add(db, plat, plat, f"tok_{plat}", market="IE")
    orig = harvest.registry.get

    def fake_get(plat):
        if plat in failing:
            class _Boom:
                def fetch(self, t): raise RuntimeError("board down")
            return _Boom
        posts = platform_posts[plat]
        return lambda: _FakeAdapter(posts)
    harvest.registry.get = fake_get
    return harvest, db, orig


def test_harvest_dedup_same_role_two_boards():
    url = "https://x/same-role"
    p = _post(posted_date=_recent_iso(), apply_url=url)
    harvest, db, orig = _harvest_env({"greenhouse": [p], "lever": [p]})
    import tempfile
    try:
        fresh = harvest.run(db, hours=48, markets=("IE",), index_dir=tempfile.mkdtemp())
        assert len(fresh) == 1, f"dedup failed: {len(fresh)}"
    finally:
        harvest.registry.get = orig; os.remove(db)


def test_harvest_skips_failing_board():
    good = _post(posted_date=_recent_iso(), apply_url="https://x/good")
    harvest, db, orig = _harvest_env({"greenhouse": [good], "lever": [good]}, failing=("lever",))
    import tempfile
    try:
        fresh = harvest.run(db, hours=48, markets=("IE",), index_dir=tempfile.mkdtemp())
        assert any(fp.apply_url == "https://x/good" for fp in fresh)
    finally:
        harvest.registry.get = orig; os.remove(db)


def test_harvest_excludes_dateless_from_fresh():
    dateless = _post(posted_date=None, apply_url="https://x/dateless")
    harvest, db, orig = _harvest_env({"greenhouse": [dateless]})
    import tempfile
    try:
        fresh = harvest.run(db, hours=48, markets=("IE",), index_dir=tempfile.mkdtemp())
        assert all(fp.apply_url != "https://x/dateless" for fp in fresh)
    finally:
        harvest.registry.get = orig; os.remove(db)


# ---------------------------------------------------------------- Task 15 CLI
import subprocess


def test_cli_platforms_smoke():
    r = subprocess.run([sys.executable, os.path.join(HERE, "ats_harvest.py"), "platforms"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "greenhouse" in r.stdout and "workday" in r.stdout


def test_live_greenhouse():  # opt-in: ATS_LIVE=1
    from ats_harvest.adapters.greenhouse import Greenhouse
    posts = Greenhouse().fetch("stripe")
    assert len(posts) > 10
    assert any(p.posted_date for p in posts)


# ---------------------------------------------------------------- EDGE CASES
def test_parse_date_edge_types():
    from ats_harvest.base import parse_date
    assert parse_date(["x"]) is None            # wrong type -> None
    assert parse_date({"a": 1}) is None
    assert parse_date("not a date") is None
    assert parse_date("2026/10/18").startswith("2026-10-18")   # slash format
    assert parse_date(0) is not None or parse_date(0) is None  # epoch 0 doesn't crash


def test_parse_workday_edge():
    from ats_harvest.base import parse_workday_date
    from datetime import datetime
    now = datetime(2026, 10, 19)
    assert parse_workday_date("Posted 1 Day Ago", now).startswith("2026-10-18")  # singular
    assert parse_workday_date("POSTED TODAY", now).startswith("2026-10-19")      # case
    assert parse_workday_date("", now) is None
    assert parse_workday_date(None, now) is None


def test_parse_date_recruitee_utc_format():
    from ats_harvest.base import parse_date
    from ats_harvest import filters
    from datetime import datetime, timezone, timedelta
    # Recruitee real format: "2026-10-05 13:25:03 UTC" must normalize + be usable by is_fresh
    iso = parse_date("2026-10-05 13:25:03 UTC")
    assert iso and "T" in iso
    datetime.fromisoformat(iso.replace("Z", "+00:00"))  # must not raise
    recent = (datetime.now(timezone.utc) - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S UTC")
    assert filters.is_fresh(_post(posted_date=parse_date(recent)), 48) is True


def test_is_fresh_malformed_date_not_crash():
    from ats_harvest import filters
    assert filters.is_fresh(_post(posted_date="garbage"), 48) is False
    assert filters.is_fresh(_post(posted_date="2026-13-45"), 48) is False  # impossible date


def test_in_market_empty_fields():
    from ats_harvest import filters
    assert filters.in_market(_post(location=None, country=None), ("IE", "IN")) is False
    assert filters.in_market(_post(location="", country=""), ("IE", "IN")) is False


def test_title_match_empty():
    from ats_harvest import filters
    assert filters.title_match("") is False
    assert filters.title_match("Chef de Partie") is False


def test_adapter_empty_response_no_crash():
    from ats_harvest.adapters.greenhouse import Greenhouse
    import ats_harvest.adapters.greenhouse as gh
    orig = gh.http_json
    gh.http_json = lambda *a, **k: {}          # no 'jobs' key
    try:
        assert Greenhouse().fetch("acme") == []
    finally:
        gh.http_json = orig


def test_registry_unknown_platform_raises():
    from ats_harvest import registry
    try:
        registry.get("not_a_real_ats")
        assert False
    except KeyError:
        pass


def test_discovery_no_html_no_fetch():
    from ats_harvest import discovery
    assert discovery.detect("https://acme.com", html=None, fetch=False) == (None, None)


def test_workday_pagination_multi_page():
    # total(25) > limit(20): page0 returns 20, page1 (offset 20) returns 5. Must collect 25.
    import ats_harvest.adapters.workday as wd

    def job(i):
        return {"title": f"Data Analyst {i}", "locationsText": "Dublin",
                "postedOn": "Posted Today", "externalPath": f"/{i}", "bulletFields": [str(i)]}

    def fake(url, method="GET", json_body=None, **k):
        off, lim = json_body["offset"], json_body["limit"]
        return {"total": 25, "jobPostings": [job(i) for i in range(off, min(off + lim, 25))]}
    orig = wd.http_json
    wd.http_json = fake
    try:
        posts = wd.Workday().fetch("x.wd1.myworkdayjobs.com/External")
        assert len(posts) == 25, f"pagination collected {len(posts)}"
    finally:
        wd.http_json = orig


def test_smartrecruiters_pagination_respects_offset():
    # total(150) > limit(100): two pages. Must collect 150.
    import ats_harvest.adapters.smartrecruiters as sr

    def fake(url, **k):
        off = int(url.split("offset=")[1].split("&")[0])
        lim = int(url.split("limit=")[1].split("&")[0])
        content = [{"id": str(i), "name": "Data Analyst", "location": {"city": "Dublin"},
                    "releasedDate": "2026-10-18"} for i in range(off, min(off + lim, 150))]
        return {"totalFound": 150, "content": content}
    orig = sr.http_json
    sr.http_json = fake
    try:
        posts = sr.SmartRecruiters().fetch("acme")
        assert len(posts) == 150
    finally:
        sr.http_json = orig


# ---------------------------------------------------------------- runner
def main():
    live = os.environ.get("ATS_LIVE") == "1"
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    if not live:
        tests = [(n, f) for n, f in tests if not n.startswith("test_live_")]
    passed = failed = 0
    for name, fn in tests:
        try:
            fn()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"  FAIL {name}: {type(e).__name__}: {e}")
    print(f"\nATS harvester tests: {passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
