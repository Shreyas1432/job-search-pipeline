"""Candidate profile: the only place personal settings live.

Reads data/profile.json. Everything that used to be hard-coded to one person
(name on send files, years of experience, salary floor, work permission,
past employers used to spot the Experience section) comes from here.
"""
import json
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.environ.get("PROFILE_FILE", os.path.join(BASE_DIR, "data", "profile.json"))

_DEFAULT = {"name": "Candidate", "years_experience": 3, "salary_floor": 60000,
            "work_permission": "Stamp 1G", "employers": []}


def load():
    try:
        with open(PATH, encoding="utf-8") as fh:
            return {**_DEFAULT, **json.load(fh)}
    except (OSError, ValueError):
        return dict(_DEFAULT)


PROFILE = load()


def file_prefix():
    """'Alex Morgan' -> 'Alex_Morgan_' (send files are named for the candidate)."""
    return "_".join(PROFILE["name"].split()) + "_"
