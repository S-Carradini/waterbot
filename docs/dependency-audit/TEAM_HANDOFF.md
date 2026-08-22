# Dependency Audit — Team Handoff

**From:** Jacob Kuriakose
**Purpose:** So the team can pick this up cleanly after I leave. This doc says **what I did, what
I found, what I'm leaving in-flight, and exactly what remains** — with enough context that no one
has to reverse-engineer my thinking.

Read this alongside:
- **`DEPENDENCY_AUDIT_REPORT.md`** — the actual findings (the substance).
- **`raw/`** — raw scanner output, so you can trust/verify every number.

---

## 1. Context: why this exists

The professor asked for a **dependency check** — the first coordinated one this project has had.
Goal: find libraries that are outdated or have known security vulnerabilities (CVEs), and set up
a way to keep on top of it. "Dependencies" = the third-party packages in `requirements*.txt`,
`package.json`, the Docker base images, and the GitHub Actions.

There were no prior materials or process to build on — this is greenfield.

---

## 2. What I did (done ✅)

- **Inventoried every dependency surface:** backend Python (3 manifests), frontend npm, the new
  `eval/` ML deps, Docker base images, GitHub Actions.
- **Ran the scanners** against the *real* versions: `pip-audit` on the pinned prod file (under
  Python 3.11), `npm audit` on the frontend. Raw output saved in `raw/`.
- **Resolved "which versions does prod actually run"** — a genuinely confusing question here
  (there are three conflicting answers; see Finding 1 in the report). Answer: **`requirements_full.txt`**.
- **Identified ~40 dead packages** left over from the removed ChromaDB/AWS stack (Finding 2) —
  the highest-value cleanup, and zero functional risk.
- **Classified every upgrade by risk** (safe / moderate / breaking) so no one blindly bumps
  LangChain or the OpenAI SDK and breaks prod.
- **Wrote the findings report** (`DEPENDENCY_AUDIT_REPORT.md`).
- **Drafted a `dependabot.yml`** (in this folder) to automate scanning going forward.

---

## 3. Key findings at a glance

(Full detail + evidence in the report. This is the "if you read nothing else" version.)

1. **No single source of truth for versions.** `requirements.txt` (unpinned), `requirements_full.txt`
   (pinned, 5 months old), and the conda env (drifted) all disagree. **Prod runs `requirements_full.txt`.**
   Fix this *first* — everything else depends on it.
2. **~40 of 119 backend packages are dead weight** from the old ChromaDB/AWS stack (kubernetes,
   onnxruntime, grpcio, protobuf, opentelemetry, posthog, …). Nothing imports them. Removing them
   deletes a big chunk of the CVEs for free.
3. **Backend: ~105 advisories across 26 packages.** Worst offenders: `aiohttp` (very stale),
   `starlette`, `python-multipart`, `urllib3`, `jinja2`.
4. **Frontend: 9 vulns (7 high)**, all in the build toolchain (Vite/Rollup/esbuild). Mostly fixable
   with plain `npm audit fix`.
5. **No automated scanning exists** — no Dependabot/Snyk. That's why it silently rotted.
6. **Minor:** Dockerfile builds frontend on Node 18 but CI uses Node 20; `setup-python` action
   version differs between workflows.

---

## 4. ⚠️ Critical things to know before touching anything

- **`main` auto-deploys to Railway.** `.github/workflows/deploy-railway.yaml` triggers on push to
  `main`. **A merge to `main` = a production deploy.** Do all work on a branch; only merge after review.
- **A PR does NOT deploy** — only merging to `main` does. So PRs are safe. But note: `eval.yaml`
  runs the RAG eval suite on any PR touching `application/**`, which **spends OpenAI tokens**. Expect
  that cost when the cleanup PR opens.
- **Always audit/build against Python 3.11 — it's what prod runs** (`Dockerfile` + `.python-version`).
  The pinned prod file requires `numpy==2.3.2`, which needs Python ≥3.11, so it won't even install on
  older Python. Don't rely on whatever local interpreter you happen to have.
  *(Machine-specific note: the conda env `waterbot` on Jacob's laptop was Python 3.10, so it silently
  drifted to different versions — that env is personal, not a shared team artifact. The lesson is
  "use 3.11," not "use that env." I audited with a throwaway `python3.11 -m venv` instead.)*
- **Don't run `npm audit fix --force`** — it pulls major bumps (React 19 etc.) and will break the build.
- **The OpenAI SDK situation is a landmine:** prod pins `openai==1.109.1` (1.x), but the conda env
  is on `2.21.0` (2.x — a breaking rewrite). Someone upgraded locally but never in prod. Resolve
  this deliberately, don't let it happen by accident.

---

## 5. What I'm leaving in-flight / what remains ⏳

Ordered by priority. Anyone on the team can pick these up.

