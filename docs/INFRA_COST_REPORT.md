# WaterBot Infrastructure Cost Report

## TL;DR

The current AWS setup costs an estimated **$300–370/month** to run a chatbot that realistically
needs about **$15–40/month** of compute. The overspend is driven by enterprise-grade defaults
(Multi-AZ RDS, 2–4 Fargate tasks, NAT Gateways, ALB) applied to a project that serves a small
number of concurrent users. Moving to Railway, Render, or a self-hosted VPS would cut the bill
by 85–95% with zero loss of capability at this scale.

---

## Current AWS Cost Breakdown

### Resource Inventory (from `iac/cdk/stacks/app_stack.py`)

| Resource | Spec | Why it exists |
|----------|------|---------------|
| ECS Fargate | **2 tasks minimum, up to 4** — 2 vCPU + 4 GB RAM each | App container |
| RDS PostgreSQL | **t3.small, Multi-AZ**, 20 GB, 30-day backups | Message storage |
| Application Load Balancer | Standard ALB | Routes traffic to Fargate |
| VPC with 2 private subnets | max_azs=2, private with egress | Fargate + RDS networking |
| NAT Gateway × 2 | One per AZ (required for private subnets) | Outbound internet for containers |
| CloudFront | CDN distribution | Static asset caching + HTTPS |
| DynamoDB | Pay-per-request | Ratings/feedback |
| S3 × 3 buckets | Export, transcripts, Postgres backups | Storage |
| Lambda × 3 | dynamo_export, db_init, postgres_backup | Automation |
| Secrets Manager × 3 | OpenAI key, DB creds, Basic Auth | Secret injection |
| ECR | Container registry | Docker image storage |
| CloudWatch Logs | Container + RDS logs | Observability |
| EventBridge + SQS × 2 | Scheduled backup rules + DLQs | Scheduling |

### Monthly Cost Estimate (us-east-1, Feb 2026 pricing)

| Service | Monthly Cost | Notes |
|---------|-------------|-------|
| ECS Fargate (2 tasks × 2 vCPU × 4 GB, 24/7) | **~$142** | $0.04048/vCPU-hr + $0.004445/GB-hr |
| RDS t3.small Multi-AZ | **~$100** | Multi-AZ doubles the single-AZ ~$50 cost |
| NAT Gateways × 2 | **~$65** | $0.045/hr each, required for private subnets |
| Application Load Balancer | **~$18** | $0.0225/hr fixed + LCU charges |
| CloudWatch Logs | **~$8** | Log ingestion + storage |
| Secrets Manager | **~$2** | $0.40/secret/month × 3 |
| S3 (3 buckets) | **~$3** | Storage + requests at low traffic |
| DynamoDB | **~$2** | Pay-per-request at low traffic |
| CloudFront | **~$2** | Low traffic, mostly free tier |
| ECR | **~$1** | Single image, small storage |
| Lambda, EventBridge, SQS | **~$0** | Well within free tiers |
| **Total** | **~$343/month** | **~$4,116/year** |

> **Note:** This does not include data transfer costs, which can add $10–30/month depending on traffic.

---

## Why This Is Overkill

### 1. Two Fargate Tasks Running 24/7 for a Low-Traffic Chatbot

The CDK stack sets `desired_count=2` with auto-scaling up to 4 tasks. Each task has 2 vCPU and
4 GB RAM. WaterBot is a FastAPI async app — a **single task with 1 vCPU and 1 GB RAM** can handle
hundreds of concurrent users without breaking a sweat. The second task exists for high-availability
reasons that only matter at scale.

**Overspend: ~$71/month for the second idle task.**

### 2. Multi-AZ RDS for a Non-Critical Read-Heavy Workload

Multi-AZ RDS runs an identical standby replica in a second availability zone and automatically
fails over if the primary goes down. Failover takes 60–120 seconds. For a chatbot that stores
chat messages (not financial transactions), this level of availability is unnecessary. A single-AZ
`t3.micro` or `t3.small` with daily backups is entirely sufficient.

**Overspend: ~$50/month for the Multi-AZ standby.**

### 3. NAT Gateways ($65/month to Give Containers Internet Access)

