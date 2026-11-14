#!/usr/bin/env python3
"""Pinned regression suite for job_store.make_job_id.

WHY THIS EXISTS: on 2026-09-22 make_job_id blanket-stripped the query string.
An Indeed job URL is https://ie.indeed.com/viewjob?jk=<id>, so EVERY Indeed job
ever sourced hashed to the same id and collapsed into one database row (one row
had absorbed 894 distinct postings). `--jd <id>` then returned the wrong JD, so
a resume could be tailored against a different company's job description.

A store that silently merges rows is more dangerous than one that errors, which
is the same lesson as the sponsor_check regression. Run `make store-test` after
ANY change to make_job_id. Never loosen a case to make the suite pass.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from job_store import make_job_id as mid

DISTINCT = [
    ("Indeed: two different jobs must not collide",
     "https://ie.indeed.com/viewjob?jk=83ce030be94c4829",
     "https://ie.indeed.com/viewjob?jk=127b5cc5b1863c5c"),
    ("LinkedIn: different job ids in the path",
     "https://www.linkedin.com/jobs/view/4420709478",
     "https://www.linkedin.com/jobs/view/4452718067"),
    ("Workday: different req numbers",
     "https://acme.wd5.myworkdayjobs.com/2/job/Dublin--Ireland/Ref-Data_26994894",
     "https://acme.wd5.myworkdayjobs.com/2/job/Dublin--Ireland/Ref-Data_26994918"),
    ("Greenhouse: gh_jid is the identity and lives in the query string",
     "https://eosits.com/company/careers/?gh_jid=8537662002",
     "https://eosits.com/company/careers/?gh_jid=8537662003"),
    ("No URL: fall back to company+title+location",
     None, None),
]

SAME = [
    ("Indeed: same job, different tracking noise",
     "https://ie.indeed.com/viewjob?jk=83ce030be94c4829&from=serp&vjk=abc",
     "https://ie.indeed.com/viewjob?jk=83ce030be94c4829&tk=xyz&utm_source=linkedin"),
    ("LinkedIn: same job, tracking query stripped",
     "https://www.linkedin.com/jobs/view/4420709478?refId=abc&trackingId=def",
     "https://www.linkedin.com/jobs/view/4420709478"),
    ("Trailing slash and case are not identity",
     "https://ie.indeed.com/viewjob?jk=83CE030BE94C4829",
     "https://ie.indeed.com/viewjob?jk=83ce030be94c4829"),
    ("Param order is not identity",
     "https://example.com/job?b=2&a=1",
     "https://example.com/job?a=1&b=2"),
    ("AECOM: ?vs= is tracking, not identity",
     "https://aecom.jobs/dublin-irl/digital-data-analyst/C149/job/?vs=1606",
     "https://aecom.jobs/dublin-irl/digital-data-analyst/C149/job/"),
]

def main():
    failed = 0
    print("job_store.make_job_id regression suite")
    print("=" * 66)
    print("\nMUST BE DISTINCT (different jobs -> different ids)")
    for name, a, b in DISTINCT:
        if a is None:
            ia = mid(None, "Davy", "Business Analyst", "Dublin")
            ib = mid(None, "Fenergo", "Business Analyst", "Dublin")
        else:
            ia, ib = mid(a, "", "", ""), mid(b, "", "", "")
        ok = ia != ib
        failed += not ok
        print(f"  {'PASS' if ok else '*** FAIL'}  {name}")
        if not ok:
            print(f"          both hashed to {ia}")

    print("\nMUST BE IDENTICAL (same job -> same id)")
    for name, a, b in SAME:
        ia, ib = mid(a, "", "", ""), mid(b, "", "", "")
        ok = ia == ib
        failed += not ok
        print(f"  {'PASS' if ok else '*** FAIL'}  {name}")
        if not ok:
            print(f"          {ia} != {ib}")

    print("=" * 66)
    if failed:
        print(f"{failed} FAILURE(S). Do not ship. Do not loosen a case to make this pass.")
        return 1
    print("All cases pass.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