| # | Task | Status | Risk | Notes |
|---|---|---|---|---|
| 1 | **Consolidate to one pinned manifest** (regenerate from real imports, drop the ~40 dead deps, delete/deprecate unpinned `requirements.txt`) | Not started | Low functional, but touches Docker build | The keystone task. Do first. Simplifies the confusing 2-file Docker install too. |
| 2 | **Apply 🟢 safe security patches** on the branch, verify with tests + eval, open PR | Not started (may partly do this in my week — see §6) | Low | certifi, idna, urllib3, requests, jinja2, python-multipart, etc. |
| 3 | **Commit `dependabot.yml`** to automate future scanning | Draft ready in this folder | None | Just needs review + merge. |
| 4 | **`npm audit fix`** (no `--force`) + commit updated lockfile | Not started | Low | Build-toolchain CVEs. |
| 5 | **🔴 Major upgrades** — LangChain family, openai 1.x→2.x, React 18→19 | Not started (documented only) | **High** | Each is separate deliberate work + eval validation. Do NOT batch. |
| 6 | **Align Node 18→20 in Dockerfile** to match CI | Not started | Low | One-line change. |
| 7 | **Fix env drift** — decide whether the shared `waterbot` conda env should be rebuilt on 3.11 to mirror prod | Not started | Low | Prevents future "works on my machine" confusion. |

---

## 6. How I intend to spend my remaining week

(Adjust based on professor's answer on scope/authority.)

1. Task #1 (consolidate manifest) + Task #2 (safe patches) on the `dependency-audit` branch.
2. Verify with the Playwright tests + eval suite (nothing merged to `main`).
3. Open a **PR for review** — leave the merge decision to the team.
4. Commit the `dependabot.yml`.
5. Leave the 🔴 major upgrades documented (Task #5) for the team to schedule.

**Everything I change stays on the `dependency-audit` branch as a reviewable PR. I will not merge
to `main`.**

---

## 7. How to reproduce / continue the audit

```bash
# Backend audit — MUST use Python 3.11 (prod's version; older Python fails on numpy==2.3.2)
python3.11 -m venv /tmp/wb-audit
/tmp/wb-audit/bin/pip install pip-audit
/tmp/wb-audit/bin/pip-audit -r application/requirements_full.txt

# Frontend audit
cd frontend && npm ci && npm audit

# Verify a package is unused before deleting it from requirements
grep -rl "<import_name>" application/*.py application/managers application/adapters

# Which file does prod actually use? -> requirements_full.txt
#   (Dockerfile installs it first; requirements.txt is installed --no-deps and ignored for versions)
```

---

## 7a. How to verify each finding (spot-check the report)

Each finding traces to a command you can run yourself. Use this to confirm claims (or defend them).

```bash
# Finding 1 — three conflicting version definitions; prod uses requirements_full.txt
cat application/requirements.txt                       # (a) unpinned — no versions
head -5 application/requirements_full.txt              # (b) pinned — real versions
grep -A3 "requirements" Dockerfile                     # (c) full installed first, txt --no-deps => ignored

# Finding 2 — the ~40 dead deps: installed but never imported (these return NOTHING)
grep -rl "kubernetes"  application/*.py application/managers application/adapters
grep -rl "onnxruntime" application/*.py application/managers application/adapters
grep -rl "import grpc" application/*.py application/managers application/adapters
grep -E "kubernetes|onnxruntime|grpcio|google-auth" application/requirements_full.txt  # ...yet pinned

# Finding 3 — backend vuln counts (run against Python 3.11, see §7)
/tmp/wb-audit/bin/pip-audit -r application/requirements_full.txt 2>/dev/null > /tmp/a.txt
grep -cE "PYSEC|GHSA" /tmp/a.txt                                        # ~105 advisories
grep -vE "^(Name|----|Found)" /tmp/a.txt | awk '{print $1}' | sort -u   # 26 packages

# Finding 5 — frontend: 9 vulns (7 high)
cd frontend && npm ci && npm audit ; cd ..

# Finding 7 — Node mismatch: Dockerfile builds on 18, CI tests on 20
grep FROM Dockerfile ; grep -i node-version .github/workflows/deploy-railway.yaml
```

Raw scanner output for cross-checking lives in `raw/`.

---

## 8. Open questions for the professor (unblock before major changes)

1. **Deliverable:** report only, or also apply the safe patches as a PR? (I've assumed: report +
   safe-patch PR on a branch, nothing merged.)
2. **Authority:** am I allowed to open the cleanup PR against `main`, or should the team drive all changes?
3. **Automation:** OK to add Dependabot (weekly PRs), or does the team prefer a manual quarterly check?

---

## 9. File map for this audit

```
docs/dependency-audit/
├── DEPENDENCY_AUDIT_REPORT.md   # the findings (substance)
├── TEAM_HANDOFF.md              # this file (status + what remains)
├── dependabot.yml               # drafted automation config (review before moving to .github/)
└── raw/
    ├── prod_pip_audit.txt       # pip-audit on requirements_full.txt (Python 3.11) — the authoritative prod scan
    └── npm_audit.json           # npm audit JSON (frontend)
```
