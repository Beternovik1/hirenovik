#src/scrapers/pipeline.py
import logging
import os
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import func
from database.models import db_connect, create_tables, Job
from etl.extract import extract_data
from etl.transform import transform_data, clean, detect_state
from etl.loaders import load_data
from shared.config import (
    NEW_SCRAPERS_CONFIG,
    ENRICHMENT_CONFIG,
    get_search_config_for_profile,
    get_profile_results_limit,
)
from scrapers.computrabajo_scraper import ComputrabajoScraper
from scrapers.occ_scraper import OCCScraper
from shared.config import include_linkedin_today
from notifications.matcher import matches_alert_geography
from notifications.profiles import get_alert_profile
from notifications.scoring import DIGEST_KEY_SCORE, score_job

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)


def _map_phase1_records(df, search_term, industry_niche):
    """Map DataFrame from Phase 1 scraper to Job model dict list."""
    worker_name = os.getenv("WORKER_NAME", "unknown")
    records = []
    # Agrega este mapeo antes de hacer el append
    JOB_TYPE_MAP = {
        "Remoto": "remoto",
        "Híbrido": "hibrido", 
        "Presencial": "presencial",
        "Remote": "remoto",
        "Hybrid": "hibrido",
    }
    for _, row in df.iterrows():
        job_url = row.get("job_url")
        if not job_url:
            logger.warning("Skipping record with null job_url for %s", search_term)
            continue
        raw_location = clean(row.get("raw_location"), "Ubicación desconocida")
        records.append({
            "site": row.get("site"),
            "job_url": row.get("job_url"),
            "title": str(clean(row.get("title"), "")).upper(),
            "company": clean(row.get("company"), "Empresa confidencial"),
            "raw_location": raw_location,
            "country": "México",
            "country_code": row.get("country_code", "MX"),
            "state": detect_state(raw_location),
            "career": search_term,
            "scraped_by": worker_name,
            "industry_niche": industry_niche,
            "job_type": JOB_TYPE_MAP.get(row.get("job_type"), row.get("job_type")),            
            "salary_min": row.get("salary_min"),
            "salary_max": row.get("salary_max"),
            "currency": clean(row.get("currency"), "MXN"),
            "description": None,
            "date_posted": row.get("date_posted"),
            "status": "PENDING_ENRICHMENT",
        })
    return records


def _filter_occ_by_alert_geography(df, industry_niche, allowed_cities):
    """Drop OCC rows whose ``raw_location`` is outside the alert geography.

    Only applied to the Industrial Bajío niche: OCC's ``scrape_metadata`` hits
    national results (``countries=["MX"]``) and would otherwise insert Industrial
    Bajío candidates from Hidalgo/CDMX/Jalisco/etc., wasting enrichment quota on
    jobs the alert can never email. Tech/general niches are NOT filtered, so the
    all-Mexico tech scrape behaviour is preserved.

    Geography semantics are reused from :func:`notifications.matcher.matches_alert_geography`
    (which delegates to the alert matcher's ``_matches_location``), so this
    filter accepts exactly the same locations the alert matcher accepts
    downstream (e.g. ``"Celaya, GUA, MX"``, ``"León, Guanajuato"``) and rejects
    the same out-of-geography ones (e.g. ``"Tizayuca, Hidalgo"``,
    ``"Leon, Nuevo Leon"``). Keeping a single source of truth for geography
    means a row that survives the insert filter is guaranteed to survive the
    matcher's geography gate too.

    Pure: no I/O, no DB. Operates only on the DataFrame read from the scraper.

    Args:
        df: OCC scraper DataFrame (must expose a ``raw_location`` column).
        industry_niche: The niche tag of the current search term
            (e.g. ``"Industrial Bajío"``).
        allowed_cities: Accent-folded lowercase city tokens defining the alert
            geography (typically the alert profile's ``allowed_cities``).

    Returns:
        A filtered DataFrame (possibly empty) with out-of-geography rows
        removed. For non-alert niches ``df`` is returned unchanged.
    """
    if df.empty or industry_niche != _ALERT_NICHE:
        return df
    # No alert profile resolved -> allowed_cities empty. Fail safe by skipping
    # the filter entirely: an empty allowed_cities would match NO city and drop
    # every Industrial Bajío row, silently emptying the OCC insert. Keeping the
    # legacy nationwide insert is preferable to a silent empty scrape.
    if not allowed_cities:
        logger.warning(
            "OCC alert geography filter: empty allowed_cities for niche '%s'; "
            "skipping filter to avoid dropping all rows.",
            industry_niche,
        )
        return df
    mask = df["raw_location"].apply(
        lambda value: matches_alert_geography(value, allowed_cities)
    )
    kept = df[mask].reset_index(drop=True)
    dropped = len(df) - len(kept)
    logger.info(
        "OCC alert geography filter for niche '%s': kept %d, dropped %d",
        industry_niche, len(kept), dropped,
    )
    return kept


