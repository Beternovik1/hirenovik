#src/scrapers/pipeline.py
import logging
import os
import time
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


def run_local_enrichment_pipeline():
    """
    Runs locally (residential IPs).
    1. Queries the database using the existing ORM session for ALL records
       WHERE site IN ('computrabajo','occ') AND status='PENDING_ENRICHMENT'.
    2. Groups URLs by site.
    3. ANTI-BAN LOGIC (using ENRICHMENT_CONFIG):
       - Cap the total records processed per run using `daily_limit`.
       - Process the URLs in chunks based on `batch_size`.
       - Apply a time.sleep(`cooldown_seconds`) between chunks.
       - CIRCUIT BREAKER: If there are `circuit_breaker_threshold` consecutive
         errors from the SAME site, sleep for `circuit_breaker_sleep` seconds
         before continuing.
    4. Calls .enrich_descriptions() for the respective scraper.
    5. Updates the database using the ORM.
    """
    engine = db_connect()
    Session = sessionmaker(bind=engine)
    session = Session()

    config = ENRICHMENT_CONFIG
    daily_limit = config["daily_limit"]
    batch_size = config["batch_size"]
    cooldown = config["cooldown_seconds"]
    circuit_threshold = config["circuit_breaker_threshold"]
    circuit_sleep = config["circuit_breaker_sleep"]

    try:
        pending = session.query(Job).filter(
            Job.site.in_(["computrabajo", "occ"]),
            Job.status == "PENDING_ENRICHMENT",
        ).all()

        if not pending:
            logger.info("No PENDING_ENRICHMENT records found. Nothing to do.")
            return

        logger.info("Found %d records pending enrichment", len(pending))

        urls_by_site = {}
        for job in pending:
            urls_by_site.setdefault(job.site, []).append(job.job_url)

        url_to_job = {job.job_url: job for job in pending}

        total_enriched = 0
        total_orphaned = 0
        total_processed = 0

        # Split daily limit evenly between both sites so OCC does not starve.
        # If one site has fewer pending records than its half-quota,
        # the unused slots go to the other site.
        ct_count = len(urls_by_site.get("computrabajo", []))
        occ_count = len(urls_by_site.get("occ", []))
        half = daily_limit // 2

        quotas = {}
        quotas["computrabajo"] = min(ct_count, half)
        quotas["occ"] = min(occ_count, half)

        if ct_count < half:
            quotas["occ"] = min(occ_count, daily_limit - ct_count)
        elif occ_count < half:
            quotas["computrabajo"] = min(ct_count, daily_limit - occ_count)

        logger.info(
            "Enrichment quotas: Computrabajo %d, OCC %d (limit %d)",
            quotas["computrabajo"], quotas["occ"], daily_limit,
        )

        for site in ["computrabajo", "occ"]:
            if site not in urls_by_site:
                continue

            quota = quotas[site]
            if quota <= 0:
                logger.info("Quota exhausted for %s, skipping", site)
                continue

            urls = urls_by_site[site][:quota]

            if site == "computrabajo":
                scraper = ComputrabajoScraper()
            else:
                scraper = OCCScraper()

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
                    total_processed += len(batch)
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
                        total_enriched += 1
                    else:
                        job.status = "ORPHANED"
                        total_orphaned += 1

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

                total_processed += len(batch)
                session.commit()

                if i + batch_size < len(urls):
                    logger.info("Cooldown %d seconds between batches", cooldown)
                    time.sleep(cooldown)

        remaining_pending = session.query(Job).filter(
            Job.site.in_(["computrabajo", "occ"]),
            Job.status == "PENDING_ENRICHMENT",
        ).count()

        logger.info(
            "Enrichment summary — Total enriched: %d, ORPHANED: %d, Remaining PENDING_ENRICHMENT: %d",
            total_enriched, total_orphaned, remaining_pending,
        )

    except Exception as error:
        logger.error("(LOCAL ENRICHMENT) Failed: %s", error)
        raise
    finally:
        session.close()
