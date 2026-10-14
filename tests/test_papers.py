import unittest

from ibpp import catalog
from ibpp.cli import parse_query, parse_years
from ibpp.papers import Paper, Session, markschemes_for, parse_filename, question_papers

MAY24 = Session(2024, 5, "/x/May 2024")


def paper(name: str, session: Session = MAY24) -> Paper:
    return Paper(session=session, name=name, path=f"{session.path}/{name}", size=1, **parse_filename(name))


class ParseFilename(unittest.TestCase):
    def test_modern(self):
        info = parse_filename("Physics_paper_2__TZ1_HL_markscheme.pdf")
        self.assertEqual(info, {"subject": "Physics", "number": "2", "tz": 1, "level": "HL",
                                "markscheme": True, "lang": "en", "variant": ""})

    def test_translation_and_new_physics(self):
        info = parse_filename("Physics_paper_1A_TZ2_SL_Spanish.pdf")
        self.assertEqual((info["number"], info["tz"], info["level"], info["lang"]), ("1A", 2, "SL", "es"))
        self.assertEqual(parse_filename("Biology_paper_1__[German]_HL.pdf")["lang"], "de")

    def test_variants(self):
        self.assertEqual(parse_filename("Mathematics_paper_3_Calculus__HL.pdf")["variant"], "Calculus")
        self.assertEqual(parse_filename("Computer_science_paper_3__case_study_HL.pdf")["variant"], "case study")
        self.assertEqual(parse_filename("Mathematics_analysis_and_approaches_paper_1__TZ1_HL.pdf")["subject"],
                         "Mathematics_analysis_and_approaches")

    def test_rejects_non_papers(self):
        self.assertIsNone(parse_filename("BM Paper 1.png"))
        self.assertIsNone(parse_filename("Computer Science HL Paper 1.txt"))


class Selection(unittest.TestCase):
    library = {MAY24: [paper(n) for n in (
        "Physics_paper_1__TZ1_HL.pdf", "Physics_paper_1__TZ1_HL_markscheme.pdf",
        "Physics_paper_1__TZ2_HL.pdf", "Physics_paper_1__TZ2_HL_markscheme.pdf",
        "Physics_paper_1__HL_Spanish.pdf", "Physics_paper_1__TZ1_SL.pdf",
        "Physics_paper_2__TZ1_HL.pdf", "Physics_paper_2__TZ1_HL_markscheme.pdf",
        "Physics_paper_2__SL_markscheme_Spanish.pdf",
    )]}

    def test_language_with_english_fallback(self):
        found = question_papers(self.library, level="HL", lang="es")
        self.assertEqual([(p.number, p.lang, p.fallback) for p in found], [("1", "es", False), ("2", "en", True)])

    def test_level_filter(self):
        found = question_papers(self.library, level="HL", number="1")
        self.assertEqual([p.tz for p in found], [1, 2])

    def test_markscheme_same_tz(self):
        q = next(p for p in self.library[MAY24] if p.name == "Physics_paper_1__TZ2_HL.pdf")
        self.assertEqual([m.name for m in markschemes_for(q, self.library)], ["Physics_paper_1__TZ2_HL_markscheme.pdf"])

    def test_markscheme_ambiguous_for_untagged_translation(self):
        q = next(p for p in self.library[MAY24] if p.lang == "es")
        self.assertEqual([m.tz for m in markschemes_for(q, self.library)], [1, 2])


class Inputs(unittest.TestCase):
    def test_years(self):
        self.assertIsNone(parse_years(""))
        self.assertEqual(parse_years("2024"), {2024})
        self.assertEqual(parse_years("2019 - 2021"), {2019, 2020, 2021})
        self.assertEqual(parse_years("19-20, 2023"), {2019, 2020, 2023})
        with self.assertRaises(ValueError):
            parse_years("last year")

    def test_query_words(self):
        q = parse_query(["math", "aa", "2019-2021", "may", "p1b", "tz2", "sl", "spanish"])
        self.assertEqual((q.subject, q.years, q.months, q.number, q.tz, q.level, q.lang),
                         ("math-aa", {2019, 2020, 2021}, {5}, "1B", 2, "SL", "es"))
        q = parse_query(["physics", "2", "24"])
        self.assertEqual((q.number, q.years, q.single_year), ("2", {2024}, True))
        self.assertFalse(parse_query(["physics", "hl"]).has_filters)

    def test_subject_lookup(self):
        self.assertEqual(catalog.lookup("phys").key, "physics")
        self.assertEqual(catalog.lookup("aa").key, "math-aa")
        self.assertEqual(catalog.lookup("math", prefer=["math-aa", "physics"]).key, "math-aa")
        with self.assertRaises(LookupError):
            catalog.lookup("math")


if __name__ == "__main__":
    unittest.main()
