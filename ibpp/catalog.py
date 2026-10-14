"""IB subjects and how their past papers are named on ibdocs.re."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Subject:
    key: str
    name: str
    groups: tuple[int, ...]       # IB subject groups whose folders hold this subject
    prefixes: tuple[str, ...]     # filename prefixes, e.g. "Physics" in Physics_paper_1__TZ1_HL.pdf
    aliases: tuple[str, ...] = ()
    legacy: tuple[str, ...] = ()  # prefixes of the previous syllabus (opt-in)
    legacy_note: str = ""


SUBJECTS: tuple[Subject, ...] = (
    Subject("physics", "Physics", (4,), ("Physics",), ("phys", "phy")),
    Subject("chemistry", "Chemistry", (4,), ("Chemistry",), ("chem",)),
    Subject("biology", "Biology", (4,), ("Biology",), ("bio",)),
    Subject("computer-science", "Computer Science", (4,), ("Computer_science",), ("cs", "compsci")),
    Subject("ess", "Environmental Systems and Societies", (3, 4),
            ("Environmental_systems_and_societies",), ("environmental",)),
    Subject("sehs", "Sports, Exercise and Health Science", (4,),
            ("Sports_exercise_and_health_science",), ("sports",)),
    Subject("design-technology", "Design Technology", (4,), ("Design_technology",), ("dt", "design")),
    Subject("math-aa", "Math AA", (5,), ("Mathematics_analysis_and_approaches",),
            ("aa", "maa", "math-analysis"),
            legacy=("Mathematics",), legacy_note="pre-2021 Mathematics papers"),
    Subject("math-ai", "Math AI", (5,), ("Mathematics_applications_and_interpretation",),
            ("ai", "mai", "math-applications"),
            legacy=("Mathematical_studies",), legacy_note="pre-2021 Math Studies papers"),
    Subject("further-math", "Further Mathematics", (5,), ("Further_mathematics",), ("fm",)),
    Subject("economics", "Economics", (3,), ("Economics",), ("econ",)),
    Subject("business", "Business Management", (3,),
            ("Business_management", "Business_and_management"), ("bm", "business-management")),
    Subject("history", "History", (3,), ("History", "History_route_2"), ("hist",)),
    Subject("geography", "Geography", (3,), ("Geography",), ("geo",)),
    Subject("psychology", "Psychology", (3,), ("Psychology",), ("psych",)),
    Subject("philosophy", "Philosophy", (3,), ("Philosophy",), ("philo",)),
    Subject("global-politics", "Global Politics", (3,), ("Global_politics",), ("gp", "gpol")),
    Subject("digital-society", "Digital Society", (3,), ("Digital_society",), ("ds",),
            legacy=("ITGS",), legacy_note="the old ITGS papers"),
    Subject("anthropology", "Social and Cultural Anthropology", (3,),
            ("Social_and_cultural_anthropology",), ("sca",)),
)

_BY_KEY = {s.key: s for s in SUBJECTS}


def _norm(text: str) -> str:
    return re.sub(r"[\s_]+", "-", text.strip().lower())


def get(key: str) -> Subject:
    return _BY_KEY[key]


def lookup(token: str, prefer: list[str] | tuple[str, ...] = ()) -> Subject:
    """Find a subject by key, alias or unambiguous prefix ("phys", "math-a", "aa").

    When a prefix is ambiguous, subjects listed in `prefer` (the user's own
    subjects) win, so "math" resolves to Math AA for someone who takes it.
    """
    t = _norm(token)
    for subject in SUBJECTS:
        if t == subject.key or t in subject.aliases:
            return subject
    matches = [s for s in SUBJECTS if s.key.startswith(t) or _norm(s.name).startswith(t)]
    if len(matches) > 1:
        preferred = [s for s in matches if s.key in prefer]
        if len(preferred) == 1:
            return preferred[0]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise LookupError(f"unknown subject '{token}'")
    raise LookupError(f"'{token}' could be " + ", ".join(s.key for s in matches) + " — be more specific")
