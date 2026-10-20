# Handoff: health-data-anonymiser (frozen prototype, PR #4 open)

## Where things stand
- Repo `otmanm/health-data-anonymiser`, branch `claude/improve-mac-gui-scrubber-SjgtZ`, **PR #4** into `main` is open, CI green (6/6), mergeable, head `b22814f`. The PR itself and `git log origin/main..HEAD` hold the full feature history, so it isn't repeated here.
- Decision already made by the user: **freeze the repo as a prototype**. README now has a "Status: frozen prototype" section with known limitations (README.md, top).
- Codex review loop **deliberately stopped** after 7 rounds. It finds new edge cases every pass. Remaining findings are documented as README limitations, not fixed (output written straight into the chosen folder; slow cancel during OCR; K/L/M personal NIFs; surrogate mode still emits `**TOKEN**` for Spanish IDs).
- Validators fixed after Opus recheck: CIF accepts digit or letter control for every org letter; NAF accepts both the concatenation and `province*10^7 + serial` rules (`validators.py`). 113 tests pass: `python3 -m unittest discover -p "test_*.py"`.

## Pending decisions (the user's, do not act without explicit OK)
| Decision | Notes |
|---|---|
| Merge PR #4 | Recommended. GitHub shows the default branch README, so the freeze note only appears after merge. |
| Post the OpenMed issue | Public/outward. Draft: `/tmp/claude-0/-home-user-health-data-anonymiser/42428ce3-0f0b-55d1-927f-faea6f332dbb/scratchpad/openmed_issue_draft.md` (needs rewrite, see below). |
| Keep or delete `.claude/` SessionStart hook (installs `gh`) | Currently kept. |
| Archive the repo after merging | User's call. |

## OpenMed issue: rewrite instructions (from the Opus max recheck)
- OpenMed (`maziyarpanahi/openmed`, checked at commit `8440bda`, v3.0.0) has DNI/NIE, IBAN, Belgian RRN, Moroccan CIN, Portuguese NIF validators but **no Spanish CIF, NAF/NUSS or K/L/M personal-NIF handling**, and no existing issue about them.
- Lead with **NAF** and **K/L/M NIFs**; CIF identifies companies, so it is the weakest part. Offer CIF as optional.
- Use their `[FEATURE]` issue form (blank issues disabled); no tool or vendor names in the body (their `AGENTS.md`); link code by **commit-SHA permalink**, not the `claude/...` branch.
- **Before posting:** run synthetic NAF, K/L/M and hyphenated-DNI samples through OpenMed's Spanish pipeline locally. If any ID survives de-identification, file a **private security advisory** (their `SECURITY.md`) instead of a public issue. Never run OpenMed code from an untrusted clone without care.
- Their maintainer closed the user's PR #1607 for lacking a linked maintainer-authored issue, so: issue first, wait for acknowledgement, no unsolicited PR.
- Test vectors to use (synthetic): `28 12345678 40` valid / `…41` invalid; `28 01234567 42` (split rule) and `…85` (concatenation) show the pre-1992 ambiguity; `B12345674` CIF valid.

## Facts and gotchas
- `gh` works via **REST only** (`gh api ...`); GraphQL is blocked, so `gh pr create`/`gh pr list` fail. Comment on PRs with `gh api -X POST repos/otmanm/health-data-anonymiser/issues/4/comments -f body=...`.
- **NLM Scrubber output format and config keys are unverified.** The app writes keys and expects `**NAME**` tokens; the Opus recheck says NLM's documented keys are `ROOT1`, `ClinicalReports_dir`, `ClinicalReports_files`, `nPHI_outdir` and it emits `[PERSONALNAME]`-style tags. The app has never been run against the real binary. README says so. Reference: lhncbc.nlm.nih.gov/scrubber/configuration.html.
- The Fable "what did Codex miss" review was stopped before reporting; its one lead was exactly the config-key mismatch above.
- Earlier mistake to keep corrected: the user's OpenMed PRs are #604, #605, #616 merged; #623 closed unmerged; #1702 merged (docs); #1607 closed stale. Contribution is real but modest.
- GitHub access to OpenMed through `gh` is blocked in these sessions; `git clone https://github.com/maziyarpanahi/openmed` (via the proxy) works.

## User preferences
Tired of permission prompts and wants minimal approvals. Do **not** use the Parallel Search / web-search connector (it triggers per-call approval prompts). Wants decisions as short tables and blunt, honest answers. They asked about a full-permissions mode; the session mode menu only offered Auto / Accept edits / Plan.

## Suggested next steps
1. Ask the user to merge PR #4 (or merge it if they say so).
2. Rewrite the OpenMed issue per above; post only on their go-ahead.
3. Optionally verify NLM's real config/output format on a Mac and fix or document.

## Skills
None required. `code-review` or `verify` could help if code changes resume.

## Update (latest, head after this commit)
- PR #4 head moved past b22814f: `aad2077` added a DOCX OSError fix and a stronger README warning that the NLM integration is probably non-working. CI green. Codex has now reviewed 9 times; it always finds more edge cases. Do not keep chasing them.
- Codex rounds 8-9 also confirmed (independently of the Opus recheck): the app writes the wrong NLM config keys and its built-in download URL may be a 403 (official: https://data.lhncbc.nlm.nih.gov/public/scrubber/files/linux/scrubber.19.0403L.zip). **First real task: run the real NLM Scrubber on this Mac and fix or document the mismatch.**
- Known, unfixed, minor: OCR can drop a failed page silently; a run can report success when the scrubber omits a file; dropped file paths with spaces may fail; phone check can cut digits from longer grouped IDs; cancel lags while the scrubber is quiet.
- Cloud credit ($250 promo) is only for cloud sessions and expires Nov 4; local sessions use normal plan limits instead.
