# WaterBot — Agile CI/CD & Testing Guidelines

**Who this document is for:**
- [Section 1 — Project Stakeholders](#section-1--project-stakeholder-guidelines): Process, sprint cycles, team rules, and deployment policies. No technical knowledge required.
- [Section 2 — Developers](#section-2--developer-technical-guidelines): Testing commands, CI/CD configuration, and implementation specifics.

---

# Section 1 — Project Stakeholder Guidelines

---

## Branch Strategy

Every change to WaterBot flows through a structured pipeline before it can reach users:

```
feature/name/ticket-id  ──▶  test  ──────────────────────▶  main
fix/name/description    ──▶  │    PR + 1 reviewer + tests    │
                             │                               │
                             ▼                               ▼
                      https://test.azwaterbot.org    https://azwaterbot.org
                      (Staging — us-west-2)          (Production — us-east-1)
```

**Rules — no exceptions:**

- Never commit directly to `test` or `main`
- Every change goes through a **Pull Request**
- PRs require **at least 1 reviewer approval**
- PRs require **all automated checks to pass** before merging

> **Why this matters:** Every change is reviewed by a human and verified by automated tests before it can affect users. If something breaks, the PR that caused it is identifiable and reversible.

---

## Automated Deployments

Both branches deploy automatically — no manual trigger needed:

| Event | What happens |
|---|---|
| Push to `test` | Automatically deploys to `https://test.azwaterbot.org` |
| Push to `main` | Automatically deploys to `https://azwaterbot.org` |

Pushes only happen via merged PRs — direct commits to either branch are not allowed.

---

## Sprint Cycle

| Day(s)            | Activity                         | Outcome                                       |
|-------------------|----------------------------------|-----------------------------------------------|
| Monday            | Sprint Planning                  | Features defined with acceptance criteria     |
| Tuesday–Thursday  | Development                      | Work done on feature branches                 |
| Friday            | Code freeze + PR review day      | All PRs reviewed; staging testing begins      |
| Following Monday  | Demo + Retrospective             | Prod deploy approved only if staging is clean |

---

## Definition of "Done"

A feature is **not done** until all five of these are true:

1. **Code is merged to `test` via a reviewed Pull Request**
   — ensures a peer has checked the work before it advances

2. **Automated tests pass in CI**
   — tests run automatically on every push; no human approval needed to run them

3. **The feature works on the staging environment**
   — staging (`test.azwaterbot.org`) is a full copy of production; test there first

4. **A teammate has manually verified the feature on staging**
   — a second person confirms the feature behaves correctly

5. **No regressions in existing automated tests**
   — nothing that worked before has been broken

---

## Pull Request Checklist

Before opening a PR, the author confirms:

- [ ] I tested this locally in the browser
- [ ] I ran the automated tests and they all passed
- [ ] The feature works on `https://test.azwaterbot.org`
- [ ] My PR description clearly explains **what** changed and **why**
- [ ] I did not skip any tests or disable any linting rules

---

## Team Rules (Non-Negotiable)

### If You Find a Bug

1. **Do not report it verbally** — verbal reports get lost and can't be tracked
2. Open a **GitHub Issue** with: steps to reproduce, expected vs. actual behavior, and a screenshot
3. The fix goes through the normal flow: feature branch → PR → tests → staging → prod

### Before Merging to Main (Production)

1. Your change must already be on **`https://test.azwaterbot.org`** (merged to `test`)
2. Manually test the specific feature you changed on the staging URL
3. Tell the team: *"I'm opening a PR to main — I tested X and Y on staging"*
4. Get **1 teammate to also verify** the feature on staging
5. Only then open the PR from `test` → `main`

### If Tests Are Failing

- **Do not bypass, disable, or comment out failing tests**
- Fix the root cause — or flag it in your PR so a reviewer can weigh in
- If you believe the test itself is wrong, update it — but explain why in the PR description

---

## Quick Reference — Before Every Production Deploy

> **Five steps. Always.**
>
> 1. Run automated tests locally — all must be green
> 2. Merge your feature PR to `test` first
> 3. Test your specific change manually on `https://test.azwaterbot.org`
> 4. Get a teammate to verify it too
> 5. Then open a PR from `test` → `main`
>
> **Reporting a bug in production without prior staging verification = the PR that caused it gets reverted.**

---
---

# Section 2 — Developer Technical Guidelines

> For implementation details, CI/CD configuration, and testing commands. See [Section 1](#section-1--project-stakeholder-guidelines) for team process rules.

---

## Environments

| Environment | Branch | URL | AWS Region |
|---|---|---|---|
| Staging | `test` | https://test.azwaterbot.org | us-west-2 |
| Production | `main` | https://azwaterbot.org | us-east-1 |

---

## CI/CD Workflows

Both workflows trigger automatically on push to their respective branch:

| Workflow file | Triggers on | GitHub Environment | ECS Cluster |
|---|---|---|---|
| `deploy-waterbot-dev.yaml` | push to `test` | `aws-test-deploy` | `cdk-app-stack-dev-WaterbotFargateCluster8D18135A-Rh49QXMfHkSP` |
| `deploy-waterbot-prod.yaml` | push to `main` | `aws-prod-deploy` | `cdk-app-stack-dev-WaterbotFargateCluster8D18135A-qC2WwpVI2CWn` |

Both environments are configured with `ECR_ACCOUNT_ID`, `ECR_REPO`, `ECS_SERVICE`, and `AWS_ROLE_ARN` in GitHub → Settings → Environments.

---

## Testing Stack

| Layer          | Tool       | Location                  | Run Command                     |
|----------------|------------|---------------------------|---------------------------------|
| Frontend E2E   | Playwright | `frontend/tests/`         | `npx playwright test`           |
| Frontend unit  | Vitest *(add this)* | `frontend/src/__tests__/` | `npm run test:unit`  |
| Backend API    | pytest     | `application/tests/`      | `pytest -v` (from `application/`) |
| Manual QA      | Staging env | test.azwaterbot.org      | Manual browser verification     |

---

## Frontend Testing — Playwright E2E

Existing test files to reference: `frontend/tests/mic-animation.spec.js`, `frontend/tests/logo.spec.js`

### Priority 1 — Must pass before any production deploy

- [ ] Page loads and splash screen renders
- [ ] Chat input submits a message (mock the API response)
- [ ] Bot response appears in the chat window
- [ ] Language toggle switches between English and Spanish
- [ ] Microphone button opens the recording modal

### Priority 2 — Run when modifying these features

- [ ] Thumbs up/down rating buttons function correctly
- [ ] Download transcript link appears after a chat session
- [ ] Mobile layout renders without overflow or clipping
- [ ] Header links and dropdown open/close correctly

### Running tests

```bash
cd frontend
npx playwright test                      # run all tests
npx playwright test --reporter=html      # generate visual report in playwright-report/
npx playwright test --debug              # step through tests interactively
npx playwright test tests/specific.js   # run a single file
```

---

## Backend Testing — pytest

Tests live in `application/tests/` and use `httpx` + `pytest-asyncio` to test
the FastAPI app in-process — no real OpenAI, Bedrock, or PostgreSQL connections are made.

### Setup

```bash
cd application
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt   # pytest, pytest-asyncio, httpx
```

### Running tests

```bash
pytest -v                    # run all backend tests (from application/)
pytest -v -s                 # include print/log output
pytest -k "test_chat"        # filter by name pattern
```

### What is tested

| Endpoint | Test |
|---|---|
| `GET /` | Responds with 200 or redirect |
| `POST /chat_api` | Returns `{resp, msgID}` with 200; msgID increments per session |
| `POST /chat_api` | Handles `language_preference=es` |
| `GET /messages` | Returns 401 without Basic Auth credentials |
| `POST /session-transcript` | Returns graceful empty-session message |
| `POST /translate` | Returns 400 for invalid `target_lang`; 200 with translations list for valid requests |
| `POST /submit_rating_api` | Returns `{status: success}` when DynamoDB is not configured |

### Adding new tests

Add test cases to `application/tests/test_api.py`. Use `async def test_*` methods
inside a class or at module level — `asyncio_mode = auto` is configured in `pytest.ini`.

The `client` fixture in `conftest.py` provides a pre-configured `httpx.AsyncClient`
wired to the FastAPI app. All external I/O (OpenAI, Bedrock, psycopg2) is mocked.

---

## Developer Quick Reference

```bash
# Run all frontend E2E tests
cd frontend && npx playwright test

# Run with visual HTML report
cd frontend && npx playwright test --reporter=html

# Debug a failing test interactively
cd frontend && npx playwright test --debug

# Run all backend tests
cd application && source .venv/bin/activate && pytest tests/ -v

# Start local dev environment (two terminals)
cd frontend && npm run dev             # port 5173
cd application && fastapi dev main.py  # port 8000
```

**Before opening a PR:** all local tests must be green.
**After merging to `test`:** verify your change on `https://test.azwaterbot.org`.