The VPC uses private subnets for Fargate and RDS, which is the secure default. But private subnets
require NAT Gateways for outbound internet (to call OpenAI, Bedrock, etc.), and NAT Gateways cost
$0.045/hour each. With 2 AZs that's $64.80/month — more than many competing platforms charge for
an entire hosted app.

**Alternative:** Use public subnets with security groups (marginally less "enterprise" but
perfectly secure for a public-facing chatbot) and pay $0 for NAT.

### 4. Application Load Balancer for a Single Service

The ALB routes traffic to the ECS service and enables the custom-header security check. At this
scale a simple reverse proxy (nginx, Caddy) in front of the container does the same job for free.

**Overspend: ~$18/month.**

### 5. DynamoDB for Ratings Storage

DynamoDB is pay-per-request at this scale so cost is minimal, but it adds operational complexity
(separate IAM, separate SDK calls, separate backup logic) for a table that could trivially be a
second table in the existing PostgreSQL database.

---

## Alternative Platform Comparison

### Option A — Railway

Railway runs Docker containers directly and includes managed PostgreSQL.

| Component | Solution | Cost |
|-----------|----------|------|
| FastAPI app | Railway service (1 vCPU, 512 MB–1 GB RAM) | ~$5–10/month |
| PostgreSQL | Railway managed Postgres | ~$5–10/month |
| Static files / CDN | Cloudflare free tier (proxy in front) | $0 |
| Secrets | Railway environment variables | $0 |
| **Total** | | **~$10–20/month** |

**Pros:** Deploys from Dockerfile with zero config changes to the app. GitHub integration built
in. Managed Postgres with connection pooling. Automatic SSL.

