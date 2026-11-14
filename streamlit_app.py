"""Job Search Pipeline - interactive demo.

Runs the same modules the command-line pipeline uses (scripts/), against a
fictional demo candidate in data/ and examples/. Nothing leaves the machine
except the optional liveness check, which fetches the URL you paste.
"""
import contextlib
import io
import os
import re
import sqlite3
import sys
import tempfile

import pandas as pd
import streamlit as st

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import ats_analyzer  # noqa: E402
import check_live  # noqa: E402
import fit_decision  # noqa: E402
import job_store  # noqa: E402
import pipeline_review  # noqa: E402
import verify_claims  # noqa: E402
from candidate import PROFILE  # noqa: E402


def example(name):
    with open(os.path.join(ROOT, "examples", name), encoding="utf-8") as fh:
        return fh.read()


def run_quiet(fn, *args, **kwargs):
    """Call a CLI-style function, returning (result, captured stdout)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        result = fn(*args, **kwargs)
    return result, buf.getvalue()


def as_temp_md(text):
    fh = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8")
    fh.write(text)
    fh.close()
    return fh.name


st.set_page_config(page_title="Job Search Pipeline", page_icon="📊", layout="wide")
st.title("Job Search Pipeline")
st.caption(
    "A local-first pipeline for sourcing, vetting and tailoring job applications. "
    f"Demo candidate: **{PROFILE['name']}** (fictional), {PROFILE['years_experience']} years experience."
)

tab_ats, tab_fit, tab_claims, tab_live, tab_store, tab_funnel = st.tabs(
    ["ATS analyzer", "Fit decision", "Claims gate", "Liveness check", "Job store", "Pipeline review"])

# --- ATS analyzer -------------------------------------------------------------
with tab_ats:
    st.subheader("Score a resume against a job description")
    st.write("Weighted keyword coverage from the JD's own terms, must-have coverage, title match, "
             "and a pre-send lint for em dashes, buzzwords and a missing phone number. Gaps are split "
             "into terms the candidate can honestly add and terms they do not have.")
    c1, c2 = st.columns(2)
    resume = c1.text_area("Resume (Markdown)", example("resume.md"), height=420, key="ats_resume")
    jd = c2.text_area("Job description", example("jd_data_analyst.txt"), height=420, key="ats_jd")
    if st.button("Analyze", type="primary", key="ats_go"):
        path = as_temp_md(resume)
        try:
            res, report = run_quiet(ats_analyzer.analyze, path, jd, None)
        finally:
            os.unlink(path)
        m1, m2, m3 = st.columns(3)
        m1.metric("Composite score", f"{res['composite']:.0f}/100")
        m2.metric("Keyword coverage", f"{res['coverage']:.0f}%")
        m3.metric("Title match", f"{res['title'] * 100:.0f}%")
        if res["blockers"]:
            st.error("Not ready to send: " + "; ".join(res["blockers"]))
        else:
            st.success("Pre-send gate clean")
        if res["earnable"]:
            st.warning("Missing but backed by the claims file, so it can be added: " + ", ".join(res["earnable"][:15]))
        if res["not_true"]:
            st.info("Missing and not in the claims file, so leave it out: " + ", ".join(res["not_true"][:15]))
        with st.expander("Full report"):
            st.code(report)

# --- Fit decision -------------------------------------------------------------
with tab_fit:
    st.subheader("Apply, stretch or skip?")
    st.write("Typed gates (yes/no with confidence) for the things that have killed applications before: "
             "visa wording, the years bar, seniority in the title, a salary hidden in prose, Northern Ireland. "
             "The two judgement scores are yours to set after reading the JD.")
    sample = st.radio("Sample JD", ["Good fit", "Knockout"], horizontal=True)
    jd_fit = st.text_area("Job description",
                          example("jd_data_analyst.txt" if sample == "Good fit" else "jd_knockout.txt"),
                          height=260, key=f"fit_jd_{sample}")
    first_line = jd_fit.strip().splitlines()[0] if jd_fit.strip() else ""
    title = st.text_input("Job title", first_line, key=f"fit_title_{sample}")
    c1, c2 = st.columns(2)
    overlap = c1.slider("Required-skills overlap with the claims file (0-3)", 0, 3, 3)
    domain = c2.slider("Domain match (0-3)", 0, 3, 2)
    out = fit_decision.evaluate(jd_fit, title=title, overlap=overlap, domain=domain)
    colour = {"APPLY_TIER1": "green", "APPLY_TIER2": "blue", "STRETCH": "orange", "SKIP": "red"}.get(out["verdict"], "gray")
    st.markdown(f"### Verdict: :{colour}[{out['verdict']}]  (confidence {out['confidence']:.2f})")
    for b in out["blockers"]:
        st.error(b)
    for w in out["warnings"]:
        st.warning(w)
    gates = [{"gate": d["q"], "result": str(d.get("noul", d.get("score", d.get("choice")))),
              "confidence": d.get("confidence"), "why": d.get("why", "")} for d in out["decisions"]]
    st.dataframe(pd.DataFrame(gates), hide_index=True, width="stretch")

# --- Claims gate --------------------------------------------------------------
with tab_claims:
    st.subheader("Is every claim under Experience backed by evidence?")
    st.write("Each tool named in the Experience section must appear in the claims file at the right tier. "
             "A portfolio-only tool (here dbt and Snowflake) under Experience is flagged as an overclaim.")
    bad = example("resume.md").replace(
        "- Built Power BI dashboards", "- Built dbt models on Snowflake and Power BI dashboards")
    choice = st.radio("Resume", ["Honest version", "Overclaiming version"], horizontal=True)
    text = st.text_area("Resume (Markdown)", example("resume.md") if choice == "Honest version" else bad,
                        height=300, key=f"claims_{choice}")
    if st.button("Run claims gate", type="primary"):
        path = as_temp_md(text)
        try:
            ok, report = run_quiet(verify_claims.verify_resume, path)
        finally:
            os.unlink(path)
        (st.success if ok else st.error)("Passed" if ok else "Blocked: fix the flagged lines before compiling")
        st.code(report)
    with st.expander("Claims file (data/master_experience_claims.json)"):
        st.json(verify_claims.json.load(open(verify_claims.CLAIMS_FILE)))

# --- Liveness -----------------------------------------------------------------
with tab_live:
    st.subheader("Is the role still accepting applications?")
    st.write("A page that renders is not a role that is open. LinkedIn serves closed postings with HTTP 200, "
             "and aggregators or JavaScript-shell ATS pages prove nothing on a 200. The check returns LIVE, "
             "CLOSED or UNVERIFIED and says why.")
    url = st.text_input("Job URL", placeholder="https://boards.greenhouse.io/company/jobs/123")
    if st.button("Check", type="primary") and url:
        with st.spinner("Fetching..."):
            verdict, why = check_live.check(url)
        {"LIVE": st.success, "CLOSED": st.error}.get(verdict, st.warning)(f"{verdict}: {why}")

# --- Job store ----------------------------------------------------------------
with tab_store:
    st.subheader("Deduplicated job store")
    st.write("Every sourced posting lands in one SQLite store, deduplicated on a normalised URL "
             "(tracking parameters stripped, board-specific job ids kept). Demo data below.")
    if not os.path.exists(job_store.DB_PATH):   # fresh clone or hosted demo: build it once
        import subprocess
        subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "seed_demo.py")], check=False)
    if not os.path.exists(job_store.DB_PATH):
        st.info("No demo store yet. Run `python scripts/seed_demo.py`.")
    else:
        conn = sqlite3.connect(job_store.DB_PATH)
        df = pd.read_sql_query(
            "SELECT title, company, location, site, salary, is_contract, first_seen, times_seen, description "
            "FROM jobs ORDER BY first_seen DESC", conn)
        q = st.text_input("Search title, company or description", "")
        contract = st.selectbox("Type", ["All", "Permanent", "Contract"])
        if q:
            pat = re.escape(q)
            df = df[df["title"].str.contains(pat, case=False) | df["company"].str.contains(pat, case=False)
                    | df["description"].str.contains(pat, case=False)]
        if contract != "All":
            df = df[df["is_contract"] == (1 if contract == "Contract" else 0)]
        c1, c2 = st.columns(2)
        c1.metric("Jobs shown", len(df))
        c2.metric("Contract share", f"{100 * df['is_contract'].mean():.0f}%" if len(df) else "n/a")
        st.dataframe(df, hide_index=True, width="stretch")

# --- Pipeline review ----------------------------------------------------------
with tab_funnel:
    st.subheader("Measured from the tracker, not guessed")
    st.write("Raw status strings drift (\"Applied 2026-11-13\", \"applied via recruiter\"...). "
             "They are normalised into a few real states before anything is counted.")
    rows = pipeline_review.load(os.path.join(ROOT, "data", "application_tracker.csv"))
    df = pd.DataFrame(rows)
    counts = df["_state"].value_counts()
    applied = int(sum(counts.get(s, 0) for s in ("APPLIED", "INTERVIEW", "REJECTED", "OFFER")))
    c1, c2, c3 = st.columns(3)
    c1.metric("Applications", applied)
    c2.metric("Interviews", int(counts.get("INTERVIEW", 0)) + int(counts.get("OFFER", 0)))
    c3.metric("Median ATS score", f"{df['_ats'].dropna().median():.0f}" if df["_ats"].notna().any() else "n/a")
    st.bar_chart(counts)
    rej = df[df["_state"] == "REJECTED"]["rejection_reason"].replace("", "not recorded").value_counts()
    if len(rej):
        st.write("Rejection reasons")
        st.bar_chart(rej)
    st.dataframe(df[["date_added", "company", "job_title", "status", "fit_level", "_state", "_ats"]],
                 hide_index=True, width="stretch")
