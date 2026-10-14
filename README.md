# ibpp

IB past papers from your terminal. Pick a subject and a year (or a range for a
random paper). ibpp opens the paper, then the matching markscheme when you're
done. Papers come from [ibdocs.re](https://ibdocs.re).

```
$ ibpp
✓ Subject · Physics HL
✓ Year · 2019-2023
✓ Paper · Paper 2
⚄ Random pick (out of 14)
✓ Opened May 2021 · Paper 2 · TZ2 · HL
  ~/IB Past Papers/Physics HL/2021 May/Physics_paper_2__TZ2_HL.pdf

? When you're done
❯ Open the markscheme
  Skip it
```

Plain Python, no dependencies. Works on Linux, macOS and Windows.

## Install

```sh
pipx install git+https://github.com/urresta/ibpp
```

No pipx? `sudo pacman -S python-pipx` on Arch, `py -m pip install --user pipx`
on Windows. Or skip installing and run `python -m ibpp` inside this folder.

## Usage

```sh
ibpp                              # guided mode (first run sets up your subjects)
ibpp physics 2024                 # pick from 2024's papers
ibpp physics 2019-2023 p2         # random paper 2 from that range
ibpp math 2023 may p1 tz2 --ms    # that exact paper, plus its markscheme
ibpp random                       # random paper you haven't done yet
ibpp list physics 2025            # what's available
ibpp log                          # papers you've done
ibpp setup                        # change subjects, language, PDF viewer
```

Filters go in any order: years (`2024`, `2019-2023`, `2020-`), session
(`may`, `nov`), paper (`p1`, `p2`, `p1b`), time zone (`tz1`), level (`hl`,
`sl`). For the language use `--es`, `--en`, `--fr` or `--de`. Subject names can
be shortened (`phys`, `chem`, `aa`), and `math` means whichever math you take.

PDFs are kept in `~/IB Past Papers`, so a paper only downloads once.

## Notes

- **Math AA/AI** exams started in 2021. Setup can also include the pre-2021
  Mathematics papers.
- **Physics** changed syllabus in 2025: papers 1A, 1B and 2 instead of 1, 2 and
  3. `p1` matches both 1A and 1B.
- **Translated papers** don't say which time zone they're from, so ibpp asks
  which markscheme you want.
- **Opening PDFs** uses your system default. Setup lets you pick an installed
  viewer such as Zathura or Okular instead.

## Development

```sh
python -m unittest discover -s tests
```

To release, bump `version` in `pyproject.toml`, commit, then tag and push:

```sh
git tag v0.3.0 && git push origin main v0.3.0
```

GitHub Actions runs the tests, publishes to PyPI and creates a GitHub release.

## Disclaimer

ibpp is not affiliated with the IBO or ibdocs.re and contains no exam
material. It downloads files that ibdocs.re serves publicly. Past papers are
© International Baccalaureate Organization.