**Cons:** No built-in multi-region. Occasional cold starts on Hobby plan (solvable on Pro).
Less control over networking. No Bedrock (would need to keep AWS credentials for KB calls — but
that's just env vars, not infrastructure).

**Migration effort:** Low. Change the `DATABASE_URL` env var, deploy the existing Dockerfile.

---

### Option B — Render

Similar to Railway but slightly more traditional PaaS feel. Existing `render.yaml` was already
in the repo (now deleted) suggesting it was evaluated before.

| Component | Solution | Cost |
|-----------|----------|------|
| FastAPI app | Render Web Service (Starter: 512 MB RAM) | $7/month |
| PostgreSQL | Render managed Postgres (Starter: 256 MB RAM, 1 GB storage) | $7/month |
| CDN | Render includes global CDN on all web services | $0 |
| **Total** | | **~$14/month** |

**Pros:** Persistent disk, always-on (no sleep on paid plan), GitHub auto-deploy, built-in
health checks. Familiar — the project had a `render.yaml` at some point.

**Cons:** Starter Postgres is quite small. Standard tier ($20 DB + $25 service) brings it to
$45/month but with much better specs.

---

### Option C — Supabase + Fly.io

Supabase handles the PostgreSQL database with a generous hosted offering; Fly.io handles the
container.

| Component | Solution | Cost |
|-----------|----------|------|
| FastAPI app | Fly.io (shared-cpu-2x, 512 MB) | ~$11/month |
| PostgreSQL | Supabase Pro ($25/month: 8 GB DB, 100 GB storage, 250 GB bandwidth) | $25/month |
| CDN | Cloudflare free tier | $0 |
| **Total** | | **~$36/month** |

**Pros:** Supabase gives you a proper managed Postgres with REST API, realtime, auth, and a
dashboard — useful if the project grows. Fly.io has excellent multi-region support and Anycast
networking. Persistent volumes available.

**Cons:** Two platforms to manage. Supabase Pro is slightly expensive for just using it as a
plain Postgres. But if the project ever wants to use Supabase Auth or realtime features, the
$25 becomes excellent value.

---

### Option D — Self-Hosted VPS (Hetzner / DigitalOcean / Linode)

Run the entire stack on a single VPS with Docker Compose.

| Component | Solution | Cost |
|-----------|----------|------|
| VPS (Hetzner CX22: 2 vCPU, 4 GB RAM, 40 GB SSD) | Docker Compose: FastAPI + Postgres + nginx | €5.92/month (~$6.50) |
| Backups (Hetzner automated) | Daily snapshot | +€1.18/month |
| Domain / SSL | Caddy auto-HTTPS | $0 |
| CDN (optional) | Cloudflare free tier | $0 |
| **Total** | | **~$8–10/month** |

**Pros:** Cheapest option by far. Full control. No vendor lock-in. Postgres running on the same
machine means zero network latency between app and DB. Hetzner has excellent uptime and is based
in the EU (GDPR-friendly).

**Cons:** You own the ops. OS patching, Postgres upgrades, disk management, and monitoring are
your responsibility. No managed failover — if the VPS goes down, the app goes down until you
restart it (typically 2–5 minutes with Hetzner's SLA).

**Required compute for WaterBot:**
- FastAPI (async) handles ~100–200 concurrent users on 1 vCPU
- PostgreSQL for chat messages: ~256 MB RAM is sufficient
- Total Docker Compose stack: comfortably fits in 2 GB RAM
- The CX22 (4 GB RAM, 2 vCPU) has 50% headroom

---

## Side-by-Side Comparison

| | **Current AWS** | **Railway** | **Render** | **Supabase + Fly.io** | **Self-Hosted (Hetzner)** |
|-|-----------------|-------------|------------|----------------------|--------------------------|
| **Monthly cost** | ~$343 | ~$15 | ~$14–45 | ~$36 | ~$10 |
| **Annual cost** | ~$4,116 | ~$180 | ~$168–540 | ~$432 | ~$120 |
| **Migration effort** | — | Low | Low | Medium | Medium |
| **Ops burden** | Low (managed) | Low | Low | Low | High |
| **Scalability** | Excellent | Good | Good | Good | Manual |
| **HA / failover** | Enterprise | Basic | Basic | Basic | None |
| **Bedrock KB** | Native | Env vars only* | Env vars only* | Env vars only* | Env vars only* |
| **Postgres included** | RDS managed | Managed | Managed | Supabase managed | Self-managed |
| **Docker deploy** | Yes (ECR) | Yes (Dockerfile) | Yes (Dockerfile) | Yes (Fly.io) | Yes (Compose) |
| **Custom domain + SSL** | Yes (CloudFront) | Yes | Yes | Yes | Yes (Caddy) |

> *Bedrock KB is AWS-only. On any non-AWS platform you still call it via boto3 with `AWS_ACCESS_KEY_ID` /
> `AWS_SECRET_ACCESS_KEY` environment variables. No infra change needed — just credentials.

---

## What You'd Lose Moving Off AWS

| Feature | Impact | Mitigation |
|---------|--------|------------|
| Bedrock Knowledge Base | None — it's an API call, not infra | Keep AWS credentials as env vars |
| Multi-AZ RDS failover | 60–120s downtime if DB host fails | Nightly backups + restore is sufficient at this scale |
| ECS auto-scaling | App can't automatically add containers under load | A single well-sized container handles this traffic |
| CloudWatch Logs | Lose centralised AWS logging | Use Papertrail, Logtail, or self-hosted Loki (free tiers available) |
| ALB custom header auth | Lose the `X-Custom-Header` protection layer | Replace with the existing CloudFront basic auth |

---

## Recommendation

**Short term (easiest):** Move to **Railway** (~$15/month). Zero code changes. Deploy the
existing Dockerfile, set `DATABASE_URL` to Railway's managed Postgres, keep the same
`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_KB_ID` env vars for Bedrock calls.
Estimated annual saving: **~$3,936**.

**Long term (most control):** **Hetzner VPS + Docker Compose** (~$10/month). Requires setting
up nginx/Caddy, Postgres, and a simple systemd unit for auto-restart, but gives you maximum
control and the lowest cost. Postgres and the app run on the same machine — simpler, faster, no
NAT fees. Estimated annual saving: **~$3,996**.

**If the project grows significantly** (thousands of daily users, uptime SLA required): revisit
AWS but with a right-sized setup — one Fargate task, single-AZ RDS, public subnets (no NAT),
no ALB (use CloudFront directly to the container). That cuts the AWS bill to ~$60–80/month.

---

## Annual Savings Summary

| Move to | Monthly | Annual saving vs AWS |
|---------|---------|---------------------|
| Railway | ~$15 | **$3,936** |
| Render | ~$14–45 | **$3,576–3,948** |
| Supabase + Fly.io | ~$36 | **$3,684** |
| Self-hosted Hetzner | ~$10 | **$3,996** |