def run_pipeline(search_config, results_limit, include_linkedin=False):
    engine = db_connect()
    create_tables(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        for search_term, location, industry_niche in search_config:
            logger.info(f"==> Extrayendo: {search_term} en {location} (Nicho: {industry_niche})")

            raw_df = extract_data(
                search_term=search_term,
                location=location,
                results_limit=results_limit,
                include_linkedin=include_linkedin
            )

            if raw_df.empty:
                logger.warning(f"No hay datos para: {search_term}. Saltando...")
                continue

            records = transform_data(raw_df, search_term, industry_niche)
            load_data(session, records)

    except Exception as error:
        logger.error(f"(PIPELINE) Falló: {error}")
        raise
    finally:
        session.close()
        logger.info("Conexión de base de datos cerrada.")


def run_cloud_extraction_pipeline(
    search_config,
    results_limit,
    metadata_results_limit=None,
):
    """Run Phase 1 cloud extraction on datacenter IPs.

    Runs JobSpy (Indeed; LinkedIn gated by include_linkedin_today()) and the
    Computrabajo/OCC metadata scrapers when their ``enabled`` flag is set in
    ``NEW_SCRAPERS_CONFIG``. All results insert into the DB with
    ``status='PENDING_ENRICHMENT'``.

    The ``results_limit`` controls JobSpy rows per search term. The Computrabajo
    and OCC ``scrape_metadata`` calls use ``max_results`` from
    ``NEW_SCRAPERS_CONFIG`` by default (legacy behavior). When
    ``metadata_results_limit`` is provided, it overrides both metadata scrapers'
    ``max_results`` so a profile-specific cap applies consistently across ALL
    scraper paths (JobSpy, Computrabajo, OCC). This is used by the multi-profile
    daily scout to keep low-volume industrial scrapes conservative across every
    board, not just JobSpy.

    Args:
        search_config: Iterable of ``(search_term, location, industry_niche)``.
        results_limit: JobSpy results wanted per search term.
        metadata_results_limit: Optional cap applied to Computrabajo and OCC
            ``scrape_metadata`` ``max_results``. ``None`` keeps the
            ``NEW_SCRAPERS_CONFIG`` defaults (legacy tech-only manual runs).

    Returns:
        None. Inserted/skipped counts are logged in the summary line.
    """
    engine = db_connect()
    create_tables(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    total_inserted = {"jobspy": 0, "computrabajo": 0, "occ": 0}
    total_skipped = {"jobspy": 0, "computrabajo": 0, "occ": 0}

    computrabajo_enabled = NEW_SCRAPERS_CONFIG["computrabajo"]["enabled"]
    occ_enabled = NEW_SCRAPERS_CONFIG["occ"]["enabled"]

    computrabajo_scraper = ComputrabajoScraper() if computrabajo_enabled else None
    occ_scraper = OCCScraper() if occ_enabled else None

    # When a metadata cap is passed, it applies to every board so the
    # profile-specific low-volume rule is real across all scraper paths.
    # None preserves legacy NEW_SCRAPERS_CONFIG defaults for tech-only manual runs.
    computrabajo_max = (
        metadata_results_limit
        if metadata_results_limit is not None
        else NEW_SCRAPERS_CONFIG["computrabajo"]["max_results"]
    )
    occ_max = (
        metadata_results_limit
        if metadata_results_limit is not None
        else NEW_SCRAPERS_CONFIG["occ"]["max_results"]
    )

    # Resolve the alert profile's allowed_cities once so the Phase 1 OCC insert
    # path can geography-filter Industrial Bajío rows against the exact same
    # city tokens the Phase 2 alert matcher uses. A missing profile degrades to
    # an empty tuple, which the filter treats as "skip filtering" (keep the
    # legacy nationwide insert rather than silently empty Occ).
    alert_profile = get_alert_profile(_ALERT_PROFILE_NAME)
    alert_allowed_cities = (
        alert_profile.allowed_cities if alert_profile is not None else ()
    )

    try:
        for search_term, location, industry_niche in search_config:
            logger.info("==> Cloud extraction: %s en %s (Niche: %s)", search_term, location, industry_niche)

            raw_df = extract_data(
                search_term=search_term,
                location=location,
                results_limit=results_limit,
                include_linkedin=include_linkedin_today(),
            )

            if not raw_df.empty:
                records = transform_data(raw_df, search_term, industry_niche)
                inserted, skipped = load_data(session, records)
                total_inserted["jobspy"] += inserted
                total_skipped["jobspy"] += skipped
            else:
                logger.warning("No JobSpy data for: %s", search_term)

            if computrabajo_scraper:
                logger.info("Computrabajo Phase 1 for: %s", search_term)
                df_ct = computrabajo_scraper.scrape_metadata(
                    keywords=[search_term],
                    countries=NEW_SCRAPERS_CONFIG["computrabajo"]["countries"],
                    is_remote=NEW_SCRAPERS_CONFIG["computrabajo"]["is_remote"],
                    max_results=computrabajo_max,
                )
                if not df_ct.empty:
                    records = _map_phase1_records(df_ct, search_term, industry_niche)
                    inserted, skipped = load_data(session, records)
                    total_inserted["computrabajo"] += inserted
                    total_skipped["computrabajo"] += skipped

            if occ_scraper:
                logger.info("OCC Phase 1 for: %s", search_term)
                df_occ = occ_scraper.scrape_metadata(
                    keywords=[search_term],
                    countries=["MX"],
                    is_remote=NEW_SCRAPERS_CONFIG["occ"]["is_remote"],
                    max_results=occ_max,
                )
                if not df_occ.empty:
                    # Industrial Bajío OCC rows are national by default; drop the
                    # out-of-geography ones before insert so enrichment quota is
                    # not wasted on jobs the alert can never email. Other niches
                    # keep nationwide results (tech all-Mexico behaviour).
                    df_occ = _filter_occ_by_alert_geography(
                        df_occ, industry_niche, alert_allowed_cities
                    )
                if not df_occ.empty:
                    records = _map_phase1_records(df_occ, search_term, industry_niche)
                    inserted, skipped = load_data(session, records)
                    total_inserted["occ"] += inserted
                    total_skipped["occ"] += skipped

    except Exception as error:
        logger.error("(CLOUD EXTRACTION) Failed: %s", error)
        raise
    finally:
        session.close()
        logger.info(
            "Cloud extraction summary — JobSpy: %d inserted, %d skipped | "
            "Computrabajo: %d inserted, %d skipped | "
            "OCC: %d inserted, %d skipped",
            total_inserted["jobspy"], total_skipped["jobspy"],
            total_inserted["computrabajo"], total_skipped["computrabajo"],
            total_inserted["occ"], total_skipped["occ"],
        )


def run_multi_profile_cloud_extraction(
    profiles: list[str],
    cooldown_seconds: int,
) -> None:
    """Run cloud extraction for multiple profiles sequentially in one process.

    Profiles are scraped one after another (never in parallel) so we avoid
    spawning competing scraper workflows against the same datacenter IP. A
    ``cooldown_seconds`` sleep is applied between profiles for anti-ban safety.

    Each profile gets its own conservative ``results_limit`` looked up via
    ``get_profile_results_limit``. Each profile reuses
    ``run_cloud_extraction_pipeline``, which manages its own DB session, so a
    failure in one profile does not corrupt the session of the next.

    Validation runs UP FRONT: every profile name is resolved before any scraping
    begins, so an env typo raises ``ValueError`` before a single request is made.
    This prevents a partial run where one profile scrapes and the next silently
    fails to duplicate tech rows.

    Args:
        profiles: Ordered list of profile names to run (e.g.
            ``["tech_mx", "industrial_irapuato_bajio"]``).
        cooldown_seconds: Seconds to sleep between profiles. ``0`` disables it.

    Raises:
        ValueError: If any profile name is not a key in ``SEARCH_PROFILES``.
    """
    if not profiles:
        logger.warning("No profiles configured for multi-profile scout; nothing to do.")
        return

    # Fail closed: resolve every profile's config before scraping anything so an
    # unknown name raises here, never after partial scraping has happened.
    plan = [
        (
            profile,
            get_search_config_for_profile(profile),
            get_profile_results_limit(profile),
        )
        for profile in profiles
    ]

    logger.info(
        "Multi-profile scout: %d profile(s) scheduled, cooldown %d seconds",
        len(profiles),
        cooldown_seconds,
    )

    for index, (profile, search_config, results_limit) in enumerate(plan):
        logger.info(
            "Multi-profile scout: starting profile '%s' (%d search terms, limit %d)",
            profile,
            len(search_config),
            results_limit,
        )
        # Pass the per-profile limit as BOTH JobSpy results_limit and metadata
        # max_results so the low-volume rule is real across every scraper path
        # (JobSpy, Computrabajo, OCC), not just JobSpy.
        run_cloud_extraction_pipeline(
            search_config,
            results_limit,
            metadata_results_limit=results_limit,
        )

        is_last = index == len(plan) - 1
        if not is_last and cooldown_seconds > 0:
            logger.info(
                "Cooldown %d seconds before next profile ('%s')",
                cooldown_seconds,
                profiles[index + 1],
            )
            time.sleep(cooldown_seconds)

    logger.info("Multi-profile scout completed: %d profile(s) run.", len(profiles))


# ---------------------------------------------------------------------------
# Local enrichment (Phase 2) -- alert bucket + general bucket
# ---------------------------------------------------------------------------

# Alert scorer profile name. The Industrial Bajío discovery niche is scraped
# under SEARCH_PROFILES["industrial_irapuato_bajio"] and scored against the
# subscriber's CV-informed AlertProfile registered under the same name. Kept as
# a named constant rather than a magic string so the niche->profile coupling is
# auditable in one place.
_ALERT_PROFILE_NAME = "industrial_irapuato_bajio"

# Industrial Bajío niche tag. Matches shared.config._INDUSTRIAL_BAJIO_NICHE and
# the ``industry_niche`` value carried by every SEARCH_PROFILES[
# "industrial_irapuato_bajio"] tuple. OCC scrapes national results, so without
# this gate Industrial Bajío rows pour in from Hidalgo/CDMX/Jalisco/etc.; only
# this niche is geography-filtered at insert time, tech/general stay nationwide.
_ALERT_NICHE = "Industrial Bajío"


def _partition_pending_by_bucket(jobs, alert_niche):
    """Split pending jobs into ``(alert_jobs, general_jobs)`` by industry_niche.

    Pure: no I/O, no DB. Alert jobs carry ``industry_niche == alert_niche``;
    every other job (different niche, or ``None``) is general. Partitioning in
    Python instead of two filtered SQL queries makes the exclusion rule
    trivially correct for NULL niches and lets the split be unit-tested without
    a database.

    Args:
        jobs: Iterable of Job-like objects exposing ``industry_niche``.
        alert_niche: The niche string that defines the alert bucket
            (e.g. ``"Industrial Bajío"``).

    Returns:
        ``(alert_jobs, general_jobs)`` as two lists, preserving input order.
    """
    alert_jobs = []
    general_jobs = []
    for job in jobs:
        if job.industry_niche == alert_niche:
            alert_jobs.append(job)
        else:
            general_jobs.append(job)
    return alert_jobs, general_jobs


def _split_site_quotas(urls_by_site, daily_limit):
    """Split ``daily_limit`` evenly between computrabajo and occ (anti-starvation).

    Extracted verbatim from the legacy inline logic so the existing per-site
    behavior is preserved byte-for-byte and can be unit-tested in isolation.
    Each site gets ``daily_limit // 2`` slots; if one site has fewer pending
    records than its half-quota, the unused slots flow to the other site so OCC
    is never starved when Computrabajo is light (and vice versa).

    Pure: no I/O, deterministic given inputs.

    Args:
        urls_by_site: Mapping ``site -> list[url]`` (only ``len`` is read).
        daily_limit: Total slots to split across the two sites.

    Returns:
        ``{"computrabajo": int, "occ": int}`` with each value clamped to the
        site's available pending count; the pair never exceeds ``daily_limit``.
    """
    ct_count = len(urls_by_site.get("computrabajo", []))
    occ_count = len(urls_by_site.get("occ", []))
    half = daily_limit // 2

    quotas = {"computrabajo": min(ct_count, half), "occ": min(occ_count, half)}

    if ct_count < half:
        quotas["occ"] = min(occ_count, daily_limit - ct_count)
    elif occ_count < half:
        quotas["computrabajo"] = min(ct_count, daily_limit - occ_count)

    return quotas


def _aware_utc(dt):
    """Normalize a datetime to timezone-aware UTC.

    ``date_scraped`` comes from a ``DateTime(timezone=True)`` column but may
    arrive naive depending on the driver/DB. Comparing a naive ``now`` against
    an aware DB value raises ``TypeError``, so both sides are normalized to
    aware UTC before any freshness math. ``None`` (missing) maps to the epoch
    so a job with no scrape date sorts as the oldest possible (stale), which is
    the safe default for an alert digest that should not surface unknown-age
    leads first.

    Args:
        dt: A ``datetime`` (aware or naive) or ``None``.

    Returns:
        A timezone-aware UTC ``datetime``.
    """
    if dt is None:
        return datetime.fromtimestamp(0, tz=timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _rank_alert_jobs(jobs, profile, now, freshness_days):
    """Rank alert (Industrial Bajío) pending jobs for priority enrichment.

    Ordering, most important first:

    1. **Freshness bucket** -- jobs scraped within ``freshness_days`` of ``now``
       sort before stale jobs regardless of score, so we never preferentially
       enrich old leads for a digest that will itself only email recent jobs.
    2. **CV-informed score descending** -- ``notifications.scoring.score_job``
       scores title+location against the subscriber profile (``description`` is
       ``None`` while pending, which is acceptable). Jobs the scorer rejects
       (wrong city / no role signal) fall back to score 0 so they are still
       enrichable, just lowest priority within their freshness bucket.
    3. **date_scraped descending** -- newer jobs first, a secondary recency
       tiebreaker inside each freshness/score band.
    4. **id ascending** -- stable, deterministic final tiebreaker so the same
       pending set always produces the same enrichment order across runs.

    The four criteria are folded into a single ascending sort key using
    negation for the descending fields, so one stable ``sorted`` call yields the
    full ordering deterministically.

    Pure: no I/O, no randomness. ``now`` is an explicit parameter so tests are
    deterministic; production passes ``datetime.now(timezone.utc)``.

    Args:
        jobs: Iterable of Job-like objects with ``id``, ``title``,
            ``raw_location``, ``description`` and ``date_scraped``.
        profile: The subscriber ``AlertProfile`` to score against, or ``None``
            (then every job gets score 0 and only freshness/recency/id apply).
        now: Reference ``datetime`` (aware or naive) for the freshness window.
        freshness_days: Freshness window length in days.

    Returns:
        A new list of the same job objects in ranked order. Input is never
        mutated.
    """
    aware_now = _aware_utc(now)
    cutoff = timedelta(days=freshness_days)

    def sort_key(job):
        scraped = _aware_utc(job.date_scraped)
        is_fresh = (aware_now - scraped) <= cutoff
        record = {
            "title": job.title,
            "raw_location": job.raw_location,
            "description": job.description,
        }
        score = 0
        if profile is not None:
            digest = score_job(record, profile)
            if digest is not None:
                score = digest[DIGEST_KEY_SCORE]
        # Ascending key with negated descending fields:
        # fresh(0) before stale(1), score desc, date_scraped desc, id asc.
        return (0 if is_fresh else 1, -score, -scraped.timestamp(), job.id)

    return sorted(jobs, key=sort_key)


def _enrich_site_urls(session, site, urls, url_to_job, config):
    """Enrich one site's URL list in batches, preserving anti-ban behavior.

    Encapsulates the per-site execution shared by the alert and general buckets:
    a fresh scraper per site, ``batch_size`` chunking, per-batch cooldown, a
    circuit breaker on consecutive all-fail batches, description/salary/status
    updates, and per-batch commits. Behavior is identical to the legacy
    single-bucket loop, factored out so it is reused rather than duplicated.

    Args:
        session: SQLAlchemy ORM session (commits and status updates).
        site: ``"computrabajo"`` or ``"occ"``.
        urls: Ordered list of job URLs for this site (already capped to the
            site's quota by the caller).
        url_to_job: Mapping ``job_url -> Job`` for the bucket's pending jobs.
        config: ``ENRICHMENT_CONFIG`` dict.

    Returns:
        ``{"enriched": int, "orphaned": int, "processed": int}`` for this site.
    """
    batch_size = config["batch_size"]
    cooldown = config["cooldown_seconds"]
    circuit_threshold = config["circuit_breaker_threshold"]
    circuit_sleep = config["circuit_breaker_sleep"]

    scraper = ComputrabajoScraper() if site == "computrabajo" else OCCScraper()

    totals = {"enriched": 0, "orphaned": 0, "processed": 0}
    consecutive_errors = 0

    for i in range(0, len(urls), batch_size):
        batch = urls[i:i + batch_size]
        logger.info(
            "Enriching %s batch %d/%d (%d URLs)",
            site,
            i // batch_size + 1,
            (len(urls) + batch_size - 1) // batch_size,
            len(batch),
        )

        enriched = scraper.enrich_descriptions(batch)

        if not enriched:
            logger.warning("Empty enrich result for %s batch, skipping", site)
            totals["processed"] += len(batch)
            session.commit()
            if i + batch_size < len(urls):
                time.sleep(cooldown)
            continue

        failed_urls = sum(
            1 for data in enriched.values()
            if data.get("description") is None
        )

        for url, data in enriched.items():
            job = url_to_job.get(url)
            if not job:
                continue

            description = data.get("description")

            if description is not None:
                job.description = description
                salary_raw = data.get("salary_raw")
                if salary_raw:
                    parsed_min, parsed_max = scraper._parse_salary(salary_raw)
                    if job.salary_min is None and parsed_min is not None:
                        job.salary_min = parsed_min
                        job.salary_max = parsed_max
                job.status = "NEW"
                totals["enriched"] += 1
            else:
                job.status = "ORPHANED"
                totals["orphaned"] += 1

            job.last_updated = func.now()

        if failed_urls == len(enriched):
            consecutive_errors += 1
            logger.warning(
                "Circuit breaker: %d/%d consecutive all-fail batches for %s",
                consecutive_errors, circuit_threshold, site,
            )
            if consecutive_errors >= circuit_threshold:
                logger.warning(
                    "Circuit breaker tripped for %s. Sleeping %d seconds",
                    site, circuit_sleep,
                )
                time.sleep(circuit_sleep)
                consecutive_errors = 0
        else:
            consecutive_errors = 0

        totals["processed"] += len(batch)
        session.commit()

        if i + batch_size < len(urls):
            logger.info("Cooldown %d seconds between batches", cooldown)
            time.sleep(cooldown)

    return totals


def _enrich_bucket(session, jobs, daily_limit, config, bucket_label):
    """Enrich one bucket (alert or general) up to ``daily_limit``.

    Groups the bucket's jobs by site, splits ``daily_limit`` across the two
    sites with the anti-starvation rule (:func:`_split_site_quotas`), then runs
    the shared per-site execution (:func:`_enrich_site_urls`) for each site that
    has pending work. The input order of ``jobs`` is preserved within each
    site's selected URL slice, so for the alert bucket the
    freshness/score/recency ranking drives which jobs fill each site's quota.

    Args:
        session: SQLAlchemy ORM session.
        jobs: Ordered list of pending Job objects for this bucket (ranked for
            the alert bucket, query order for the general bucket).
        daily_limit: Per-bucket daily cap (alert or general).
        config: ``ENRICHMENT_CONFIG`` dict.
        bucket_label: Human-readable label for log lines (e.g. ``"Alert"``).

    Returns:
        ``{"enriched": int, "orphaned": int, "processed": int}`` for the bucket.
    """
    if not jobs:
        logger.info("No %s PENDING_ENRICHMENT records. Nothing to do.", bucket_label)
        return {"enriched": 0, "orphaned": 0, "processed": 0}

    logger.info("Found %d %s records pending enrichment", len(jobs), bucket_label)

    url_to_job = {job.job_url: job for job in jobs}
    urls_by_site = {}
    for job in jobs:
        urls_by_site.setdefault(job.site, []).append(job.job_url)

    quotas = _split_site_quotas(urls_by_site, daily_limit)
    logger.info(
        "%s quotas: Computrabajo %d, OCC %d (limit %d)",
        bucket_label, quotas["computrabajo"], quotas["occ"], daily_limit,
    )

    totals = {"enriched": 0, "orphaned": 0, "processed": 0}
    for site in ["computrabajo", "occ"]:
        if site not in urls_by_site:
            continue

        quota = quotas[site]
        if quota <= 0:
            logger.info("Quota exhausted for %s, skipping", site)
            continue

        urls = urls_by_site[site][:quota]
        counts = _enrich_site_urls(session, site, urls, url_to_job, config)
        for key in totals:
            totals[key] += counts[key]

    return totals


def run_local_enrichment_pipeline():
    """Run Phase 2 local enrichment from residential IPs in two buckets.

    The run splits into an ALERT bucket and a GENERAL bucket that share the same
    per-site quota/cooldown/circuit-breaker execution but are otherwise
    independent:

    1. **ALERT bucket** -- ``Industrial Bajío`` pending OCC/Computrabajo rows,
       ranked by a freshness-aware CV-informed ordering, capped at
       ``alert_daily_limit`` (default 20). Runs FIRST because it feeds a later
       daily email and is small, so it must not be starved by the general bucket.
    2. **GENERAL bucket** -- every other pending OCC/Computrabajo row (tech plus
       any non-alert niche), capped at ``daily_limit`` (default 100). Excludes
       the alert niche, so no job is processed by both buckets and the total
       never exceeds ``alert_daily_limit + daily_limit``.

    A single query fetches all pending OCC/Computrabajo rows and partitions them
    in Python; each bucket then applies its own anti-starvation per-site quota
    split. Industrial jobs are the alert bucket's exclusive responsibility:
    leftover industrial jobs beyond the 20/day cap stay PENDING_ENRICHMENT for
    the next run rather than spilling into the general bucket, keeping the alert
    cap honest and avoiding a stale backlog of enriched-but-never-emailed rows.
    """
    engine = db_connect()
    Session = sessionmaker(bind=engine)
    session = Session()

    config = ENRICHMENT_CONFIG
    alert_niche = config["alert_niche"]
    alert_limit = config["alert_daily_limit"]
    general_limit = config["daily_limit"]
    freshness_days = config["alert_freshness_days"]

    try:
        pending = session.query(Job).filter(
            Job.site.in_(["computrabajo", "occ"]),
            Job.status == "PENDING_ENRICHMENT",
        ).all()

        if not pending:
            logger.info("No PENDING_ENRICHMENT records found. Nothing to do.")
            return

        logger.info("Found %d records pending enrichment", len(pending))

        alert_jobs, general_jobs = _partition_pending_by_bucket(pending, alert_niche)

        # Resolve the alert scorer profile once. A missing profile degrades
        # gracefully: ranking falls back to score 0 for every job (freshness /
        # recency / id still order the bucket) instead of crashing enrichment.
        alert_profile = get_alert_profile(_ALERT_PROFILE_NAME)
        if alert_profile is None:
            logger.warning(
                "Alert profile '%s' not found; ranking by freshness/recency only.",
                _ALERT_PROFILE_NAME,
            )

        # Alert bucket runs FIRST so the user-facing digest candidates are
        # enriched before the larger general bucket consumes scrape quota.
        ranked_alert = _rank_alert_jobs(
            alert_jobs, alert_profile, datetime.now(timezone.utc), freshness_days
        )
        alert_counts = _enrich_bucket(
            session, ranked_alert, alert_limit, config, "Alert"
        )

        # General bucket excludes the alert niche (partitioned above), so the
        # same job is never enriched twice and total <= alert_limit + general_limit.
        general_counts = _enrich_bucket(
            session, general_jobs, general_limit, config, "General"
        )

        remaining_pending = session.query(Job).filter(
            Job.site.in_(["computrabajo", "occ"]),
            Job.status == "PENDING_ENRICHMENT",
        ).count()

        logger.info(
            "Enrichment summary — Alert: enriched %d, ORPHANED %d | "
            "General: enriched %d, ORPHANED %d | Remaining PENDING_ENRICHMENT: %d",
            alert_counts["enriched"], alert_counts["orphaned"],
            general_counts["enriched"], general_counts["orphaned"],
            remaining_pending,
        )

    except Exception as error:
        logger.error("(LOCAL ENRICHMENT) Failed: %s", error)
        raise
    finally:
        session.close()
