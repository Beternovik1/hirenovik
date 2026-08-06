# database/models.py
import os

from dotenv import load_dotenv
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base
from sqlalchemy.sql import func

load_dotenv()

Base = declarative_base()


class Job(Base):
    __tablename__ = "jobs"

    id = Column(BigInteger, primary_key=True)
    site = Column(String(50))
    job_url = Column(String, unique=True, nullable=False)
    title = Column(String, nullable=False)
    company = Column(String, nullable=False)

    # Ubicación
    raw_location = Column(Text, nullable=False)
    country = Column(String(50), default="México")
    country_code = Column(String(5))  # MX, CO, PE, CL, AR
    state = Column(String(50))

    # Negocio
    career = Column(String(100))
    scraped_by = Column(String(50))
    industry_niche = Column(String(50))
    is_premium = Column(Boolean, default=False)

    # Modalidad
    job_type = Column(String(20))

    # Salarios
    salary_min = Column(Numeric)
    salary_max = Column(Numeric)
    currency = Column(String(10), default="MXN")
    salary_source = Column(String(20))

    # NLP
    description = Column(Text)
    cleaned_description = Column(Text)
    keywords_json = Column(JSONB)

    # Description enrichment provenance (Slice 3.5)
    # NULL = never enriched; 'raw_description' = cleaned from stored text;
    # 'detail_page' = fetched from live job-board detail page.
    description_enrichment_source = Column(String(20))

    # Skill extraction (Slice 2 — canonical skills per listing)
    # ------------------------------------------------------------------
    # NULL = not yet processed; [] = processed, no known skills detected;
    # ["python","sql"] = normal result.
    # Separate from keywords_json: that column stores BERTopic topic metadata,
    # not per-listing deterministic skill evidence.
    skills_json = Column(JSONB)
    # Taxonomy version at extraction time (e.g. "1.0.0") for version-aware
    # reprocessing.
    skill_extractor_version = Column(String(32))
    # Application-supplied timestamp; NOT a server_default so the caller
    # controls when extraction was performed.
    skills_extracted_at = Column(DateTime(timezone=True))

    date_posted = Column(String)

    # Tracker
    date_scraped = Column(DateTime(timezone=True), default=func.now())
    last_updated = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())
    status = Column(String(20), default="NEW")

    __table_args__ = (
        Index("idx_niche_date", "industry_niche", "date_scraped"),
        Index("idx_geo_type", "country_code", "state", "job_type"),
        Index("idx_career_scope", "career", "job_type"),
        Index("idx_status", "status"),
    )

    def __repr__(self):
        return f"<Job(title='{self.title}', company='{self.company}', type='{self.job_type}')>"


class NotificationLog(Base):
    """Audit record of a job successfully sent in a digest email.

    One row per (job, alert profile, digest send). The selector in a later
    slice excludes jobs that already have a row for a given profile, replacing
    the blanket ``NEW -> NOTIFIED`` status flip in ``operations.mark_jobs_as_notified``
    with a profile-scoped, auditable history.

    The natural idempotence key is ``(job_id, profile_name, sent_at)``: a single
    digest send produces one ``sent_at`` timestamp shared by every job in that
    email, so re-recording the same send collides on this key and the caller
    uses ``ON CONFLICT DO NOTHING`` rather than crashing or duplicating. The
    "send once per profile" policy is enforced by the exclusion selector
    (next slice), NOT by this unique key -- the schema deliberately stays able
    to represent a job sent across distinct windows so the table remains an
    honest audit ledger even if a future policy change allows re-sends.

    ``sent_at`` is caller-supplied (NOT ``server_default``) so every row in one
    digest shares the identical digest-run timestamp, which is what makes the
    unique key meaningful. A row inserted without a timestamp fails fast
    (``NOT NULL``) rather than silently taking per-row ``now()`` values that
    would defeat idempotence.

    Recording happens only after a successful real SES send
    (``EmailResult.dry_run is False``); dry-runs never write rows, so
    ``ses_message_id`` is the real SES message id and is non-empty.
    """

    __tablename__ = "notification_log"

    id = Column(BigInteger, primary_key=True)
    # FK uses the default ON DELETE NO ACTION (effectively RESTRICT): deleting a
    # job would orphan its audit trail. There is no job-deletion path today, so
    # RESTRICT costs nothing and protects auditability. Switch to CASCADE only if
    # a job-retention prune of the log is explicitly desired later.
    job_id = Column(BigInteger, ForeignKey("jobs.id"), nullable=False)
    # Stable alert profile identifier (e.g. "industrial_irapuato_bajio"), the
    # same name registered in notifications.profiles.ALERT_PROFILES so exclusion
    # can be profile-scoped when multiple subscribers exist.
    profile_name = Column(String(100), nullable=False)
    # Single digest-run timestamp shared by every job in one email; caller-owned
    # so the (job_id, profile_name, sent_at) unique key identifies one send.
    sent_at = Column(DateTime(timezone=True), nullable=False)
    # SES MessageId returned by a real send; empty/blank never recorded.
    ses_message_id = Column(String(255), nullable=False)

    __table_args__ = (
        # Idempotence key: re-recording the same (job, profile, send) collides.
        UniqueConstraint("job_id", "profile_name", "sent_at", name="uq_notification_log_send"),
        # Drives the profile-scoped exclusion query "has this job been sent?"
        # independently of the send window, so it stays efficient even when a
        # job legitimately has rows spanning multiple windows.
        Index("idx_notification_log_profile_job", "profile_name", "job_id", unique=False),
        # Audit/debug lookup: find every job included in a given SES email.
        Index("idx_notification_log_ses_message", "ses_message_id", unique=False),
        # Temporal inspection of a profile's send history.
        Index("idx_notification_log_profile_sent", "profile_name", "sent_at", unique=False),
    )

    def __repr__(self):
        return (
            f"<NotificationLog(job_id={self.job_id}, "
            f"profile_name='{self.profile_name}', sent_at='{self.sent_at}')>"
        )


def db_connect():
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise ValueError("DATABASE_URL no encontrada en .env")

    database_url = database_url.replace("postgres://", "postgresql://")

    engine = create_engine(database_url, pool_size=5, max_overflow=10, pool_pre_ping=True)

    return engine


def create_tables(engine):
    Base.metadata.create_all(engine)
    print("Conexión exitosa con Supabase y ORM sincronizado.")


if __name__ == "__main__":
    # 1. Establecemos la conexión a Supabase
    engine = db_connect()
    # 2. Sincronizamos el modelo y mostramos el mensaje
    create_tables(engine)
    print("YA jalo jeje !!")
