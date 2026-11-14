#!/usr/bin/env python3
"""Plain-assert tests for jsonld.extract_job_postings. Run: python3 scripts/jsonld_test.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from jsonld import extract_job_postings

# JobPosting nested in an @graph, with HTML in the description and an entity.
GRAPH = """
<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@graph":[
 {"@type":"WebSite","name":"Careers"},
 {"@type":"JobPosting","title":"Data Analyst","hiringOrganization":{"@type":"Organization","name":"Acme"},
  "jobLocation":{"@type":"Place","address":{"@type":"PostalAddress","addressLocality":"Dublin","addressCountry":"IE"}},
  "datePosted":"2026-11-04","validThrough":"2026-11-30","employmentType":"FULL_TIME",
  "url":"https://acme.example/jobs/1","description":"<p>Build <b>dashboards</b> &amp; reports.</p>"}
]}
</script></head><body></body></html>
"""

# Top-level array form, type as a list, no description.
ARRAY = """
<script type="application/ld+json">
[{"@type":["JobPosting"],"title":"ML Engineer","hiringOrganization":"Globex",
  "jobLocation":[{"address":"Cork, Ireland"}],"datePosted":"2026-10-01"}]
</script>
"""

BAD = '<script type="application/ld+json">{not valid json]</script><p>no job here</p>'


def test_graph_and_entities():
    jobs = extract_job_postings(GRAPH)
    assert len(jobs) == 1, jobs
    j = jobs[0]
    assert j["title"] == "Data Analyst"
    assert j["company"] == "Acme"
    assert "Dublin" in j["location"] and "IE" in j["location"]
    assert j["date_posted"] == "2026-11-04"
    # HTML stripped, entity unescaped, whitespace folded
    assert j["description"] == "Build dashboards & reports."


def test_array_and_listtype_and_string_org():
    jobs = extract_job_postings(ARRAY)
    assert len(jobs) == 1
    j = jobs[0]
    assert j["title"] == "ML Engineer" and j["company"] == "Globex"
    assert j["location"] == "Cork, Ireland"
    assert j["description"] is None  # missing stays None, never fabricated


def test_malformed_jsonld_is_skipped():
    assert extract_job_postings(BAD) == []
    assert extract_job_postings("") == []


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for fn in tests:
        try:
            fn(); passed += 1
        except Exception as e:
            failed += 1; print(f"  FAIL {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\njsonld tests: {passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
