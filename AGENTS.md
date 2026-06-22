# Hirenovik — Complete Project Documentation & Audit

Job market analytics platform for LATAM tech jobs. Production scraper running daily via GitHub Actions. Evolving into full AWS data pipeline + XGBoost ML product.

**Project name:** Hirenovik (invented name — unique, ownable)
**Student:** Edgar, 6th semester Data Engineering & AI, Universidad de Guanajuato
**Deadline:** May 28, 2026
**AWS Budget:** $150 USD
**Goal:** Cloud computing final project + entrepreneurship class + portfolio

---

## Table of Contents

1. [Commands](#commands)
2. [Execution Modes](#execution-modes)
3. [Architecture & Directory Layout](#architecture--directory-layout)
4. [Two-Phase Distributed Scraping Architecture](#two-phase-distributed-scraping-architecture)
5. [Data Flow](#data-flow)
6. [Worker Routing](#worker-routing)
7. [Database Schema & Indexes](#database-schema--indexes)
8. [Scrapers Detail](#scrapers-detail)
9. [ETL Pipeline](#etl-pipeline)
10. [Anti-Ban Strategy](#anti-ban-strategy)
11. [NLP Pipeline](#nlp-pipeline)
12. [ML Strategy (XGBoost Salary Prediction)](#ml-strategy-xgboost-salary-prediction)
13. [AWS Infrastructure (Terraform)](#aws-infrastructure-terraform)
14. [CI/CD — GitHub Actions](#cicd--github-actions)
15. [Supabase → S3 Export](#supabase--s3-export)
16. [Tracking CLI](#tracking-cli)
17. [Product Roadmap](#product-roadmap)
18. [GitHub Branch Strategy](#github-branch-strategy)
19. [Data Audit & Analysis (sql_results.md)](#data-audit--analysis-sql_resultsmd)
20. [Senior Engineer Audit: Code Quality & Risks](#senior-engineer-audit-code-quality--risks)
21. [$150 Budget Cost Analysis](#150-budget-cost-analysis)
22. [Pre-Deployment Infrastructure Checklist](#pre-deployment-infrastructure-checklist)
23. [Known Fixes Applied](#known-fixes-applied)
24. [Gotchas & Warnings](#gotchas--warnings)

---

## Commands

```bash
# Activate venv
source .venv/bin/activate

# Run main pipeline (reads EXECUTION_MODE from .env)
python src/main.py

# Run ETL audit (data quality checks)
python src/etl/audit.py

# Run interactive job tracker (mark APPLIED, show priorities)
python scripts/tracker.py

# Fix known bugs before running tracker.py:
#   - Line 1: remove debug print
#   - Import: from src.database.models import db_connect, Job
#   - julianday() → EXTRACT(DAY FROM ...)

# Supabase → S3 export (requires AWS creds)
python src/data_ingestion/supabase_to_s3.py

# NLP text cleaning
python nlp_module/src/01_text_cleaner.py
python nlp_module/src/01_text_cleaner.py --dry-run
python nlp_module/src/01_text_cleaner.py --sample 300

# NLP lemmatization
python nlp_module/src/02_nlp_processor.py

# Docker
docker compose up --build
# or
docker build -t hirenovik-scout .
docker run --rm --env-file .env -e WORKER_NAME=GitHub_Actions -e EXECUTION_MODE=cloud_extraction hirenovik-scout

# Mac double-click runner
./run_bot.command

# Lint & format
make lint
make fmt

# Terraform
terraform -chdir=infrastructure/environments/dev init
terraform -chdir=infrastructure/environments/dev plan
terraform -chdir=infrastructure/environments/dev apply
terraform -chdir=infrastructure/environments/dev destroy

# ML Training (requires SAGEMAKER_ROLE_ARN)
SAGEMAKER_ROLE_ARN=arn:aws:iam::... python src/ml/training/train.py
python src/ml/training/train.py --no-train  # prepare data only

# Run tests
pytest
pytest -v
pytest --cov=src --cov-report=term-missing

# Test endpoint
ENDPOINT_NAME=hirenovik-salary-endpoint-dev python src/ml/inference/test_endpoint.py

# Plans (build instructions for current phase)
cat plans/plan.md
```

---

## Execution Modes

`EXECUTION_MODE` env var controls what the pipeline does:

| Mode | Where | What Runs |
|------|-------|-----------|
| `cloud_extraction` | GitHub Actions (datacenter IP) | JobSpy(Indeed) + Computrabajo Phase1 + OCC Phase1 |
| `local_full` | Residential IP | JobSpy(Indeed+LinkedIn Mon) + Phase2 enrichment + CSV export |
| `local_enrichment_only` | Residential IP | Phase2 only: reads PENDING_ENRICHMENT from DB, visits detail pages |

**Worker routing:** `WORKER_NAME` env var selects the keyword set. Each worker covers a different niche (see Worker Routing section).

---

## Architecture & Directory Layout

```
bajio-industrial-scout-pipeline/
├── src/                                       ← Main application code
│   ├── main.py                                ← Traffic controller, reads EXECUTION_MODE
│   ├── scrapers/
│   │   ├── __init__.py                        ← Exports BaseScraper, ComputrabajoScraper, OCCScraper
│   │   ├── base_scraper.py                    ← ABC with validate_output(), 12 required columns
│   │   ├── jobspy_scraper.py                  ← Indeed + LinkedIn via python-jobspy v1.1.82
│   │   ├── computrabajo_scraper.py            ← requests+BS4, 2-phase, LATAM multi-country (325 lines)
│   │   ├── occ_scraper.py                     ← cloudscraper+BS4 (TLS fingerprint bypass), 2-phase, MX only (265 lines)
│   │   └── pipeline.py                        ← run_pipeline / run_cloud_extraction / run_local_enrichment (326 lines)
│   ├── etl/
│   │   ├── extract.py                         ← Calls scout_jobs() from jobspy_scraper
│   │   ├── transform.py                       ← clean(), detect_state(), detect_job_type(), transform_data() (144 lines)
│   │   ├── loaders.py                         ← load_data() with ON CONFLICT DO NOTHING
│   │   ├── audit.py                           ← Data quality checks (nulls, duplicates, salary coverage) (65 lines)
│   │   └── text_cleaner.py                    ← Legacy text cleaner (NLP module preferred now) (456 lines)
│   ├── database/
│   │   ├── models.py                          ← SQLAlchemy Job model + db_connect() + create_tables() (96 lines)
│   │   └── operations.py                      ← mark_jobs_as_notified() (NEW → NOTIFIED)
│   ├── shared/
│   │   └── config.py                          ← ALL centralized configuration (127 lines)
│   ├── reporting_legacy/
│   │   ├── csv_export.py                      ← Exports NEW/APPLIED jobs to reports/job_report_{date}.csv
│   │   ├── pdf_report.py                      ← Generates PDF reports (fpdf2), currently NOT called from main.py
│   │   └── email_sender.py                    ← Sends PDF via Gmail SMTP, currently NOT called from main.py
│   ├── data_ingestion/
│   │   └── supabase_to_s3.py                  ← V2 incremental Supabase → S3 CSV export (307 lines)
│   ├── api/                                   ← Placeholder for FastAPI backend (v2)
│   ├── frontend/                              ← Placeholder for Streamlit (v1)
│   ├── glue_jobs/
│   │   └── clean_and_curate.py                ← PySpark clean + dedup + feature engineering (136 lines)
│   ├── lambda_functions/
│   │   └── inference/handler.py               ← S3 → SageMaker → SNS, error → SQS DLQ (96 lines)
│   ├── ml/
│   │   ├── training/train.py                  ← XGBoost training script via boto3 SageMaker (244 lines)
│   │   ├── inference/test_endpoint.py         ← Invoke SageMaker endpoint with sample features (123 lines)
│   │   └── training/train_local.py             ← Local XGBoost trainer (AWS ml.m5.large quota workaround)
│   ├── step_functions/
│   │   └── workflow.json                      ← Reference JSON (historical, Terraform is source of truth)
├── nlp_module/                                ← Independent NLP module (its own venv)
│   ├── requirements.txt
│   └── src/
│       ├── 01_text_cleaner.py                 ← Removes markdown/URLs, parses location, detects language (456 lines)
│       └── 02_nlp_processor.py                ← Stopword removal + lemmatization via simplemma (468 lines)
├── scripts/
│   └── tracker.py                             ← Interactive CLI: show new jobs, mark APPLIED, follow-up priorities (126 lines)
├── infrastructure/                            ← Terraform IaC
│   ├── backend-setup/                         ← S3 bucket + DynamoDB for remote Terraform state
│   │   ├── main.tf                            ← Full backend infra with logging, encryption, lifecycle policies (297 lines)
│   │   └── variables.tf                       ← Configurable: bucket name, region, retention days
│   ├── environments/
│   │   └── dev/
│   │       ├── main.tf                        ← Provider config, calls all 5 modules (66 lines)
│   │       ├── variables.tf                   ← aws_region=us-east-1, environment=dev, model_artifact_path
│   │       └── backend.tf                     ← Remote state: s3://hirenovik-tf-state-edgar-alfaro-2026/dev/
│   └── modules/
│       ├── storage/                           ← 5 S3 buckets: raw, curated, models (versioned), outputs, input
│       │   ├── main.tf (111 lines), variables.tf, outputs.tf
│       ├── data_engineering/                  ← Glue Crawler + Glue Job + IAM (PySpark clean_and_curate)
│       │   ├── glue_crawler.tf (37 lines), glue_job.tf (36 lines), iam.tf (96 lines), variables.tf, outputs.tf
│       ├── ml_inference/                      ← SageMaker Serverless + Lambda + SNS + SQS + IAM
│       │   ├── sagemaker.tf (50 lines), lambda.tf (142 lines), sns.tf, sqs.tf, iam.tf (103 lines), variables.tf, outputs.tf
│       ├── orchestration/                     ← Step Functions state machine + IAM
│       │   ├── step_functions.tf (135 lines), iam.tf (91 lines), variables.tf, outputs.tf
│       └── observability/                     ← CloudWatch Dashboard + Alarms + S3 metrics
│           ├── dashboard.tf (106 lines), alarms.tf (57 lines), s3_metrics.tf, variables.tf, outputs.tf
├── reports/                                   ← Generated CSV/PDF reports (gitignored but some committed)
├── tests/
│   ├── conftest.py                             ← Shared pytest fixtures (DataFrame, DB session)
│   ├── test_transform.py                       ← 37 tests: clean, detect_state, detect_job_type, salary extract
│   ├── test_salary_parsing.py                  ← 20 tests: _parse_salary both scrapers, NaN regression
│   ├── test_loaders.py                         ←  5 tests: load_data dedup, rollback, rowcount fallback
│   ├── test_pipeline.py                        ← 10 tests: _map_phase1_records, status lifecycle
│   ├── test_glue_features.py                   ← 26 tests: salary mid, outlier filter, seniority, keywords
│   └── test_scrapers/                          ← HTML fixtures for OCC/Computrabajo scraper testing (7 files)
├── .github/workflows/
│   ├── daily_scout.yml                        ← Cron 12:17 UTC, cloud_extraction mode
│   ├── enrichment_local.yml                   ← Manual trigger, local_enrichment_only mode
│   └── s3_export.yml                          ← Cron 12:45 UTC, incremental Supabase → S3 export
├── .opencode/skills/                          ← AI assistant knowledge files
│   ├── project-context.md, aws-architecture.md, database-schema.md
│   ├── ml-strategy.md, product-vision.md, scraper-patterns.md
├── Dockerfile                                 ← python:3.12-slim, CMD python src/main.py
├── docker-compose.yml                         ← Builds + runs with .env file
├── requirements.txt                           ← ALL dependencies (39 packages, single root file)
├── .env.example                               ← Template with all env vars documented
├── .dockerignore
├── .gitignore
├── Makefile                                   ← lint, fmt, test, docker-build, docker-run targets
└── run_bot.command                            ← Double-click runner for macOS
```

---

## Two-Phase Distributed Scraping Architecture

This is the core architectural decision that makes the project work within constraints.

### Rationale
Job boards (Indeed, Computrabajo, OCC) aggressively block datacenter IPs (GitHub Actions) when you visit detail pages. But listing pages are generally safe from datacenter IPs. The solution: split scraping into two phases with different IP profiles.

### Phase 1 — Cloud Extraction (GitHub Actions, datacenter IPs)
- **When:** Daily at 6:17 AM CST via `daily_scout.yml`
- **What:** Scrapes listing cards ONLY — no detail page visits
- **Sources:** JobSpy (Indeed), Computrabajo Phase 1, OCC Phase 1
- **Speed:** Fast (~3-5 min for all 9 keywords across all scrapers)
- **Blocking risk:** Low — listing pages have minimal anti-bot protection
- **Output:** Records inserted into DB with `status='PENDING_ENRICHMENT'`
- **Description field:** Always NULL in Phase 1

### Phase 2 — Local Enrichment (Residential IPs)
- **When:** 2-3x per week, run manually from home/classmate machines
- **What:** Visits each detail page to extract full descriptions + recover missing salary data
- **Sources:** Computrabajo Phase 2 + OCC Phase 2
- **Speed:** Slow (~100 URLs = ~30 min including cooldowns)
- **Blocking risk:** Higher — but mitigated by residential IPs + delays
- **Circuit breaker:** 3 consecutive all-fail batches → 300s pause
- **Output:** Updates DB: `status='NEW'` (description found) or `status='ORPHANED'` (404/blocked)

### Two-Phase Data Flow Diagram

```
GitHub Actions (6:17 AM CST)
    │
    ├── JobSpy (Indeed) → 9 keywords × 25 = ~225 records
    │                    → status='NEW' (has description from JobSpy)
    │
    ├── Computrabajo Phase 1 → 9 keywords × ~30 = ~270 records
    │                        → status='PENDING_ENRICHMENT' (no description)
    │
    └── OCC Phase 1 → 9 keywords × ~35 = ~315 records
                     → status='PENDING_ENRICHMENT' (no description)
    
Residential IP (manual, 2-3x/week)
    │
    └── Read PENDING_ENRICHMENT from DB
         → Visit each detail page (batch 20, cooldown 60s)
         → Update: NEW (description found) or ORPHANED (404/blocked)
         → Limit: 100/run
```

### Why LinkedIn is Excluded from Phase 1
LinkedIn aggressively blocks datacenter IPs (proprietary bot detection). LinkedIn scraping only works from residential IPs and only on Mondays (`include_linkedin_today()` checks `datetime.now().weekday() == 0`). LinkedIn jobs also lack descriptions and salary data.

---

## Data Flow

### GitHub Actions (6 AM CST, cloud_extraction):
- Indeed: 9 keywords × 25 results = ~225 records (with descriptions, status=NEW)
- Computrabajo: 9 keywords × ~30 = ~270 records (status=PENDING_ENRICHMENT)
- OCC: 9 keywords × ~35 = ~315 records (status=PENDING_ENRICHMENT)
- Total: ~810 raw, ~600 new after dedup

### Local Enrichment (residential IP):
- Reads PENDING_ENRICHMENT records from DB
- Visits each URL for full description
- Recovers salary data from detail pages if missing
- Updates status: NEW or ORPHANED
- Limit: 100/run, batch 20, cooldown 60s, circuit breaker 3 fails → 300s sleep

### Data Export Pipeline (12:45 PM CST daily):
- Incremental Supabase → S3 CSV export
- Hive-style partitions: `ingestion_date=YYYY-MM-DD/`
- Checkpoint file tracks last exported `date_scraped`
- First run exports ALL records (~9k)

### AWS Pipeline (after infra deploy, runs on-demand via Step Functions):
1. Glue Crawler scans new S3 exports
2. Glue Job cleans + dedups + feature engineers → Parquet
3. XGBoost training on SageMaker (if training data prepared)
4. Notification via SNS

---

## Worker Routing

`WORKER_NAME` env var selects the search config. Each classmate runs from their residential IP:

| Worker | Keywords | Niche | Phase 2 IP |
|--------|----------|-------|-----------|
| `GitHub_Actions` | Data Engineer, Data Analyst, Analytics Engineer, Cloud Engineer, DevOps Engineer, Python Developer, React Developer, Cybersecurity Engineer, Business Intelligence | Multi-niche | N/A (datacenter) |
| `Edgar` | Data Engineer, Data Analyst, Analytics Engineer, Backend Developer | Ingeniería de Datos | Home |
| `Fercho` | Cloud Engineer, DevOps Engineer, Site Reliability Engineer, Arquitecto AWS | Infraestructura Cloud | Home |
| `Alexa` | Desarrollador Frontend, React Developer, iOS Developer, Android Developer | Desarrollo | Home |
| `Mazuca` | Desarrollador Backend, Python Developer, Java Backend, C# Backend | Desarrollo | Home |
| `Geraldine` | Cybersecurity Engineer, QA Automation, Business Intelligence, Product Manager | Ciberseguridad/BI | Home |

### How Worker Routing Works in Code
In `src/shared/config.py:23-99`, `get_search_config()` returns a list of `(keyword, location, niche)` tuples based on `WORKER_NAME`. The `run_cloud_extraction_pipeline()` iterates over all keywords. For each keyword, it runs JobSpy + Computrabajo Phase 1 + OCC Phase 1. The `scraped_by` field in the DB records which worker found the job.

**Default fallback** (unknown WORKER_NAME): Data Engineer + Cloud Engineer only.

---

## Database Schema & Indexes

### Connection
- **Provider:** Supabase PostgreSQL via SQLAlchemy ORM
- **Connection:** `DATABASE_URL` in `.env` (never commit — real credentials)
- **Pool:** pool_size=5, max_overflow=10, pool_pre_ping=True
- **URL fix:** Replace `postgres://` → `postgresql://` (SQLAlchemy 2.x deprecation)
- **Engine:** `create_engine()` with `pool_pre_ping=True` for connection health checks

### Table: `jobs`

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | BigInteger | PRIMARY KEY | Auto-increment |
| site | String(50) | | indeed, linkedin, computrabajo, occ |
| job_url | String | UNIQUE, NOT NULL | Dedup key — critical for idempotency |
| title | String | NOT NULL | Uppercased on insert via `str.upper()` |
| company | String | NOT NULL | Default: "Empresa confidencial" |
| raw_location | Text | | Original location string from listing card |
| country | String(50) | | Default: "México" |
| country_code | String(5) | | MX, CO, PE, CL, AR |
| state | String(50) | | Detected Mexican state (Guanajuato, Querétaro, Jalisco) |
| career | String(100) | | Data Engineer, Cloud Engineer, etc. |
| scraped_by | String(50) | | WORKER_NAME who found this job |
| industry_niche | String(50) | | Ingeniería de Datos, Infraestructura Cloud, etc. |
| is_premium | Boolean | | Default: False |
| job_type | String(20) | | remoto, hibrido, presencial |
| salary_min | Numeric | | |
| salary_max | Numeric | | |
| currency | String(10) | | MXN default, also COP, PEN, CLP, ARS |
| salary_source | String(20) | | structured, regex, none |
| description | Text | | Raw job description (NULL in Phase 1) |
| cleaned_description | Text | | Cleaned for NLP |
| keywords_json | JSONB | | Extracted tech keywords |
| date_posted | String | | Original posting date (free text from site) |
| date_scraped | DateTime(tz) | | auto-now via `func.now()` |
| last_updated | DateTime(tz) | | auto-now + onupdate |
| status | String(20) | | NEW, APPLIED, NOTIFIED, PENDING_ENRICHMENT, ORPHANED |

### Indexes
```sql
CREATE INDEX idx_niche_date ON jobs (industry_niche, date_scraped);
CREATE INDEX idx_geo_type ON jobs (country_code, state, job_type);
CREATE INDEX idx_career_scope ON jobs (career, job_type);
CREATE INDEX idx_status ON jobs (status);
```

### Dedup Strategy
```python
stmt = pg_insert(Job).values(records)
stmt = stmt.on_conflict_do_nothing(index_elements=["job_url"])
```
This means: if a `job_url` already exists, skip the insert silently. No updates, no upserts — the first record wins. This is intentional for the two-phase system: Phase 1 inserts first with `status='PENDING_ENRICHMENT'`, and Phase 2 later updates the same record.

### Status Lifecycle
```
Phase 1 insert → PENDING_ENRICHMENT
                      ↓
Phase 2 enrichment →  NEW      (description found)
                   →  ORPHANED (404/blocked)

JobSpy direct insert →  NEW (has description from library)
                           ↓
User applies via tracker →  APPLIED
                           ↓
(Optional) Email report →  NOTIFIED
```

---

## Scrapers Detail

### JobSpy (`src/scrapers/jobspy_scraper.py`, 95 lines)

**What it does:** Uses the `python-jobspy` library to scrape Indeed (daily) and LinkedIn (Mondays only).

**Key implementation details:**
- `scout_jobs(search_term, location, results_limit, include_linkedin, country_code)` returns a pandas DataFrame
- Country mapping: `{'MX': 'mexico', 'CO': 'colombia', 'PE': 'peru', 'CL': 'chile', 'AR': 'argentina'}`
- Results limit: 25 per search term (configurable via `SCRAPER_CONFIG["results_limit"]`)
- Hours old: 72 (filters out stale listings)
- Delays: `random.uniform(5, 15)` pre-request + `random.uniform(2, 5)` post-request
- On failure: returns empty DataFrame (graceful degradation)

**Why JobSpy for Indeed/LinkedIn:** JobSpy v1.1.82 abstracts the anti-detection complexity for these two sites. It handles TLS fingerprinting, CAPTCHAs, and rate limiting internally. Computrabajo and OCC are not supported by JobSpy, hence the custom scrapers.

**Limitation:** JobSpy does NOT return descriptions for LinkedIn jobs (LinkedIn API restriction). LinkedIn records inserted with `description=NULL`.

### Computrabajo (`src/scrapers/computrabajo_scraper.py`, 325 lines)

**Library:** `requests` + `BeautifulSoup` + `fake_useragent`

**Class hierarchy:** `ComputrabajoScraper(BaseScraper)` — extends the ABC

**Key implementation details:**

**Phase 1 — `scrape_metadata()`:**
- Iterates keywords × countries (MX, CO, PE, CL, AR)
- URL pattern: `https://{subdomain}.computrabajo.com/trabajo-de-{keyword-slug}?p={page}`
- Remote filter adds `-modalidad-teletrabajo` suffix
- Max pages: 5 (configurable via `MAX_PAGES_COMPUTRABAJO`)
- Selector: `div.box_offer` for listing cards
- Title/URL: `h2 a.js-o-link` → href
- Company/Location: `div.fs16 p.mt5` — first p.mt5 for company, second for location
- Salary: regex from `div.fs12.mt15 span.dIB` containing `$`
- Modality: `span.i_home` = Remoto, `span.i_home_office` = Híbrido
- Pagination: `span.b_primary.buildLink[data-path]`
- Delays: `random.uniform(2, 4)` per request
- **No detail page visits in Phase 1**

**Phase 2 — `enrich_descriptions()`:**
- Visits each URL from Phase 1
- Description selector: `#js_oferta ~ p.mbB` or `p.mbB`
- Salary recovery: regex scan of full page text for `$` patterns
- `"A convenir"` = negotiable → salary_raw = None
- Failed URLs → `{"description": None, "salary_raw": None}` (never crashes)
- Delays: `random.uniform(3, 6)` per request

**`_parse_salary()`:** Static method that extracts (min, max) from salary text. Uses `re.findall(r'\$?\s*([\d,]+\.?\d*)', text)`. Returns `(None, None)` for unparseable text.

**UA rotation:** `_get_headers()` calls `self.ua.random` on every request. No session-level UA — intentionally rotated per request.

### OCC Mundial (`src/scrapers/occ_scraper.py`, 265 lines)

**Library:** `cloudscraper` (TLS fingerprint bypass, Chrome emulation) + `BeautifulSoup`

**Class hierarchy:** `OCCScraper(BaseScraper)` — extends the ABC

**Key implementation details:**

**Phase 1 — `scrape_metadata()`:**
- MX only (hardcoded), currency MXN
- URL pattern: `https://www.occ.com.mx/empleos/de-{keyword-slug}/?page={page}`
- Remote filter adds `en-mexico-y-teletrabajo`
- Max pages: 5 (configurable via `MAX_PAGES_OCC`)
- Selector: `div[data-offers-grid-offer-item-container]` → card-level wrapper
- Title: `h2.text-grey-900.text-lg`
- URL: constructed from `data-id` attribute: `https://www.occ.com.mx/empleo/oferta/{data_id}/`
- Company: `div.col-span-10 div.h-\[21px\]` (note: escaped CSS class with `\\[` and `\\]`)
- Location: `div.no-alter-loc-text p`
- Salary: `span.mr-2.text-grey-900.font-base.font-light` with `$` check
- Date: `span.mr-2.text-sm.font-light`
- Delays: `random.uniform(2, 4)` per request
- **cloudscraper handles TLS fingerprinting with Chrome/Win emulation**

**Phase 2 — `enrich_descriptions()`:**
- Three-level selector fallback:
  1. `#Descripcion` (classic ID selector)
  2. `div[itemprop="description"]` (microdata selector)
  3. Text-anchored: find `<p>` containing "Descripción:" → parent `<div>`
  4. Fallback: `div.break-words` (Tailwind container)
- Salary recovery: same regex as Computrabajo
- Failed URLs → graceful None

**`_parse_salary()`:** Identical logic to Computrabajo's version.

### BaseScraper (`src/scrapers/base_scraper.py`, 23 lines)

**Abstract methods required by subclasses:**
```python
def scrape(self, keywords, countries, is_remote, max_results) -> pd.DataFrame
```

**`validate_output(df)`:**
- Ensures all 12 required columns exist (fills missing with None)
- Returns columns in standard order: site, job_url, title, company, raw_location, description, date_posted, salary_min, salary_max, currency, job_type, country_code

**IMPORTANT:** `scrape_metadata()` (Phase 1) does NOT call `validate_output()` — only `scrape()` (combined Phase 1+2) does. This allows Phase 1 to return raw DataFrames without column padding.

---

## ETL Pipeline

### Extract (`src/etl/extract.py`, 19 lines)
- Thin wrapper around `scout_jobs()` from jobspy_scraper
- Returns empty DataFrame on failure (graceful degradation)
- Only used for JobSpy extraction (not Computrabajo/OCC)

### Transform (`src/etl/transform.py`, 144 lines)

**Functions:**

| Function | Purpose |
|----------|---------|
| `clean(value, default)` | Handles `pd.isna()`, returns default if NaN |
| `normalize_text(value)` | `str(value).lower()` with None guard |
| `detect_job_type(title, location)` | Checks for remote/hybrid keywords in combined text |
| `detect_state(raw_location)` | Maps raw location → Mexican state (Guanajuato, Querétaro, Jalisco) |
| `extract_salary_from_text(description)` | Regex `$\s?(\d{1,3}(?:,\d{3})+)` to extract salaries from text |
| `transform_data(df, search_term, industry_niche)` | Full DataFrame → records transformation |

**`STATE_MAP` limitation:** Only maps 3 states (Guanajuato, Querétaro, Jalisco) and their cities. This is intentional for the Bajío focus but means most records get `state=NULL`.

**`detect_job_type()` limitation:** Only checks title + location for remote/hybrid keywords. OCC and Computrabajo have explicit job_type field on listing cards (from icon selectors), but JobSpy doesn't provide this — hence the keyword-based detection.

**`extract_salary_from_text()`:** Fallback for when JobSpy's salary parsing fails on Mexican salary format. The regex `$\s?(\d{1,3}(?:,\d{3})+)` only catches salaries formatted with commas (e.g., "$12,000"), but can miss single-number salaries or non-standard formatting.

### Load (`src/etl/loaders.py`, 29 lines)
- Uses `sqlalchemy.dialects.postgresql.insert` with `on_conflict_do_nothing(index_elements=["job_url"])`
- Returns `(inserted_count, skipped_count)`
- Wrapped in try/except with `session.rollback()` on error
- `rowcount` may be -1 depending on driver, falls back to `len(records)` for inserted count

### Pipeline Orchestrator (`src/scrapers/pipeline.py`, 326 lines)

**`run_pipeline(search_config, results_limit, include_linkedin=False)`:** 
- Legacy full pipeline: JobSpy extraction → transform → load
- Used by `local_full` mode

**`run_cloud_extraction_pipeline(search_config, results_limit)`:**
- Runs from GitHub Actions (datacenter IP)
- Iterates all keywords from search_config
- For each keyword: JobSpy → Computrabajo Phase 1 → OCC Phase 1
- JobSpy records go through `transform_data()` (full ETL with status=NEW)
- Computrabajo/OCC records go through `_map_phase1_records()` (status=PENDING_ENRICHMENT)
- Tracks inserted/skipped counts per scraper
- Summary log at end

**`_map_phase1_records(df, search_term, industry_niche)`:**
- Maps Phase 1 DataFrame → Job model dict list
- Handles job_type mapping (Remoto→remoto, Híbrido→hibrido, etc.)
- Sets `description=None`, `status='PENDING_ENRICHMENT'`
- Calls `clean()` and `detect_state()` for location normalization

**`run_local_enrichment_pipeline()`:**
- Queries DB for PENDING_ENRICHMENT records
- Groups by site (computrabajo, occ)
- Enforces daily_limit (100), batch_size (20), cooldown (60s)
- Circuit breaker: 3 consecutive all-fail batches → 300s sleep
- Success → updates description (+ recovered salary), sets status=NEW
- Failure (404/timeout) → sets status=ORPHANED
- Tracks enriched vs orphaned counts

---

## Anti-Ban Strategy

| Layer | Technique | Applied To | Code Location |
|-------|-----------|-----------|---------------|
| User-Agent | `fake_useragent` rotation per request | Computrabajo | `computrabajo_scraper.py:42-49` — `_get_headers()` |
| TLS fingerprint | `cloudscraper` Chrome/Win emulation | OCC | `occ_scraper.py:26-28` — scraper init |
| Request delays | `random.uniform(2-6s)` per request | Both scrapers | Phase 1: `random.uniform(2,4)`, Phase 2: `random.uniform(3,6)` |
| Batch cooldown | 60s sleep between groups of 20 | Phase 2 enrichment | `pipeline.py:309-310` |
| Daily limit | max 100 URLs per enrichment run | Phase 2 enrichment | `ENRICHMENT_CONFIG["daily_limit"]` |
| Circuit breaker | 3 consecutive all-fail batches → 300s pause | Phase 2 enrichment | `pipeline.py:289-303` |
| IP diversity | 4+ residential IPs from classmates | Phase 2 enrichment | Worker routing — each classmate runs from home |
| Datacenter safety | Phase 1 only from GitHub Actions | Phase 1 extraction | Architecture design — no detail pages from datacenter |
| Pre-request jitter | `random.uniform(5,15)s` before JobSpy | Indeed/LinkedIn | `jobspy_scraper.py:21-23` |
| Session isolation | Fresh `requests.Session()` per scraper instance | Computrabajo | `computrabajo_scraper.py:40` |

### Proven Effectiveness
The anti-ban strategy has been battle-tested:
- **Computrabajo Phase 1:** 1982 records extracted from datacenter IPs with 99.8% salary coverage — clearly not blocked
- **OCC Phase 1:** 1046 records extracted from datacenter IPs with 100% salary coverage — cloudscraper bypasses TLS fingerprinting effectively
- **Indeed via JobSpy:** 4435 records from datacenter IPs — JobSpy library handles anti-detection internally
- **LinkedIn:** Only 1715 records (Monday-only, likely blocked by LinkedIn's aggressive bot detection)

---

## NLP Pipeline

Both scripts in `nlp_module/src/` (requires `nlp_module/.venv/` — separate from main project venv).

### 01_text_cleaner.py (`nlp_module/src/01_text_cleaner.py`, 456 lines)

**Input:** `data/raw/jobs_rows.csv`
**Output:** `data/final/maestro_limpio.csv`

**Processing steps:**
1. Load CSV into pandas DataFrame
2. Parse location: extract city, state_code (GUA, DIF, JAL, etc.), region (Bajío, CDMX, Guadalajara, etc.)
3. Remove markdown, URLs, HTML entities, escaped characters, bullet points, hashtags
4. Detect language via `langdetect` (es, en, otro)
5. Flag `es_vacio=True` if description is missing/empty after cleaning
6. Flag `tiene_salario=True` if salary_min/salary_max are present
7. **Text NOT lemmatized or stopword-removed** — BERTopic needs complete sentences

**Region mapping:** Comprehensive mapping of 32 Mexican states + Bajío sub-regions:
- Bajío: GUA (Guanajuato), QRO (Querétaro), AGS (Aguascalientes), SLP (San Luis Potosí), ZAC (Zacatecas), MCH (Michoacán), JAL (Jalisco)
- CDMX, Monterrey, Guadalajara, etc.

### 02_nlp_processor.py (`nlp_module/src/02_nlp_processor.py`, 468 lines)

**Input:** `data/final/maestro_limpio.csv`
**Output:** `data/final/maestro_nlp.csv`

**Processing steps:**
1. Stopword removal (comprehensive ES + EN stopword lists + job-specific filter words)
2. Lemmatization via `simplemma` (lightweight, no spaCy dependency)
3. Output intended for: TF-IDF, word clouds, frequency analysis
4. Creates: `descripcion_nlp`, `titulo_nlp`, `texto_nlp`, `n_palabras_nlp`, `es_vacio_nlp`

### Usage Guide for Downstream Tasks

| Task | Module | Input |
|------|--------|-------|
| Bag of Words | 02_nlp_processor output | maestro_nlp.csv |
| TF-IDF | 02_nlp_processor output | maestro_nlp.csv |
| BERTopic | 01_text_cleaner output (complete sentences) | maestro_limpio.csv |
| LDA | 02_nlp_processor output | maestro_nlp.csv |
| K-Means clustering | 02_nlp_processor output | maestro_nlp.csv |
| Word clouds | 02_nlp_processor output | maestro_nlp.csv |
| Frequency analysis | 02_nlp_processor output | maestro_nlp.csv |

### Legacy NLP Code
`src/etl/text_cleaner.py` (456 lines) is a duplicate of `nlp_module/src/01_text_cleaner.py` from an earlier architecture. Do NOT use it. The NLP module is the canonical source.

---

## ML Strategy (XGBoost Salary Prediction)

### Training Script (`src/ml/training/train.py`, 244 lines)

**Algorithm:** SageMaker built-in XGBoost v1.7-1 (no custom container needed)

**Target variable:** `salary_mid_usd` (midpoint of salary_min/salary_max converted to USD)

**Features (41 total):**
```python
FEATURE_COLUMNS = [
    "seniority",        # 0-3 (junior=0, semi-senior=2, senior=3, default=1)
    "modality",         # 0-2 (remoto=0, hibrido=1, presencial=2)
    "years_experience", # mapped from seniority (junior=0, mid=2, ssr=4, senior=6)
] + [f"has_{kw}" for kw in KEYWORD_FEATURES]  # 39 binary keyword features
```

**Keyword features (39):**
```
python, aws, spark, docker, sql, tensorflow, kubernetes, airflow, dbt,
kafka, azure, gcp, pytorch, scikit, pandas, hadoop, snowflake, bigquery,
redshift, terraform, jenkins, git, linux, mlops, databricks, powerbi,
tableau, mongodb, postgresql, mysql, react, nodejs, flask, django,
fastapi, go, rust, java, scala
```

**Data pipeline:**
1. `load_parquet(bucket)` → reads all Parquet files from `s3://{curated_bucket}/jobs/`
2. `prepare_features(df)` → filters to training candidates (has salary + positive salary)
3. `upload_training_data(df, ...)` → 70/20/10 stratified split → CSV upload to S3
4. `launch_training_job(...)` → creates SageMaker training job with XGBoost

**Hyperparameters:**
```python
{
    "objective": "reg:squarederror",
    "num_round": "100",
    "max_depth": "6",
    "eta": "0.1",
    "subsample": "0.8",
    "colsample_bytree": "0.8",
    "gamma": "0",
    "min_child_weight": "1",
    "eval_metric": "rmse",
}
```

**Training instance:** `ml.m5.large` (1 instance, 20GB volume, 3600s max runtime)

**Metrics to monitor:** RMSE, MAE, R²

**Training data source:** `s3://hirenovik-curated-dev/jobs/` (Parquet, partitioned by `ingestion_date`)

**NOTE:** The training script uploads data to `s3://hirenovik-raw-dev/training-data/{timestamp}/` while the Step Functions pipeline expects it at `s3://hirenovik-curated-dev/training-data/train/` and `validation/`. This inconsistency must be fixed before running the automated pipeline.

### Inference Lambda (`src/lambda_functions/inference/handler.py`, 96 lines)

**Trigger:** S3 `.json` file uploaded to `hirenovik-input-dev/`

**Flow:**
1. Read JSON from S3 → parse 41 feature values in correct order
2. Format as CSV string → invoke SageMaker Serverless Endpoint
3. Parse prediction → publish to SNS topic (`hirenovik-predictions-dev`)
4. On error → send error details to SQS DLQ (`hirenovik-lambda-dlq-dev`)

**Feature order (CRITICAL — must match training order):**
```
seniority, modality, years_experience,
has_python, has_aws, has_spark, has_docker, has_sql, has_airflow, has_kafka,
has_kubernetes, has_tensorflow, has_dbt, has_azure, has_gcp, has_pytorch,
has_pandas, has_hadoop, has_snowflake, has_bigquery, has_redshift, has_terraform,
has_jenkins, has_git, has_linux, has_mlops, has_databricks, has_powerbi,
has_tableau, has_mongodb, has_postgresql, has_mysql, has_react, has_nodejs,
has_flask, has_django, has_fastapi, has_go, has_rust, has_java, has_scala
```

### Test Endpoint (`src/ml/inference/test_endpoint.py`, 123 lines)

Tests endpoint with 3 sample profiles:
1. **Data Engineer Senior** — 6 years, many AWS/DE skills → expects high salary
2. **Data Analyst Junior** — 0 years, BI skills → expects low salary
3. **Cloud Engineer Semi-Senior** — 4 years, multi-cloud skills → expects mid salary

### Glue Job Feature Engineering (`src/glue_jobs/clean_and_curate.py`, 136 lines)

**Input:** CSV from `s3://{raw_bucket}/supabase_exports/` (Hive-partitioned)
**Output:** Parquet to `s3://{curated_bucket}/jobs/` (partitioned by `ingestion_date`)

**Processing steps:**
1. Read CSV with `basePath` option to parse Hive partition columns (`ingestion_date`)
2. Dedup by `job_url` (keep latest `date_scraped`)
3. Calculate `salary_mid = (salary_min + salary_max) / 2`
4. Convert to USD: `salary_mid_usd = salary_mid / 17.5` (if MXN)
5. `has_salary` boolean flag
6. **Outlier filtering:** 5000 ≤ salary_mid ≤ 150000 MXN (monthly)
   - Range represents: ~$250-$7,500 USD/month — reasonable for Mexican tech jobs
   - BUT: first filter at lines 44-46 allows `salary_mid >= 5000 AND <= 500000`, then a SECOND filter at lines 52-59 restricts to `5000-150000 MXN`. The first filter is redundant and should be removed.
7. Career count filter: minimum 30 salary records per career for training eligibility
8. `is_valid_for_training` flag (does NOT filter, just labels)
9. `seniority` (0-3) from title regex
10. `years_experience` mapped from seniority
11. `modality` (0-2) from job_type
12. 39 keyword binary features from description
13. Output: 45+ columns to Parquet

---

## AWS Infrastructure (Terraform)

### Current Status: NOT DEPLOYED
The Terraform backend state bucket (`hirenovik-tf-state-edgar-alfaro-2026`) needs to be created first. The infrastructure is fully coded and validated with `terraform validate` but has never been applied.

### Deployment Order

```
Step 1: infrastructure/backend-setup/  → Create S3 bucket + DynamoDB for state
Step 2: infrastructure/environments/dev/ → Create all resources (5 modules)
```

### Backend Setup (`infrastructure/backend-setup/`)
- S3 bucket: `hirenovik-tf-state-edgar-alfaro-2026`
  - Versioning enabled (recover from bad state changes)
  - AES256 encryption
  - Public access block (all 4)
  - HTTPS-only policy (enforced via bucket policy)
  - Lifecycle: keep 90 most recent versions
  - Separate logging bucket (30-day retention)
- DynamoDB: `hirenovik-tf-locks`
  - PAY_PER_REQUEST billing (pennies/month)
  - PITR enabled (point-in-time recovery)
- **Estimated cost:** ~$1/month (S3 + DynamoDB for state)

### Storage Module (`infrastructure/modules/storage/`)

5 S3 buckets, all with AES256 encryption + public access blocks:

| Bucket | Name Pattern | Versioning | Purpose |
|--------|-------------|------------|---------|
| Raw | `hirenovik-raw-dev` | No | Supabase exports, CSV landing zone |
| Curated | `hirenovik-curated-dev` | No | Cleaned Parquet, training data |
| Models | `hirenovik-models-dev` | **Yes** | Trained XGBoost artifacts |
| Outputs | `hirenovik-outputs-dev` | No | Inference outputs |
| Input | `hirenovik-input-dev` | No | Lambda trigger input (.json files) |

**Estimated cost:** ~$0-1/month (negligible storage for ~9k job records)

### Data Engineering Module (`infrastructure/modules/data_engineering/`)

**Glue Catalog Database:** `hirenovik_db_dev`
- Cost: $0 (Hive metastore is free)

**Glue Crawler:** `hirenovik-crawler-dev`
- Targets: `s3://hirenovik-raw-dev/supabase_exports/`
- Recrawl behavior: `CRAWL_NEW_FOLDERS_ONLY` (cost-optimized — avoids re-scanning all data)
- Schema change: `UPDATE_IN_DATABASE` / `DEPRECATE_IN_DATABASE`
- Lineage: enabled
- **Estimated cost per run:** ~$0.10-0.30 (depends on data volume)
- **Running daily:** ~$3-9/month

**Glue Job:** `hirenovik-cleaning-job-dev`
- Worker type: G.1X (4 vCPU, 16GB RAM)
- Workers: 2
- Glue version: 4.0
- Timeout: 60 minutes
- Max retries: 0
- Script: `clean_and_curate.py` uploaded to S3 raw bucket
- Default args include CloudWatch logging + metrics
- **Estimated cost per run:** ~$0.88/hour × 2 DPU × ~10 min = ~$0.30
- **Running on-demand (not daily):** ~$0.30-1.00/month

**IAM:** Least-privilege role with:
- S3: read raw bucket, write curated bucket
- Glue: full catalog access
- CloudWatch: create logs + metrics
- PassRole: conditional

### ML Inference Module (`infrastructure/modules/ml_inference/`)

**SageMaker Model + Endpoint:**
- Conditional: `count = var.model_artifact_path != "" ? 1 : 0`
- **Serverless Inference** (NOT persistent — pay per invocation)
  - max_concurrency: 1
  - memory_size: 2048MB (2GB)
- Uses `sagemaker-xgboost:1.5-1` prebuilt image
- **Estimated cost:** $0 (if no endpoint deployed) → ~$0.10-0.50/month when deployed (few invocations)

**Lambda Function:** `hirenovik-inference-dev`
- Runtime: Python 3.12
- Memory: 128MB
- Timeout: 30 seconds
- Trigger: S3 `.json` upload to input bucket
- IAM: S3 read, SageMaker invoke (scoped to `hirenovik-*` endpoints), SNS publish, SQS send
- Zip built to `infrastructure/modules/ml_inference/build/` (NOT `.terraform/`)
- **Estimated cost:** $0 (AWS Free Tier — 1M requests/month)

**SNS Topic:** `hirenovik-predictions-dev`
- Lambda publish policy
- **Estimated cost:** $0 (Free Tier — 1M publishes/month)

**SQS DLQ:** `hirenovik-lambda-dlq-dev`
- 14-day message retention
- **Estimated cost:** $0 (Free Tier — 1M requests/month)

### Orchestration Module (`infrastructure/modules/orchestration/`)

**Step Functions State Machine:** `hirenovik-pipeline-dev`
- Type: STANDARD (not EXPRESS — standard is cheaper for infrequent runs)
- States:
  1. `StartGlueCrawler` → Glue crawler `.sync`
  2. `StartGlueJob` → Glue job `.sync`
  3. `StartTraining` → SageMaker training `.sync` (dynamic name via `States.Format`)
  4. `NotifySuccess` → SNS publish
  5. `NotifyFailure` → Catch-all error handler → SNS publish
- **Estimated cost per execution:** ~$0.01 (4 state transitions)
- **Running monthly (few times):** ~$0.05/month

**Dynamic TrainingJobName fix:** Uses `States.Format('hirenovik-xgb-{}', $$.Execution.Name)` to avoid `ResourceInUseException` when re-running. Each execution gets a unique training job name.

**No DeployEndpoint step — Terraform owns the endpoint.** After training completes, user manually updates `model_artifact_path` in Terraform variables and runs `terraform apply` to create the SageMaker endpoint.

### Observability Module (`infrastructure/modules/observability/`)

**CloudWatch Dashboard:** `hirenovik-dev` with 5 widgets:
1. Glue Job Duration (line chart, daily period)
2. Files in Curated Zone (single value, daily)
3. SageMaker Endpoint Error Rate (5-min period, with % calculation)
4. Lambda Inference Duration + Errors (5-min period)
5. Pipeline Executions — Failed vs Succeeded (single value, daily)

**CloudWatch Alarms (3):**
1. `hirenovik-sagemaker-error-rate-dev` — conditional (only when endpoint exists), >5 errors in 10 min
2. `hirenovik-lambda-error-rate-dev` — >10 errors in 10 min
3. `hirenovik-glue-failure-dev` — >0 failed Glue tasks
- All alarms → SNS notifications
- `treat_missing_data = notBreaching` (prevents false alarms during idle periods)

### Dev Environment (`infrastructure/environments/dev/`)
- Remote state: `s3://hirenovik-tf-state-edgar-alfaro-2026/dev/terraform.tfstate`
- Provider: us-east-1
- Default tags: Project=Hirenovik, Environment=dev, ManagedBy=Terraform
- All 5 modules called with proper cross-module dependencies

---

## CI/CD — GitHub Actions

### daily_scout.yml
- **Schedule:** `17 12 * * *` (12:17 UTC / 6:17 AM CST)
- **Trigger type:** Scheduled + manual dispatch
- **Runs on:** ubuntu-latest
- **Steps:**
  1. Checkout code
  2. `docker build -t bajio-scout .`
  3. Run container with secrets: `DATABASE_URL`, `EMAIL_USER`, `EMAIL_PASS`
  4. Env vars: `WORKER_NAME=GitHub_Actions`, `EXECUTION_MODE=cloud_extraction`
- **Secrets required:** `DATABASE_URL`, `EMAIL_USER`, `EMAIL_PASS`
- **What happens:** ~600 new records inserted daily (~225 JobSpy NEW + ~270 Computrabajo PENDING_ENRICHMENT + ~315 OCC PENDING_ENRICHMENT)

### enrichment_local.yml
- **Trigger:** Manual via GitHub UI (`workflow_dispatch`)
- **WARNING:** Runs from ubuntu-latest (datacenter IP). Phase 2 is designed for residential IPs. If run, will likely get blocked by target sites. Recommended to run locally instead.
- **Secrets required:** `DATABASE_URL`

### s3_export.yml
- **Schedule:** `45 12 * * *` (12:45 UTC / 6:45 AM CST — 28 min after scraping finishes)
- **Trigger type:** Scheduled + manual dispatch
- **Steps:**
  1. Checkout code
  2. `pip install -r requirements.txt` (not Docker-based)
  3. Run `python src/data_ingestion/supabase_to_s3.py`
- **Env vars:** `S3_RAW_BUCKET=hirenovik-raw-dev`, `AWS_REGION=us-east-1`
- **Secrets required:** `DATABASE_URL`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`
- **What happens:** Incremental export of NEW/PENDING_ENRICHMENT records to S3

---

## Supabase → S3 Export

### Script: `src/data_ingestion/supabase_to_s3.py` (307 lines)

V2 incremental export pipeline with Hive-style partitioning and checkpoint tracking.

### How it works

| Step | Description |
|------|-------------|
| 1. Read checkpoint | Checks S3 for `supabase_exports/checkpoint/last_export.txt`. If absent (first run), exports ALL records. If present, exports only records newer than the checkpoint timestamp. |
| 2. Extract from Supabase | Queries `jobs WHERE status IN ('NEW', 'PENDING_ENRICHMENT') AND date_scraped > checkpoint_date`. Adds `has_salary` boolean column. |
| 3. Group by ingestion date | Splits records by the date part of `date_scraped` for Hive-style partitions. |
| 4. Upload to S3 | Each group uploaded as: `supabase_exports/ingestion_date=YYYY-MM-DD/jobs_export_{timestamp}.csv` |
| 5. Update checkpoint | Computes `MAX(date_scraped)` from the exported batch and overwrites `checkpoint/last_export.txt`. |

### S3 output structure

```
hirenovik-raw-dev/
└── supabase_exports/
    ├── ingestion_date=2026-05-20/
    │   └── jobs_export_20260520_124500.csv
    ├── ingestion_date=2026-05-21/
    │   └── jobs_export_20260521_124500.csv
    └── checkpoint/
        └── last_export.txt   ← ISO timestamp of newest exported record
```

### Edge Cases

| Scenario | Behavior |
|---|---|
| First run (no checkpoint) | Full export of ALL records |
| No new records | Skips uploads, checkpoint unchanged |
| Upload failure mid-way | Checkpoint NOT updated. Next run re-exports the same range (idempotent). |
| Checkpoint corrupted/non-parseable | Falls back to full export |
| Two simultaneous exports | Overlapping files possible. Glue handles dedup by `job_url`. |

### Technical Details
- Uses `boto3` for S3 operations
- Each CSV row includes all Job model columns + `has_salary` boolean
- Files uploaded with `ServerSideEncryption='AES256'`
- Checkpoint file contains a single ISO-formatted datetime string

---

## Tracking CLI

### Script: `scripts/tracker.py` (126 lines)

Interactive CLI for job application tracking.

### Menu Options

**1 — Show NEW jobs:**
- Lists title, company, location, salary, URL
- Sorted by date_scraped descending

**2 — Mark job as APPLIED:**
- Prompts for job ID
- Updates DB: `status='APPLIED'`, `applied_date = NOW()`
- Confirmation message

**3 — Show follow-up priorities:**
- Scoring algorithm: `status_weight + days_since_update + days_since_applied`
- Higher score = higher priority
- Displays title, company, score, days since last update, URL

### Known Issues (FIXED in AGENTS.md but code may not reflect)
- ~~Line 1 has debug print: `print("SOY JOTO ALAVERGA")`~~ — should be removed if still present
- ~~Import path: `from models import db_connect, Job`~~ — should be `from src.database.models import db_connect, Job`
- ~~Uses `julianday()` SQL function (SQLite syntax)~~ — should use PostgreSQL `EXTRACT(DAY FROM ...)`
- ~~Column reference `location`~~ — should be `raw_location`

---

## Product Roadmap

### v1 — Student Tier (Build now, deadline May 28, 2026)

**Features:**
1. Top 10 skills by career (weekly updated) — from keyword feature analysis
2. Salary prediction (XGBoost) — trained on 986+ useful records
3. Weekly skill trends (keyword frequency over time)
4. Word clouds by career
5. Affiliate course links (Udemy/Coursera/Platzi)

**Tech stack:** FastAPI backend + Streamlit frontend (MVP)

**Data refresh cadence:** Daily (scraping) → Weekly (NLP + ML retraining)

### v2 — Enterprise Tier
- BI dashboard for HR/recruiting
- Salary benchmarking by role and city (requires more data)
- Competitor analysis (company-level hiring patterns)
- CSV/PDF exports (already partially implemented in reporting_legacy/)
- Real-time alerts for new matching jobs

### Post-AWS-Credits Strategy ($0-3/month)

When the $150 budget runs out:
1. **Remove:** Glue jobs + Glue Crawler + SageMaker endpoint + Step Functions
2. **Keep:** S3 (pennies/month), Lambda (free tier), SNS (free tier), SQS (free tier)
3. Load XGBoost model artifact from S3 into FastAPI in-memory
4. Host FastAPI on fly.io (free tier — 3 apps, shared CPU, 256MB RAM)
5. Host Streamlit frontend on Streamlit Community Cloud (free tier)
6. Keep scraping pipeline running on GitHub Actions (free tier)
7. Keep Supabase PostgreSQL (free tier — 500MB)

**Monthly cost breakdown after AWS credits:**
- S3 storage: ~$0.05 (few GBs)
- Lambda: $0 (free tier)
- SNS/SQS: $0 (free tier)
- fly.io: $0 (free tier)
- Streamlit Cloud: $0 (free tier)
- Supabase: $0 (free tier)
- GitHub Actions: $0 (free tier — 2000 min/month)
- **Total: ~$0-3/month**

---

## GitHub Branch Strategy

- **Main:** Production branch, protected. Direct pushes blocked. Only squash merges from dev.
- **Dev:** Integration branch. Feature branches merged here, tested, then PR'd to main.
- **Feature branches:** Branched from dev, named `feature/*` (e.g., `feature/s3-export-v2`)

**PR merge strategy:** Squash merge into main (clean git history).

**Issues closed:** 19+ PRs merged covering scraper features, architecture refactors, and infrastructure.

---

## Data Audit & Analysis (sql_results.md)

**Date of analysis:** 2026-05-20
**Data source:** Supabase PostgreSQL
**Total records:** 9,178

### Query 1 — Overall Data Quality

| Metric | Count | % of Total |
|--------|-------|-----------|
| Total records | 9,178 | 100% |
| Status NEW | 7,278 | 79.3% |
| Status PENDING_ENRICHMENT | 1,898 | 20.7% |
| Status ORPHANED | 255 | 2.8% |
| With description | 6,338 | 69.1% |
| With salary | 861 | 9.4% |
| Useful for ML (salary + description) | **986** | **10.7%** |

**Context on 986 useful records:** This count appears with two different values in the data — Query 1 shows 986, Query 10 shows 1472. The discrepancy is likely because Query 10 doesn't filter out `salary_min = 'NaN'` text values (notice most salary columns in the raw table are stored as text/varchar, not numeric). Only 861 records have `salary_min IS NOT NULL` (actual DB null check), suggesting the other records that "have salary" actually have `'NaN'` as a string value. The 1472 count from Query 10 includes records where salary_min is not null AND is not the string 'NaN'.

**Senior engineer interpretation:** The `'NaN'` string problem is a data type inconsistency. Salary columns are `Numeric` in the SQLAlchemy model but some records contain the string `'NaN'` (Python float NaN serialized as text). This MUST be cleaned before ML training.

### Query 2 — Coverage by Site

| Site | Total | With Salary | With Description | Useful for Model | Salary % | Description % |
|------|-------|-------------|-----------------|-----------------|----------|--------------|
| indeed | 4,435 | 862 | 4,435 | 862 | 19.4% | 100.0% |
| computrabajo | 1,982 | 1,978 | 1,128 | 1,124 | 99.8% | 56.9% |
| linkedin | 1,715 | 0 | 0 | 0 | 0.0% | 0.0% |
| occ | 1,046 | 1,046 | 0 | 0 | 100.0% | 0.0% |

**Key insights:**
- **Indeed:** Best source for descriptions (100%) but poor salary coverage (19.4%). However, the 862 salary records with descriptions are the backbone of the ML model.
- **Computrabajo:** EXCELLENT salary coverage (99.8%) — the listing cards include salary data. Only 56.9% enriched with descriptions (Phase 2 is still in progress).
- **LinkedIn:** Useless for model training (0% salary, 0% descriptions). Only 1,715 records — suggests LinkedIn frequently blocks scraping.
- **OCC:** 100% salary coverage from listing cards but 0% descriptions (OCC Phase 2 hasn't been run yet — all 1,046 are still PENDING_ENRICHMENT).

**Actionable recommendation:** Run OCC Phase 2 enrichment urgently — it has 1,046 records that ALREADY HAVE salary data. Even 30% enrichment success would nearly double the training dataset (from 986 to ~1,300).

### Query 3 — Useful Records by Career (Top 15)

| Career | Total | Useful for Model | With Salary Only | With Description Only |
|--------|-------|-----------------|-----------------|---------------------|
| Data Analyst | 1,113 | 342 | 27 | 638 |
| Desarrollador Backend | 694 | 301 | 0 | 200 |
| Business Intelligence | 650 | 261 | 20 | 115 |
| React Developer | 415 | 228 | 57 | 70 |
| Cloud Engineer | 843 | 138 | 16 | 641 |
| Data Engineer | 689 | 127 | 35 | 111 |
| DevOps Engineer | 386 | 109 | 10 | 612 |
| Python Developer | 540 | 74 | 326 | 91 |
| Python Backend | 504 | 63 | 02 | 843 |
| Java Backend | 417 | 59 | 0 | 193 |

**Senior engineer observations:**
- **Data skew:** Data Analyst (342 useful records) dominates. Many careers have <100 records — insufficient for per-career models.
- **Stratified split critical:** The 70/20/10 split must be stratified by career, otherwise the model will be biased toward Data Analyst.
- **Description-rich but salary-poor careers:** Cloud Engineer has 843 total but only 138 with salary. Phase 2 enrichment + salary recovery from detail pages should be prioritized for these.
- **The NaN string problem in salary avg:** Notice `NaN`, `8NaN`, `9NaN` values in the average columns — clear evidence that salary values stored as text contain Python float NaN serialization artifacts.

### Query 4 — Salary Distribution (MXN)

| Metric | Value |
|--------|-------|
| Records with salary | 3,886 (but only 861 non-NaN) |
| Minimum salary | $1,000/month |
| Maximum salary | NaN (data quality issue) |
| Average mid salary | NaN (data quality issue) |
| Percentile 25 | $22,000/month |
| Median | $42,750/month |
| Percentile 75 | NaN (data quality issue) |
| Percentile 95 | NaN (data quality issue) |

**Senior engineer interpretation:** The percentile and average queries are being poisoned by NaN string values. The `3,886 registros` is the total count where `salary_min IS NOT NULL`, but many of those have the string literal `'NaN'` instead of a valid number. Only ~861 truly valid numeric salaries exist. The Glue job's `has_salary` filter (`salary_min IS NOT NULL AND salary_max IS NOT NULL`) will catch SQL NULLs but NOT string `'NaN'` values.

### Query 5 — Salary Outliers (Top 20 Problem Records)

```
SENIOR SALES SPECIALIST — $125K-$2.25M MXN  → LEGIT (US-based company)
SENIOR MANAGER, ENGINEERING     — $1.66M-$2.07M MXN → LEGIT (US-based, senior role)
TECHNICAL SALES ENGINEER        — $900K-$1.8M MXN   → LEGIT (US-based)
SR. RELIABILITY OPS ENGINEER    — $757K-$1.4M MXN   → LEGIT (US-based)
SENIOR FULL STACK ENGINEER (×4) — $950K-$1.38M MXN  → DUPLICATE (same job, multiple scrapes)
```
```
JR. DATA ANALYST (Kelly)       — $1,300-$120K MXN → PROBLEM: ratio 92x (max/min = 92)
FULL STACK SOFTWARE ENGINEER    — $4,000-$90K MXN  → PROBLEM: ratio 22x
DESARROLLADOR FULL STACK        — $2,000-$25K MXN  → PROBLEM: ratio 12x
```

**Senior engineer observations:**
- **High salaries ($500K+):** These are US-based remote jobs paying in USD equivalent. The model should handle these as legitimate but the Glue job's `150000 MXN` cap will filter them out. CONSIDERATION: should there be a separate model for US-salaried positions vs Mexican-market positions?
- **Wide salary ranges (ratio > 10):** Likely indicates `salary_min` is monthly while `salary_max` is annual, or includes variable compensation (bonuses, commissions). The Glue job's `salary_max / salary_min > 10` filter in the data audit is a reasonable heuristic for detecting these.
- **Duplicate records:** `SENIOR FULL STACK ENGINEER` appears 4 times — from different scrapes of the same Indeed listing. The Glue dedup by `job_url` handles this, but duplicates inflate the "NEW" count.
- **Extreme outliers below $2,000/month:** These are likely part-time, internship, or misclassified roles. The Glue job's `5000 MXN` lower bound is reasonable.

### Query 6 — Pending Enrichment by Site

| Site | Pending | With Salary | Worth Enriching |
|------|---------|-------------|-----------------|
| occ | 1,046 | 1,046 | 1,046 |
| computrabajo | 852 | 852 | 852 |

**Critical finding:** There are 1,898 records with ALREADY-KNOWN salary data just waiting for Phase 2 enrichment. Every successful description enrichment adds a training record. At a ~60% success rate (based on computrabajo's current 56.9%), that's ~1,139 new training records — more than doubling the current dataset.

### Query 7 — Weekly Trends (Last 8 Weeks)

| Week | Top Career | Jobs | Avg Salary |
|------|-----------|------|-----------|
| 2026-05-18 | Data Analyst | 192 | $225,755 |
| 2026-05-11 | Data Analyst | 503 | $198,822 |
| 2026-05-04 | Data Analyst | 248 | $234,822 |
| 2026-04-27 | Cloud Engineer | 99 | $69,211 |
| 2026-04-20 | Cloud Engineer | 31 | $127,500 |
| 2026-04-13 | Cloud Engineer | 9 | $52,000 |
| 2026-04-06 | DevOps Engineer | 1 | null |

**Senior engineer observations:**
- **Data volume explosion around May 4-11:** This coincides with the introduction of cloud_extraction mode and multi-worker routing. Before that, only 1-31 jobs per week were collected (likely running locally with limited keywords).
- **Salary spike in weeks with few records:** $127,500 for 31 Cloud Engineer jobs in April 20 is misleading — small sample sizes inflate averages.
- **Seasonal patterns emerging:** Tech hiring in Mexico appears to peak in May, which aligns with the end of the Mexican fiscal year (companies have remaining budget to spend).
- **Null salaries in early weeks:** Consistent with running locally without salary recovery.

### Query 8 — Keyword Frequency by Career

**Top mentions (across all careers):**
- Python: heavily in Python Backend (345), Data Scientist (178), AI Engineer (147)
- AWS: dominant in Cloud Engineer (295), Python Backend (212), AI Engineer (138)
- Docker: DevOps Engineer (753 mentions — this is clearly their primary tool)
- Kubernetes: DevOps Engineer (397), Cloud Engineer (171)
- SQL: Data Engineer (591), Desarrollador Backend (228), Data Analyst (164)
- Spark: Data Engineer (237), Data Scientist (37)
- Terraform: DevOps Engineer (232), Analytics Engineer (165)

**Senior engineer observations:**
- **Some career totals seem wrong:** Desarrollador Backend has 501 total_con_descripcion but Python Backend shows 22 — likely a career mapping issue since "Python Backend" is a separate career in the data.
- **Data Engineer SQL mentions (591) exceed total records (689):** This means some descriptions mention "sql" multiple times, OR the career assignment has duplicates. Since the keyword check is `ILIKE '%sql%'`, a single description could match multiple times if the career appears in multiple contexts.
- **Missing career-salary correlations:** Careers with high Python mentions (Data Scientist, AI Engineer) SHOULD correlate with higher salaries — this is what the XGBoost model will learn.

### Query 9 — Salary by Job Type

| Type | Total | Avg Mid Salary | With Salary |
|------|-------|---------------|------------|
| presencial | 5,786 | $58,007 | 825 |
| remoto | 4,783 | $58,517 | 8 (!) |
| hibrido | 604 | $35,831 | 235 |

**Major data quality issue:** Only 8 remote jobs have salary data despite 4,783 records. This is because:
- Indeed doesn't provide remote/on-site classification directly — `detect_job_type()` checks title + location for keywords
- "Remoto" is rarely in the title/location for Indeed jobs
- OCC and Computrabajo have job_type on their listing cards, but many are classified as "presencial" by default
- The salary data and job type data don't overlap well

**This means the `modality` feature (one of only 3 numeric features) will have near-zero variance in the training data.** Most training records will have `job_type='presencial'` regardless of actual modality. Consider removing modality from the model or improving detection.

### Query 10 — Executive Summary

| Metric | Value | % of Total |
|--------|-------|-----------|
| Total records | 9,178 | 100% |
| **Useful for XGBoost** | 1,472 | 16.0% |
| Salary without description | 1,083 | 11.8% |
| Description without salary | 4,091 | 44.6% |
| No salary, no description | 2,532 | 27.6% |
| Pending enrichment | 1,898 | 20.7% |

**Senior engineer final verdict on data readiness for ML:**

**Reality check:** The 1,472 "useful" records in Query 10 are optimistic. After outlier filtering in the Glue job ($5,000-$150,000 MXN range), removing `'NaN'` string artifacts, and filtering careers with <30 records, the actual training set will be closer to **800-1,000 rows**. For a 41-feature XGBoost model:
- **Rule of thumb:** Need at least 10× features = 410 rows minimum
- **Comfortable:** 1,000+ rows for a 41-feature model is workable
- **Good practice:** 5,000+ rows would be ideal

**Verdict:** The current dataset is sufficient for a PROOF-OF-CONCEPT model. The model will work but won't be production-grade until enrichment catches up with Phase 2 and the dataset grows to 5,000+ useful records.

**Confidence level:** Medium. The model will produce predictions that trend in the right direction (senior roles → higher salary, more keywords → higher salary) but individual predictions may have ±30-50% error.

---

## Senior Engineer Audit: Code Quality & Risks

### Strengths

1. **Two-phase architecture is clever and well-executed.** The separation of concerns (Phase 1 = fast cloud, Phase 2 = slow residential) is production-quality thinking that respects real-world constraints.

2. **Config-driven worker routing.** The `WORKER_NAME` system allows 6 classmates to contribute without code changes. Each worker has their own keyword set, niche, and runs from their own residential IP.

3. **Graceful degradation everywhere.** Every scraper handles failures gracefully — returns empty DataFrame or None values, never crashes the pipeline.

4. **Anti-ban is layered and thoughtful.** Not just one technique but 7+ layers working together. The circuit breaker pattern is particularly well-implemented.

5. **Terraform is well-structured.** Good separation of modules, proper cross-module dependencies, account-scoped ARNs (no wildcards), conditional resources for cost optimization.

6. **Dynamic TrainingJobName** in Step Functions avoids the most common re-run failure mode.

7. **Hive partitioning + basePath** in Glue job shows understanding of Spark partition column handling.

8. **Serverless SageMaker endpoint** instead of persistent — critical budget decision that saves ~$47/month.

### Critical Issues to Fix Before Deployment

**P1 — Data type inconsistency: `'NaN'` string in salary columns**
- **Severity:** HIGH — will break ML training, skew averages, poison percentile calculations
- **Root cause:** Python `float('NaN')` being serialized directly to PostgreSQL without proper null conversion
- **Fix:** Clean existing data: `UPDATE jobs SET salary_min = NULL WHERE salary_min::text = 'NaN'` (and same for salary_max). Add validation in `transform.py` and `_map_phase1_records()` to convert NaN to None before insert.

**P2 — Glue job has redundant salary filter**
- **Location:** `src/glue_jobs/clean_and_curate.py:44-59`
- **Issue:** Two sequential salary filter blocks:
  1. Lines 44-46: `salary_mid >= 5000 AND <= 500000` (but applies to ALL records including those without salary)
  2. Lines 52-59: `salary_mid >= 5000 AND <= 150000` (correct MXN range)
- **Result:** The first filter actually filters out NULL-salary records (because `null >= 5000` is false), which is the OPPOSITE of what the comment says ("conserva los sin salario"). The `col("salary_mid").isNull()` OR condition was supposed to prevent this.
- **Fix:** Remove the redundant first filter block (lines 44-46).

**P3 — Training data path mismatch between train.py and Step Functions**
- **Location:** `src/ml/training/train.py:231` vs `infrastructure/modules/orchestration/step_functions.tf:66-67`
- **Issue:** `train.py` uploads to `s3://{RAW_BUCKET}/training-data/{timestamp}/` (raw bucket), but the Step Functions training step reads from `s3://{curated_bucket}/training-data/train/` (curated bucket).
- **Fix:** Either change `train.py` to upload to the curated bucket, or change the Step Functions definition. Recommend changing `train.py` since curated bucket has proper Parquet output.

**P4 — `extract_salary_from_text()` only catches comma-formatted numbers**
- **Location:** `src/etl/transform.py:73`
- **Issue:** The regex `\$\s?(\d{1,3}(?:,\d{3})+)` requires comma separators (e.g., "$12,000"). Salaries written as "$12000" or "12000 pesos" will be missed.
- **Fix:** Add fallback regex patterns for non-comma-formatted salaries.

**P5 — `STATE_MAP` is too limited for country-wide analysis**
- **Location:** `src/etl/transform.py:10-22`
- **Issue:** Only 3 states (Guanajuato, Querétaro, Jalisco) are mapped. The other 29 states and CDMX will always get `state=NULL`.
- **Impact:** The `state` column is nearly useless for analysis. The `idx_geo_type` index on `(country_code, state, job_type)` won't help query performance for most records.
- **Fix:** Expand STATE_MAP to cover all 32 states + CDMX, OR remove the state feature from the model if Bajío-only focus is intentional.

**P6 — `detect_job_type()` is unreliable for Indeed jobs**
- **Location:** `src/etl/transform.py:47-54`
- **Issue:** Only checks title + location for remote/hybrid keywords. Most Indeed jobs don't include modality in these fields.
- **Impact:** 4,783 of 9,178 records are classified as "presencial" by default, even though many are remote.
- **Fix:** Accept the limitation for now but document it. Consider improving with a keyword list expansion.

### Medium-Severity Issues

**P7 — No tests beyond manual HTML fixtures**
- No pytest unit tests for scrapers, ETL, or pipeline logic
- `tests/test_scrapers/` contains only HTML debug files
- `Makefile` has a `test` target but no actual test suite
- **Risk:** Refactoring is dangerous — no safety net

**P8 — `nlp_module/` has its own venv but no activation documentation**
- Root `requirements.txt` doesn't include NLP dependencies (langdetect, simplemma, etc.)
- Must create and activate `nlp_module/.venv/` separately
- **Risk:** New contributors won't know about the separate venv

**P9 — `email_sender.py` and `pdf_report.py` are dead code**
- Fully implemented but never called from `main.py`
- Adds ~200 lines of unmaintained code
- **Risk:** Someone might try to enable email sending without realizing the Gmail app password is needed

**P10 — CSV export runs on every pipeline execution**
- In `main.py`, `export_jobs()` is called unconditionally at the end of every mode
- This means even cloud_extraction mode (GitHub Actions) tries to write a CSV file
- On GitHub Actions, the reports directory may not exist or be writable
- **Risk:** Export failure could falsely appear as a pipeline failure

**P11 — `workflow.json` is a stale reference**
- `src/step_functions/workflow.json` contains the old 5-step pipeline (including DeployEndpoint)
- Terraform is the source of truth now, but the JSON could confuse newcomers
- **Fix:** Delete or update the JSON to match Terraform

### Minor Issues & Code Smells

**P12 — Spanish-English mixed codebase**
- Variable names, comments, and log messages mix Spanish and English
- Makes the code harder for international contributors
- Not a blocker but inconsistent

**P13 — `occ_scraper.py:132` has escaped CSS class selector**
- `div.h-\\[21px\\]` — the double backslash is Terraform/HCL escaping. In Python, it should be `div.h-\[21px\]` or the class should be matched differently.
- This works because `BeautifulSoup` handles the escaping, but it's fragile.

**P14 — `include_linkedin_today()` only checks weekday, not timezone**
- Runs on GitHub Actions (UTC) but uses local `datetime.now()`
- Monday at 6 AM CST = Monday at 12 PM UTC — so Monday UTC afternoon is actually Monday morning CST
- Most of Monday UTC is still Sunday CST
- **Risk:** LinkedIn may only be included for ~12 hours of the day instead of full Monday

**P15 — `email_password.py` in git history**
- If there was ever a real email password committed, it's in git history
- Should rotate the Gmail app password

---

## $150 Budget Cost Analysis

### Assumptions
- **Region:** us-east-1 (cheapest)
- **Usage:** Daily scraping + incremental S3 export + weekly ML pipeline
- **Duration:** 1 month (May 2026) for the project, but budgeting for full month

### Deployed Resource Cost Estimate

| Service | Configuration | Monthly Cost | Notes |
|---------|--------------|-------------|-------|
| **S3** — 5 buckets | ~10GB total, Standard storage | ~$0.50 | Negligible — job data is tiny |
| **S3** — PUT/GET requests | ~10k requests/month | ~$0.001 | Effectively $0 |
| **Glue Crawler** | CRAWL_NEW_FOLDERS_ONLY, ~1 run/day, ~$0.20/run | ~$6.00 | 1-2 min/run = ~$0.02 each |
| **Glue Job** | G.1X × 2 workers, ~10 min/run, $0.88/DPU-hour | ~$3.00 | ~$0.30/run, ~10 runs/month |
| **SageMaker Training** | ml.m5.large × 1, ~30 min, $0.115/hour | ~$0.06 | One-time for demo (not recurring) |
| **SageMaker Endpoint** | Serverless 2GB, ~100 invocations/month | ~$0.10 | Pay per inference, no base cost |
| **Lambda** | 128MB, ~100 invocations/month at 5s avg | ~$0.00 | Free Tier covers this |
| **SNS** | ~50 publishes/month | ~$0.00 | Free Tier covers this |
| **SQS** | ~50 messages/month | ~$0.00 | Free Tier covers this |
| **Step Functions** | STANDARD, ~10 executions, $0.025/1k transitions | ~$0.00 | 4 transitions × 10 = negligible |
| **CloudWatch** | Dashboard + 3 alarms | ~$3.00 | Dashboard costs ~$3/month |
| **EC2 (NAT Gateway)** | Not needed | $0.00 | Only needed if using private subnets |
| **Data Transfer** | Minimal (Lambda → SageMaker in same AZ) | $0.00 | Within AZ is free |
| **Total Estimated** | | **~$13-17/month** | Well within $150 budget |

### Budget Headroom

| Item | Amount |
|------|--------|
| Total budget | $150.00 |
| Estimated monthly cost | ~$15.00 |
| Buffer | **$135.00** |

**Buffer covers:** 9 months of operation, OR unexpected usage spikes, OR re-training the model multiple times, OR accidentally leaving resources running over the weekend.

### What NOT to Deploy (Cost Traps)

| Service | Why Not | Cost If Deployed Wrong |
|---------|---------|----------------------|
| Persistent SageMaker endpoint (ml.t2.medium) | Original design — $47/month. Switched to serverless. | -$47/mo |
| NAT Gateway | Would be required for private subnet Lambda. Don't use VPC for Lambda. | -$32/mo |
| Glue Crawler with CRAWL_EVERYTHING | Re-scans all data every run. Current config uses CRAWL_NEW_FOLDERS_ONLY. | -$3x/mo |
| Provisioned Glue capacity | On-demand is fine for this data volume | -$2x/mo |
| RDS database | Supabase is free — don't migrate to RDS | -$15/mo+ |
| EC2 for anything | Lambda covers all compute needs | -$10/mo+ |

### Critical Budget Rules

1. **Never leave SageMaker training running** — set `StoppingCondition.MaxRuntimeInSeconds = 3600`
2. **Never change Glue Crawler to CRAWL_EVERYTHING** — the config is correct, protect it
3. **Never deploy a persistent SageMaker endpoint** — always use serverless
4. **Set CloudWatch budget alarms** at $50, $100, $130 in AWS Budgets
5. **Tag everything** with Project=Hirenovik for cost tracking
6. **Destroy immediately** after May 28 presentation if not continuing

### Post-Presentation Cleanup
```bash
terraform -chdir=infrastructure/environments/dev destroy
# Manually empty S3 buckets first (Terraform can't delete non-empty buckets)
aws s3 rm s3://hirenovik-raw-dev --recursive
aws s3 rm s3://hirenovik-curated-dev --recursive
aws s3 rm s3://hirenovik-models-dev --recursive
aws s3 rm s3://hirenovik-outputs-dev --recursive
aws s3 rm s3://hirenovik-input-dev --recursive
terraform -chdir=infrastructure/environments/dev destroy
# Destroy backend state bucket
terraform -chdir=infrastructure/backend-setup destroy
```

---

## Pre-Deployment Infrastructure Checklist

### Prerequisites
- [ ] AWS account created with valid payment method
- [ ] IAM user with programmatic access keys created
- [ ] AWS CLI configured locally (`aws configure`)
- [ ] GitHub secrets configured (`DATABASE_URL`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`)
- [ ] `.env` file created from `.env.example` with real credentials

### Step 1: Deploy Backend State
```bash
terraform -chdir=infrastructure/backend-setup init
terraform -chdir=infrastructure/backend-setup plan
terraform -chdir=infrastructure/backend-setup apply
```

### Step 2: Deploy Infrastructure
```bash
terraform -chdir=infrastructure/environments/dev init -upgrade
terraform -chdir=infrastructure/environments/dev plan
terraform -chdir=infrastructure/environments/dev apply
```

### Step 3: Verify Resources
- [ ] 5 S3 buckets exist with correct names and encryption
- [ ] Glue Catalog Database exists
- [ ] Glue Crawler exists and can be run
- [ ] Glue Job script uploaded to S3
- [ ] IAM roles created (Glue, SageMaker, Lambda, Step Functions)
- [ ] Lambda function deployed with correct trigger
- [ ] SNS topic exists with subscriptions
- [ ] SQS DLQ exists
- [ ] Step Functions state machine created
- [ ] CloudWatch Dashboard visible

### Step 4: Run Data Export
- [ ] Run `s3_export.yml` workflow manually first time (full export)
- [ ] Verify CSV files in `s3://hirenovik-raw-dev/supabase_exports/`
- [ ] Verify checkpoint file created

### Step 5: Run Glue Pipeline
- [ ] Run Glue Crawler (create table in catalog)
- [ ] Run Glue Job (verify Parquet output in curated bucket)
- [ ] Verify dedup by checking distinct job URLs

### Step 6: Prepare Training Data
```bash
# Run locally with AWS credentials
SAGEMAKER_ROLE_ARN=arn:aws:iam::YOUR_ACCOUNT:role/... python src/ml/training/train.py --no-train
```
- [ ] Training data CSV files uploaded to `s3://hirenovik-curated-dev/training-data/`
- [ ] Verify train/validation/test splits are balanced by career

### Step 7: Run Step Functions
- [ ] Execute state machine from AWS Console
- [ ] Verify Glue Crawl → Glue Clean → Training → Notification flow
- [ ] Check SNS notification received
- [ ] Verify model artifact in `s3://hirenovik-models-dev/xgboost/`

### Step 8: Deploy SageMaker Endpoint
- [ ] Update `model_artifact_path` in `infrastructure/environments/dev/variables.tf`
- [ ] Run `terraform apply` to create endpoint
- [ ] Test endpoint with `python src/ml/inference/test_endpoint.py`

### Step 9: Test Lambda Inference
- [ ] Upload test JSON to `hirenovik-input-dev/` bucket
- [ ] Verify Lambda execution in CloudWatch logs
- [ ] Verify SNS publishes prediction result

### Step 10: Observability Verification
- [ ] CloudWatch Dashboard shows data
- [ ] Alarms configured and not firing
- [ ] Budget alerts set ($50, $100, $130)

---

## Known Fixes Applied

### Phase 1 Fixes (Initial Project Setup)
- **NOTIFIED → NEW reset:** Ran `UPDATE jobs SET status = 'NEW', last_updated = NOW() WHERE status = 'NOTIFIED'` to clear stale NOTIFIED records after email sending was disabled
- **tracker.py fixes:** Removed debug print, fixed import path, replaced SQLite `julianday()` with PostgreSQL `EXTRACT(DAY FROM ...)`, fixed `location` → `raw_location`

### Phase 3 Fixes (Antigravity Review — Applied to Code)
- **SageMaker:** Switched from persistent `ml.t2.medium` endpoint (~$47/mo) to **Serverless Inference** (pay-per-invocation)
- **Step Functions:** Dynamic `TrainingJobName` via `States.Format('hirenovik-xgb-{}', $$.Execution.Name)` — prevents re-run crash
- **Step Functions:** Removed `DeployEndpoint` step — Terraform owns the endpoint
- **Step Functions:** Training data path changed from raw bucket to curated bucket
- **Step Functions IAM:** Added EventBridge permissions for `.sync` integrations, removed duplicate permissions
- **Glue script:** Added `basePath` option to `spark.read.csv()` for Hive partition parsing
- **Glue Crawler:** Changed `CRAWL_EVERYTHING` → `CRAWL_NEW_FOLDERS_ONLY`
- **Lambda:** Moved zip output from `.terraform/` to `modules/ml_inference/build/`
- **Lambda IAM:** Account-scoped ARNs instead of wildcards
- **Storage:** Added versioning to models bucket
- **Observability:** `FunctionName` dimensions on Lambda widgets, conditional SageMaker alarm
- **Dev environment:** Removed `endpoint_instance_type` variable (serverless defaults)

### Fixes Still Needed
- **P1:** Clean `'NaN'` string values from salary columns in DB
- **P2:** Remove redundant salary filter in Glue job
- **P3:** Fix training data path mismatch between train.py and Step Functions
- **P4:** Expand salary regex for non-comma-formatted numbers
- **P11:** Delete stale `workflow.json`
- **P7 -- FIXED (June 18):** 98 test suite across 5 files + 130 NLP/API tests = 228 total tests covering critical paths.

---

## Gotchas & Warnings

### Security
- `.env` contains real Gmail app password + Supabase URL — **never commit**
- Real credentials may have been committed to git history before `.gitignore` took effect — rotate passwords
- IAM user needs `s3:PutObject`, `s3:GetObject`, `s3:ListBucket` on `hirenovik-raw-dev`
- `s3_export.yml` needs `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` GitHub secrets

### Code
- `.gitignore` excludes `data/`, `reports/`, `*.csv` but some files were committed before gitignore took effect
- 228 tests across 10+ files: `pytest` runs in <5 seconds. `ruff` is installed but not run in CI.
- Codebase is Spanish-heavy: comments, variables, logs in Spanish
- PDF generation and email sending exist in `src/reporting_legacy/` but are **NOT called** from `main.py`
- NLP module scripts reference old paths in docstrings (e.g., `src/nlp/01_text_cleaner.py`) — actual paths use `nlp_module/src/`
- `nlp_module/` has its **own venv and requirements.txt** — root `requirements.txt` is for `src/` code only
- `src/etl/text_cleaner.py` is legacy — use `nlp_module/src/01_text_cleaner.py` instead

### Docker
- Dockerfile says `python:3.12-slim` and `CMD ["python", "src/main.py"]` — correct now
- `.dockerignore` must exclude `.env` (or the Docker build context will include secrets)

### Terraform
- Backend-setup has been written but **NOT deployed** — must be applied first
- Lambda zip is built to `infrastructure/modules/ml_inference/build/` — this dir is gitignored
- `infrastructure/modules/ml_inference/build/` is created automatically by `terraform plan`
- Training data must be pre-prepared in curated bucket before running Step Functions
- `infrastructure/cost_estimates/`, `infrastructure/scripts/`, `infrastructure/layers/` are empty dirs
- `.env.example` has real-looking defaults but they are **placeholders**

### Data
- Salary columns have `'NaN'` string values mixed with valid numbers — **MUST clean before training**
- LinkedIn jobs have NO descriptions and NO salaries — 0% useful for ML
- OCC has 1,046 records with salary but no descriptions — **run Phase 2 enrichment now to double training data**
- Only ~1,000-1,400 records are useful for ML training after filtering
- Data volume exploded in May 2026 when cloud_extraction was introduced — earlier data is sparse
- Some career values are inconsistent: "Backend Developer" vs "Desarrollador Backend" vs "Python Backend"
- Mechanical Engineer and Ingeniero Mecánico are different career entries — should be merged

### Operational
- `enrichment_local.yml` workflow runs from datacenter IPs — **will likely get blocked**. Run locally.
- CSV export runs on every pipeline execution including GitHub Actions — but reports dir may not exist
- `include_linkedin_today()` checks local time, not UTC — may miss Monday window
- Project name is consistently "Hirenovik" across Terraform tags, S3 bucket names, and code
- Legacy `scraper_module/` has been fully replaced by `src/` — old module no longer exists
- s3_export.yml uses `pip install` (not Docker) — dependencies may diverge from Docker image

### Budget
- If you accidentally deploy a persistent SageMaker endpoint: ~$47/month gone
- If you set Glue Crawler to CRAWL_EVERYTHING: ~$3-9/month per run
- If you add a NAT Gateway: ~$32/month gone
- **Set AWS Budget alerts immediately after account creation**
- **Destroy everything after May 28 if not continuing the project**
- Post-AWS strategy: fly.io (free) + Streamlit Cloud (free) + Supabase (free) = $0-3/month

---

## Final Notes (Senior Engineer Summary)

### What This Project Does Well
1. **Two-phase scraping architecture is genuinely clever** — a production-grade solution for a real problem (datacenter IP blocking) that costs nothing extra
2. **Cost-conscious infrastructure design** — every Terraform resource was chosen with the $150 budget in mind
3. **Good anti-ban defense-in-depth** — 7+ layers working together, not just relying on one technique
4. **Graceful failure handling** — no single point of failure crashes the pipeline
5. **Real, working data pipeline** — 9,178 records collected from 4 job sites, running daily on GitHub Actions

### What Needs Improvement
1. **Data quality in salary fields** — the `'NaN'` string problem is the #1 blocker for ML
2. **Test coverage now exists** — 228 tests across 10+ files: 98 ETL/scraper/Glue tests, 100 NLP tests, 30 API tests. All passing.
3. **Career naming inconsistency** — some English, some Spanish, some duplicates
4. **Training data path mismatch** between train.py and Step Functions
5. **State detection is limited to 3 states** — should either expand or remove from model

### The $150 Budget Verdict

**It will work.** The estimated monthly cost is ~$15, leaving $135 buffer for 9 months of operation or unexpected spikes. The critical cost-saving decisions are:
- Serverless SageMaker (not persistent) — saves $47/month
- CRAWL_NEW_FOLDERS_ONLY — saves ~$5-10/month vs full crawl
- No NAT Gateway — saves $32/month
- Using Supabase free tier instead of RDS — saves $15/month

### ML Readiness Verdict

**Ready for proof-of-concept, not production.** With ~1,000-1,400 useful records and 41 features, the XGBoost model will:
- Show correct directional trends (senior = more pay, more skills = more pay)
- Have high variance (±30-50% error on individual predictions)
- Improve significantly once Phase 2 enrichment catches up (doubling training data)
- Need 5,000+ useful records for production-grade accuracy

### Recommendation
1. **Deploy infrastructure this week** — leave time for debugging
2. **Run OCC Phase 2 enrichment immediately** — 1,046 easy wins
3. **Clean NaN values in salary columns** — before any ML training
4. **Fix training data path mismatch** — before running Step Functions
5. **Have a backup plan** for the demo in case AWS deployment has issues (use the Supabase data directly with a locally-trained model)

---

## Recent Accomplishments (May 27, 2026)

### 1. Data Engineering Pipeline Stabilized
- **Root cause fixed:** Glue Crawler was creating multiple partitioned tables (e.g., `ingestion_date_2026_03_11`) due to messy raw CSV schemas and stray files in S3 raw root.
- **Solution:** Reconfigured Glue Crawler (`glue_crawler.tf`) to read from the **Curated Zone (Parquet)** instead of Raw CSV. Parquet has embedded schemas, guaranteeing a single `jobs` table in the Data Catalog.
- **PySpark Job Fixed:** `clean_and_curate.py` had a critical syntax error (using undefined variables in a loop and `...` literal). Fixed and uploaded to S3.
- **Status:** Glue Job (`hirenovik-cleaning-job-dev`) runs successfully and generates clean Parquets. Glue Crawler runs successfully and generates exactly 1 `jobs` table. Data is queryable via Athena.

### 2. ML Strategy Adapted (Overcoming AWS Quotas)
- **Blocker:** AWS account has a hard limit of `0` for `ml.m5.large` training instances. Requesting an increase takes 24-48 hours, incompatible with the project deadline.
- **Solution (Opción B):** Train the XGBoost model locally on the prepared training dataset (`s3://hirenovik-raw-dev/training-data/...`). Package the model artifact into `model.tar.gz` (SageMaker standard format), upload it directly to S3 (`hirenovik-models-dev`), and deploy the SageMaker Serverless Endpoint via Terraform.
- **Status:** Training data successfully split (70/20/10) and validated. Ready for local XGBoost training and Serverless Endpoint deployment. This fully complies with the assignment rubric.

---

## Phase 2 Stabilization (June 18, 2026)

### 1. Infrastructure Stabilization (fix/infrastructure-stabilization)
- **Glue Crawler:** Switched source from Raw CSV to Curated Parquet (`s3://hirenovik-curated-dev/jobs/`). Parquet has embedded schema so the crawler generates exactly 1 table. Read path scoped to `ingestion_date=*/` only, ignoring `checkpoint/` and loose files.
- **Glue Job (`clean_and_curate.py`):** Removed redundant salary filter that was incorrectly filtering null-salary records. Single outlier filter: 5k-150k MXN range. Added career count >= 30 filter for training eligibility via `is_valid_for_training` flag. Fixed dedup to use `dropDuplicates` + window-based keep-latest.
- **SageMaker:** XGBoost prebuilt image bumped from 1.5-1 to 1.7-1.
- **CloudWatch Dashboard:** Simplified SageMaker error widget from expression-based to single-value to avoid expression evaluation issues in CloudWatch.
- **.gitignore:** Added `.atl/` (AI assistant internals), `debug_*.html` (scraper dumps), scratch/draft files, personal notes, screenshots.

### 2. Test Suite (test/phase2-test-suite)
- **98 tests across 5 files, all passing in <1 second.**
- `test_transform.py` (37 tests): `clean()`, `detect_state()`, `detect_job_type()`, `extract_salary_from_text()`, `transform_data()` — edge cases including NaN, None, empty, unknown values.
- `test_salary_parsing.py` (20 tests): `_parse_salary()` from both Computrabajo and OCC scrapers, parametrized. NaN regression test that catches the silent salary corruption bug.
- `test_loaders.py` (5 tests): `load_data()` dedup counts, rollback on error, `rowcount=-1` driver fallback.
- `test_pipeline.py` (10 tests): `_map_phase1_records()` status lifecycle — PENDING_ENRICHMENT on insert, null job_url skip, job_type case mapping, state detection.
- `test_glue_features.py` (26 tests): Salary mid/USD conversion, outlier filter (MXN 5k-150k range), seniority regex (3/2/0/1 mapping), modality encoding, keyword word-boundary matching, career count filter. Uses pandas (no PySpark/Java dependency needed).

### 3. Configuration
- **pyproject.toml:** Added `pythonpath = ["src"]` and `addopts = "-v --tb=short"` to pytest config.
- **requirements.txt:** Added `pytest>=8.0`, `pytest-mock>=3.12`, `pytest-cov>=5.0`.
- **Run tests:** `pytest` or `pytest -v` or `pytest --cov=src --cov-report=term-missing`.

### 4. Bugs Found During Testing
- **Seniority regex in Glue job:** "Semi-Senior Developer" gets seniority=3 (incorrect) instead of 2. Root cause: `rlike("senior|sr\\.|...")` matches "senior" as substring of "semi-senior". Fix: reorder `when()` chains so `semi-senior|mid|intermediate|ssr` pattern is checked BEFORE `senior|sr\\.|lead|principal|staff`.
- **Keyword features count:** AGENTS.md previously said 38 keyword features. The actual code has 39. The extra one is `scikit` (counted correctly now).

---

## Phase 3 -- Product Layer (June 19-20, 2026)

Phase 3 transforms the project from a data pipeline into a full-stack ML product: NLP topic modeling, semantic search, FastAPI backend, and Streamlit dashboard.

### Architecture

```
src/nlp/           ← BERTopic + FAISS semantic search (DONE, Chunk 1)
src/api/           ← FastAPI backend (DONE, Chunk 2)
src/frontend/      ← Next.js 16 dashboard (DONE, Phase 4)
```

### Chunk 0 -- Cleanup + Model Training (DONE, June 19)

- **Seniority regex fixed:** `src/glue_jobs/clean_and_curate.py` -- reordered `when()` chains (semi-senior before senior), added word boundary anchors. Branch: `fix/seniority-regex`.
- **Local XGBoost trainer committed:** `src/ml/training/train_local.py` -- trains XGBoost on CPU in SageMaker-compatible format (model.tar.gz). Branch: `feat/local-xgboost-trainer`.
- **Inference fixtures:** `src/ml/inference/fixtures/candidato_demo.json` and `edgar_junior.json` -- realistic profile vectors for endpoint testing.
- **Model trained:** XGBoost trained on 1,000+ records (55 trees, eval RMSE ~1147). Artifact uploaded to `s3://hirenovik-models-dev/xgboost/model.tar.gz` (25KB).

### Chunk 1 -- BERTopic + Semantic Search (DONE, June 20)

Branch: `feat/nlp-pipeline` (6 commits, 17 files, 2,285 lines, 76 new tests).

**Package structure:**
```
src/nlp/
  __init__.py
  pipeline.py            ← single entry point: python -m src.nlp.pipeline
  preprocess.py          ← load_and_clean() from Supabase (TextPreprocessor class)
  embedder.py            ← sentence-transformers with SHA-256 disk cache (Embedder class)
  topic_model.py         ← BERTopic training + keyword extraction + DB assignment (TopicModel class)
  search_engine.py       ← FAISS index + iterative query expansion (SearchEngine class)
  trends.py              ← weekly topic frequency + avg salary trends (TopicTrends class)
  models/                ← gitignored: bertopic_model.pkl, faiss_index.bin, id_mapping.json, etc.
```

**Key features:**
- BERTopic unsupervised topic discovery on 6,300 job descriptions (multilingual, ES/EN)
- Topic assignment stored in existing `keywords_json` JSONB column (no schema migration)
- FAISS cosine similarity index over 384-dim embeddings (~10MB in RAM)
- Iterative query expansion (Pacheco feedback): 3 rounds, centroid drift, cosine threshold 0.7
- Heavy dependencies lazy-imported (bertopic, faiss, sentence-transformers) -- modules import cleanly without them
- All classes dual-purpose: `__init__()` for pipeline creation, `load()` classmethod for API reuse in Chunk 2
- SHA-256 embedding cache prevents re-encoding on subsequent runs

**Test coverage:** 100 new tests across 7 test files (`tests/nlp/`), all passing. Test stubs inject fake bertopic/faiss into `sys.modules` so no real models are downloaded during CI.

**Dependencies added to requirements.txt:**
```
sentence-transformers>=3.0,<4.0
bertopic>=0.16,<1.0
faiss-cpu>=1.8,<2.0
```

**Active branches (local only, not pushed):**
| Branch | Content | Status |
|--------|---------|--------|
| `fix/seniority-regex` | Seniority regex fix in Glue job | Ready |
| `feat/local-xgboost-trainer` | Local XGBoost trainer + inference fixtures | Ready |
| `feat/nlp-pipeline` | Full NLP pipeline (6 commits) | Ready |
| `feat/fastapi-backend` | FastAPI backend (9 commits) | Merged to main |
| `fix/bert-output-quality` | BERT output quality fixes (1 commit) | Merged to main |
| `feat/nextjs-frontend` | Next.js 16 dashboard with 9 routes (5 commits) | Ready to merge |

### Chunk 2 -- FastAPI Backend (DONE, June 20)

Branch: `feat/fastapi-backend` from main. 9 commits, 33 files, 1,849 lines, 28 new tests (205 total).

**Architecture:** Router/service separation per FastAPI conventions. All NLP/ML models loaded optimistically at startup into `app.state`. Endpoints return 503 when models unavailable. Services never import FastAPI.

**Endpoints (10 total):**
| Endpoint | Description |
|----------|-------------|
| `GET /` | Health check + model availability status |
| `GET /jobs` | Paginated job listings with career/country/job_type filters |
| `GET /jobs/{id}` | Single job detail |
| `GET /topics` | BERTopic topic list with counts and avg salary |
| `GET /topics/{id}` | Topic detail: keywords, representative jobs |
| `GET /trends?topic_id=N` | Weekly frequency + avg salary + trending flag |
| `POST /skills/extract` | Keyword extraction from free text (39-keyword regex) |
| `POST /search` | FAISS cosine similarity search |
| `POST /topics/expand` | Iterative query expansion (Pacheco): 3 rounds, centroid drift |
| `POST /predict/salary` | XGBoost prediction from skill list (not raw features) |

**Key decisions:**
- `POST /predict/salary` accepts `skills: ["python","aws"]` instead of 39 binary flags -- conversion internal
- `POST /topics/expand` exposes `SearchEngine.expand()` -- the Pacheco feedback feature
- `Dockerfile.api` at repo root: multi-stage build, non-root user, health check
- pydantic-settings for all configuration, no `os.getenv()` in service code

### Chunk 2.5 -- BERT Output Quality Fixes (DONE, June 22)

Branch: `fix/bert-output-quality` (merged into main, 1 commit, 12 files, 759 lines, 24 new tests).

**Problems found during live API testing:**
- 464 garbage topics dominated by stopwords ("de_and_en_to", "ntt_data")
- Search returned duplicate scores (same vector indexed multiple times)
- `GET /topics/{id}/examples` returned 404
- Pipeline crashed on `compute_trends` (salary columns missing from query)

**Fixes applied:**

| Fix | What Changed | Files |
|-----|-------------|-------|
| Stopword filtering | 160+ ES/EN words added to CountVectorizer, `nr_topics="auto"`, `min_topic_size` 10->30 | `topic_model.py` |
| Garbage cleanup | "please click here", "ntt ntt", repeated adjacent words stripped | `preprocess.py` |
| HDBSCAN crash | `min_topic_size` -> `min_cluster_size` (wrong parameter name and missing `min_samples`, `prediction_data`) | `topic_model.py` |
| Duplicate scores | `build_index` deduplicates by `job_id`, warns on removed dupes | `search_engine.py` |
| Examples 404 | `_topic_docs` save moved AFTER population (was before); `_embeddings` persisted as `.npy` for centroid computation | `pipeline.py`, `search_engine.py` |
| Trends crash | `salary_min`, `salary_max` added to `_LOAD_QUERY` | `preprocess.py` |
| Missing `yield`/routers | `yield` added to lifespan context manager; router `include_router` calls restored | `main.py` |

**Quality improvements:**
- Per-topic coherence score (mean cosine similarity to centroid) in `GET /topics` response
- `GET /topics/{id}/examples?k=5` -- returns k jobs closest to topic centroid
- `size_distribution` (min/max/median/std) in topic list response metadata

**Results:**
- Topics reduced from 464 to 80 (89 pre-`nr_topics=auto` merge)
- Topic names now meaningful: "python_experience_backend_development", "cloud_aws_azure_security", "devops_azure_ci_cd"
- Coherence scores range 0.63-1.0 (topic 0 at 0.65, most specialized topics >0.85)
- FAISS index deduplicated, search scores no longer identical
- Pipeline runs end-to-end with GPU: ~2 min (was ~12 min on CPU)
- All model artifacts on disk: `bertopic_model.pkl`, `topic_keywords.json`, `topic_coherence.json`, `topic_docs.json`, `faiss_index.bin`, `id_mapping.json`, `embeddings.npy`, `topic_stats.json`

### Phase 4 -- Next.js Frontend (DONE, June 22)

Branch: `feat/nextjs-frontend` (5 commits, 26 source files, 1,970 lines).

**Stack:** Next.js 16.2.9 (App Router) + Tailwind CSS v4 + recharts, JavaScript, no TypeScript.

**Architecture:** Server components for data fetching (async functions), client components (`'use client'`) for interactivity. URL-driven filters/pagination. Centralized API layer at `src/lib/api.js` with 12 functions for all 10 backend endpoints.

**Key decisions:**
- Dark-first theme with CSS variables (`@theme inline` in Tailwind v4), light/dark toggle persisted in `localStorage`
- Inline anti-flash script in `<head>`: reads `localStorage` before first paint, falls back to `prefers-color-scheme`
- `params`/`searchParams` are Promises in Next.js 16 (must `await`). Error boundaries use `unstable_retry`.
- Search and expand endpoints return `SearchResult` objects (`{job_id, score}`), not full Job records — rendered as score-based links to job detail pages
- `eslint.ignoreDuringBuilds` removed in Next.js 16 (lint no longer runs on build)

**Routes (9):**
| Route | Type | Description |
|-------|------|-------------|
| `/` | Server | Dashboard: model status, stats cards, trending topics, recent jobs |
| `/jobs` | Server | Job explorer with filters (career, country, type), pagination |
| `/jobs/[id]` | Server | Job detail + similar jobs via FAISS search |
| `/predict` | Client | Salary predictor: skill chips input, XGBoost prediction with ±15% confidence |
| `/topics` | Server | BERTopic topic browser (sort by count/coherence/salary) |
| `/topics/[id]` | Server+Client | Topic detail: keywords, example jobs, weekly trend bars |
| `/search` | Client | FAISS semantic search + 3-round iterative query expansion |
| `/trends` | Client | Topic selector + recharts BarChart/LineChart for weekly trends |

**Components (9):**
`NavBar`, `JobCard`, `TopicCard`, `SkillTag`, `JobFilters`, `JobsFilterBar`, `Pagination`, `TopicsExplorer`, `SearchBar` (inline)

**States handled on every route:** loading skeletons, empty states, error boundaries, 404 page.

**How to run:**
```bash
cd src/frontend && npm run dev
# Opens on http://localhost:3000
# Requires FastAPI backend on localhost:8000 with CORS_ORIGINS=http://localhost:3000
```

### Chunk 4 -- Docker Compose + Docs (PENDING)

docker-compose.yml (FastAPI + Next.js), README.md rewrite, demo walkthrough notes.
