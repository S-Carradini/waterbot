# WaterBot Dependency Audit — Findings Report

**Author:** Jacob Kuriakose
**Date:** 2026-08-22
**Scope:** Backend (Python), Frontend (npm), Docker base images, GitHub Actions
**Status:** Findings complete. No production changes applied. Proposed fixes tracked separately.

> This is the first coordinated dependency audit of WaterBot. It was produced by running
> standard scanners (`pip-audit`, `npm audit`) against the project's real dependency
> manifests. Every number below is reproducible — see [How to reproduce](#how-to-reproduce).

---

## TL;DR

| Surface | Vulnerable packages | Notable severity | Headline |
|---|---|---|---|
| Backend (prod pins) | **26 packages**, ~105 advisories | Multiple high (aiohttp, starlette, urllib3, jinja2, python-multipart) | Pinned versions are ~5 months stale (last touched Mar 2026) |
| Frontend (npm) | **9 vulnerabilities** (7 high, 1 moderate, 1 low) | High: `vite`, `rollup`, `esbuild`, `postcss`, `nanoid`, `react-router` | Build-toolchain CVEs; mostly fixable with `npm audit fix` |
| Docker images | 1 aging | — | `node:18-alpine` is past support; CI already uses Node 20 (mismatch) |
| GitHub Actions | minor | — | Mostly `@v4` (fine); one `setup-python@v4` vs `@v5` inconsistency |

**Three biggest takeaways:**

1. **Version chaos — there is no single source of truth.** The project has *three* conflicting
   definitions of "what versions we run" (see [Finding 1](#finding-1--no-single-source-of-truth-critical)).
   This must be fixed first; everything else depends on it.
2. **~40 of 119 pinned backend packages are dead weight** — leftover transitive dependencies
   from the removed ChromaDB/AWS stack. They ship nothing but CVEs. Removing them is the
   single highest-value, lowest-risk action (see [Finding 2](#finding-2--dead-dependencies-from-removed-chromadbaws-stack-high-value)).
3. **Everything is stale, nothing is scanned.** No automated dependency scanning exists
   (no Dependabot). Deps were last updated ~5 months ago. This audit is a snapshot; without
   automation it will rot again (see [Finding 6](#finding-6--no-automated-scanning)).

---

## Finding 1 — No single source of truth (CRITICAL)

There are **three different, conflicting** answers to "what version of each package do we run":

| Definition | Where | State | Example: `openai` | Example: `numpy` |
|---|---|---|---|---|
| **Unpinned** | `application/requirements.txt` | No versions at all — resolves to *latest* at build time | (unpinned) | (unpinned) |
| **Pinned (prod truth)** | `application/requirements_full.txt` | Fully pinned, last edited **Mar 2026** | `1.109.1` | `2.3.2` |
| **Dev env (drifted)** | a local dev env (here: Jacob's conda env `waterbot`, Python 3.10 — personal, not shared) | Hand-installed, drifted | `2.21.0` (major diff!) | `1.26.4` |

**Why this happens:** the `Dockerfile` installs `requirements_full.txt` first (pinned), then
`requirements.txt` with `--no-deps`. Because the packages are already satisfied by the pinned
file, the unpinned `requirements.txt` names are effectively **ignored for versioning**. So:

> **Production actually runs the versions in `requirements_full.txt`.** That is the source of
> truth today — but it's implicit and confusing, and the unpinned `requirements.txt` is a trap
> (anyone running `pip install -r requirements.txt` locally gets *different* versions than prod).

**Extra evidence of drift:** `requirements_full.txt` pins `numpy==2.3.2`, which requires
Python ≥3.11. A local dev env on an older Python *cannot even install the pinned file* — which is
exactly what happened on Jacob's laptop (a personal conda env on Python 3.10 silently fell back to
numpy 1.26.4). Prod (Docker) is Python 3.11, so it's fine. **Takeaway for the team: always
audit/build against Python 3.11 to match prod; a mismatched local interpreter gives misleading results.**

**Recommendation:** Consolidate to one pinned, reproducible manifest (see [Recommendations](#recommendations)).

---

## Finding 2 — Dead dependencies from removed ChromaDB/AWS stack (HIGH VALUE)

WaterBot migrated **off ChromaDB → pgvector** and **off AWS → Railway** (see git history,
Mar 2026). But `requirements_full.txt` still pins the entire transitive dependency cluster
those tools dragged in. **None of these are imported anywhere in `application/` code** (verified
by grep):

| Dead package (pinned) | Was pulled in by | Ships CVEs? |
|---|---|---|
| `kubernetes==29.0.0` | ChromaDB | — |
| `onnxruntime==1.18.0` | ChromaDB (embeddings) | — |
| `tokenizers==0.19.1` | ChromaDB | — |
| `grpcio==1.63.0` | ChromaDB / otel | — |
| `protobuf==4.25.3` | grpc cluster | ✅ yes |
| `pyasn1==0.6.0`, `pyasn1_modules` | google-auth | ✅ yes |
| `google-auth==2.29.0`, `googleapis-common-protos` | ChromaDB telemetry | — |
| `posthog==3.5.0` | ChromaDB telemetry | — |
| `PyPika==0.48.9` | ChromaDB | — |
| `opentelemetry-*` (10 packages) | ChromaDB telemetry | — |
| `bcrypt`, `mmh3`, `flatbuffers`, `coloredlogs`, `humanfriendly`, `monotonic`, `overrides`, `pyreadline3` | ChromaDB cluster | — |

That's **~40 of the 119 pinned lines** that exist only to serve a database the app no longer
uses. Several of them (`protobuf`, `pyasn1`, `zipp`, `grpcio`) are *directly responsible for
CVEs in [Finding 3](#finding-3--backend-known-vulnerabilities)*.

**Recommendation:** Regenerate `requirements_full.txt` from the app's *actual* imports. This is
zero functional risk (nothing imports them) and removes a large slice of the vulnerability
surface for free. **Do this before chasing individual CVEs** — it may eliminate a third of them.

---

## Finding 3 — Backend known vulnerabilities

`pip-audit` against `requirements_full.txt` (the prod pins) under Python 3.11 reports
**~105 advisories across 26 packages**. Highest-priority (in-use, not dead-weight) packages:

| Package | Pinned | Fix version | Notes |
|---|---|---|---|
| `aiohttp` | 3.9.5 | 3.14.x | **Largest single source** — 30+ advisories. Very stale. |
| `starlette` | 0.41.3 | 0.47+ / 1.x | FastAPI's core; several advisories incl. DoS/multipart. |
| `python-multipart` | 0.0.9 | 0.0.31 | Form/upload parsing DoS — relevant (app takes POST bodies). |
| `urllib3` | 2.2.1 | 2.6+ | 7 advisories. |
| `jinja2` | 3.1.4 | 3.1.6 | Templating (RiverBot/legacy pages use it). |
| `requests` | 2.32.5 | 2.33.0 | — |
| `certifi` | 2024.2.2 | 2024.7.4 | Root CA bundle — easy, safe bump. |
| `idna`, `h11`, `click`, `orjson`, `ujson`, `marshmallow`, `pygments`, `filelock`, `python-dotenv`, `zipp` | various | various | Mostly transitive; low individual risk. |
| `langchain`, `langchain-core`, `langchain-openai`, `langchain-text-splitters`, `langsmith`, `langchain-classic`, `langgraph-sdk` | various | various | LangChain family — bump together, test carefully (see [Finding 4](#finding-4--upgrade-risk-tiers)). |

Full raw output: `docs/dependency-audit/raw/prod_pip_audit.txt` (regenerate anytime — see below).

> ⚠️ Severity note: `pip-audit` lists advisory IDs and fix versions but not CVSS scores. The
> "priority" ranking above is my judgment based on (a) whether the package is actually used and
> (b) whether it's on a request/parsing path. Treat it as a starting point, not a CVSS report.

---

## Finding 4 — Upgrade risk tiers

Not all updates are equal. Grouped by risk:

**🟢 Safe (patch/minor, no expected breakage) — do these first:**
`certifi`, `idna`, `urllib3`, `requests`, `jinja2`, `h11`, `click`, `python-multipart`,
`orjson`, `ujson`, `pygments`, `filelock`, `python-dotenv`, `zipp`, `aiohttp` (within 3.x).

**🟡 Moderate (minor version, worth a test run):**
`fastapi` + `starlette` + `uvicorn` (bump as a set — Starlette majors can shift behavior),
`pydantic` (2.10 → 2.12 is minor but touches everything), frontend `vite`/`rollup`/`esbuild`.

**🔴 High (major version, breaking changes likely — do NOT batch with the rest):**
- **LangChain family** — `langchain` 1.1 → 1.3, `langchain-core` etc. LangChain has a history
  of breaking public APIs across minors. Bump the whole family together and run the eval suite.
- **`openai`** — prod pins 1.109.1; the SDK's 2.x line is a breaking rewrite. The conda env is
  already on 2.21.0, so someone has *informally* tested 2.x locally — but prod is on 1.x. This
  gap needs deliberate resolution.
- **Frontend React 18 → 19**, `react-router-dom` majors, `framer-motion` 12 → 13,
  `lucide-react` 0.561 → 1.33, `marked` 17 → 18 — all majors, defer unless needed.

---

## Finding 5 — Frontend

`npm audit`: **9 vulnerabilities (7 high, 1 moderate, 1 low).** All are in the **build
toolchain** (Vite/Rollup/esbuild/PostCSS), not shipped runtime code — lower real-world risk,
but still worth fixing:

| Package | Severity | Advisory summary |
|---|---|---|
| `rollup` | high | Arbitrary file write via path traversal |
| `vite` | high | (≤6.4.2) multiple |
| `esbuild` | moderate | dev-server request smuggling |
| `postcss` | high | line-parsing |
| `nanoid` | high | predictable IDs |
| `picomatch`, `@babel/core`, `react-router`, `react-router-dom` | high/low | transitive |

Most resolve via `npm audit fix` (non-breaking). `npm audit fix --force` would pull major
bumps (React 19, etc.) — **avoid** that flag for now.

**Note:** `frontend/node_modules` was not fully installed on the audit machine (`npm outdated`
showed `MISSING`), so the audit ran off `package-lock.json`. Re-run after a clean `npm ci` to confirm.

---

## Finding 6 — No automated scanning

- **No `dependabot.yml`**, no Snyk, no scheduled security workflow. Nothing tells the team when
  a new CVE lands or a package falls behind.
- Deps were last touched **~5 months ago** and no one noticed the drift.
- The existing CI (`eval.yaml`, `deploy-railway.yaml`) tests *functionality* but never *audits deps*.

This is the root cause the professor flagged ("we've never done this systematically"). A one-time
cleanup fixes today; **automation is what keeps it fixed.**

---

## Finding 7 — Environment / config inconsistencies

Minor, but worth noting while we're here:

- **Node version mismatch:** `Dockerfile` builds the frontend on `node:18-alpine`, but
  `deploy-railway.yaml` CI uses Node **20**. CI tests on a different Node than prod builds on.
- **Python:** consistent at 3.11 across Docker + CI ✅ (only the local conda env is 3.10 — a dev-machine issue, not prod).
- **GitHub Actions:** `setup-python@v4` in one workflow, `@v5` in another. Harmless but tidy it up.

---

## Recommendations (priority order)

1. **🥇 Establish one source of truth.** Regenerate a single pinned manifest from actual imports
   (drops the ~40 dead ChromaDB/AWS packages in the same step). Delete or clearly deprecate the
   unpinned `requirements.txt`. Simplify the confusing two-file Docker install.
2. **🥈 Apply the 🟢 safe security patches** (Finding 4) on a branch, verify with the test + eval
   suites, open a PR. *Do not merge to `main` without review — `main` auto-deploys to Railway.*
3. **🥉 Add automated scanning** — commit a `dependabot.yml` (config included in this audit folder)
   so Python + npm + Actions + Docker get weekly PRs going forward.
4. **Fix `npm audit` issues** with plain `npm audit fix` (not `--force`).
5. **Schedule the 🔴 major upgrades** (LangChain, openai 2.x, React 19) as *separate, deliberate*
   pieces of work with eval-suite validation. Resolve the openai 1.x-prod / 2.x-dev split explicitly.
6. **Align Node** to 20 in the Dockerfile to match CI.

---

## How to reproduce

```bash
# Backend — audit the pinned prod file under Python 3.11 (prod's version; older Python fails on numpy 2.3.2)
python3.11 -m venv /tmp/wb-audit && /tmp/wb-audit/bin/pip install pip-audit
/tmp/wb-audit/bin/pip-audit -r application/requirements_full.txt

# Frontend
cd frontend && npm ci && npm audit

# Confirm a package is truly unused before removing it
grep -rl "<import_name>" application/*.py application/managers application/adapters
```

Raw scanner output is saved under `docs/dependency-audit/raw/`.
