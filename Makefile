PYTHON ?= python3

.PHONY: setup demo ui checks ats fit verify live jd-url source harvest

setup:            ## install dependencies
	$(PYTHON) -m pip install -r requirements.txt

demo:             ## build the demo job store
	$(PYTHON) scripts/seed_demo.py

ui: demo          ## run the Streamlit UI
	streamlit run streamlit_app.py

checks:           ## every regression suite (CI runs this)
	$(PYTHON) scripts/job_store_test.py
	$(PYTHON) scripts/jsonld_test.py
	$(PYTHON) scripts/ats_harvest_test.py
	$(PYTHON) scripts/compile_docs_test.py
	$(PYTHON) scripts/employer_verify.py --selftest
	$(PYTHON) -c "import json;json.load(open('data/master_experience_claims.json'));json.load(open('data/profile.json'));print('data files: valid JSON')"

ats:              ## make ats RESUME=examples/resume.md JD=examples/jd_data_analyst.txt
	$(PYTHON) scripts/ats_analyzer.py --resume $(RESUME) --jd-file $(JD)

fit:              ## make fit JD=examples/jd_knockout.txt
	$(PYTHON) scripts/fit_decision.py --jd $(JD)

verify:           ## make verify RESUME=examples/resume.md
	$(PYTHON) scripts/verify_claims.py --resume $(RESUME)

live:             ## make live URL=https://...
	$(PYTHON) scripts/check_live.py --url "$(URL)"

jd-url:           ## make jd-url URL=https://...  (schema.org JobPosting reader)
	$(PYTHON) scripts/jsonld.py "$(URL)"

source:           ## Indeed + LinkedIn via JobSpy (needs requirements-sourcing.txt)
	$(PYTHON) scripts/jobspy_fetch.py --hours $(or $(HOURS),48)

harvest:          ## pull fresh reqs straight from employers' own ATS boards
	$(PYTHON) scripts/ats_harvest.py seed --file data/ats_seed_ie_in.csv
	$(PYTHON) scripts/ats_harvest.py harvest --hours $(or $(HOURS),48) --market $(or $(MARKET),IE,IN)
