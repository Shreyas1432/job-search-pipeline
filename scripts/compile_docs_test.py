#!/usr/bin/env python3
"""Pins the per-folder compile rules (make compile-test, part of make checks):
one pdf+docx pair per document, a recompile keeps the send name, and the
length + company-leak guards still refuse. Never loosen a case to pass."""
import glob, os, shutil, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from candidate import file_prefix  # noqa: E402
PREFIX = file_prefix()

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
APP = os.path.join(ROOT, 'applications', '_test_tmp', '2026-01-01_acme_data_analyst')
INDEX = os.path.join(ROOT, 'applications', 'INDEX.csv')
MD = "# Test Person\n\nDublin | +353 1 234 5678\n\n## SUMMARY\n\nHello.\n"


def run(md, *args):
    return subprocess.run([sys.executable, os.path.join(ROOT, 'scripts', 'compile_docs.py'),
                           '--md_file', md, *args], capture_output=True, text=True)


def sends(cover=False):
    return sorted(os.path.basename(f) for f in glob.glob(os.path.join(APP, PREFIX + '*'))
                  if ('_Cover_Letter' in f) == cover)


saved = open(INDEX).read() if os.path.exists(INDEX) else None
os.makedirs(APP, exist_ok=True)
try:
    resume, cover = os.path.join(APP, 'resume.md'), os.path.join(APP, 'cover_letter.md')
    for p in (resume, cover):
        open(p, 'w').write(MD)

    assert run(resume, '--submit-role', 'Data Analyst').returncode == 0
    assert sends() == [PREFIX + 'Data_Analyst.docx', PREFIX + 'Data_Analyst.pdf'], sends()

    run(resume, '--submit-role', 'BI Analyst', '--submit-tag', 'EDW')          # rename replaces, never piles up
    assert sends() == [PREFIX + 'BI_Analyst_EDW.docx', PREFIX + 'BI_Analyst_EDW.pdf'], sends()

    run(resume)                                                                # recompile keeps the name
    assert sends() == [PREFIX + 'BI_Analyst_EDW.docx', PREFIX + 'BI_Analyst_EDW.pdf'], sends()

    run(cover)                                                                 # cover is separate, generic name
    assert sends(cover=True) == [PREFIX + 'Cover_Letter.docx', PREFIX + 'Cover_Letter.pdf']
    assert len(sends()) == 2

    r = run(resume, '--submit-role', 'Data Analyst', '--submit-tag', 'Acme')    # company tag refused
    assert r.returncode != 0 and 'REFUSED' in r.stdout + r.stderr
    r = run(resume, '--submit-role', 'Very Long Senior Principal Data Migration Test Analyst')
    assert r.returncode != 0 and 'REFUSED' in r.stdout + r.stderr               # >= 55 chars refused
    assert sends() == [PREFIX + 'BI_Analyst_EDW.docx', PREFIX + 'BI_Analyst_EDW.pdf']

    assert not [f for f in os.listdir(APP) if f.startswith(('resume.', 'cover_letter.')) and not f.endswith('.md')]
    print('compile_docs_test: 7 cases passed')
finally:
    shutil.rmtree(os.path.dirname(APP), ignore_errors=True)
    if saved is None:
        os.path.exists(INDEX) and os.remove(INDEX)
    else:
        open(INDEX, 'w').write(saved)
