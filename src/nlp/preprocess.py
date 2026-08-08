"""Supabase description loader and text cleaner for the NLP pipeline.

Cleans raw job descriptions scraped from Indeed, Computrabajo, OCC, and
LinkedIn in preparation for embedding and topic modeling. The cleaning
pipeline strips HTML tags, markdown, URLs, bullet points, special
characters, and normalizes whitespace so the remaining text is suitable
for embedding with multilingual sentence-transformers.

Language-aware deep cleaning (:meth:`clean_text_deep`) applies
language-specific processing after the universal clean step: English
documents are lemmatized and negation-prefixed (mirroring the VADER
preprocessing path) while Spanish documents are left intact for
transformer-based downstream processing.
"""

import importlib.util
import logging
import re
from typing import Any, Optional

import pandas as pd
from bs4 import BeautifulSoup
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.database.models import Job, db_connect
from src.nlp.language import detect_languages

logger = logging.getLogger(__name__)

#: Query used to fetch descriptions from the jobs table.
_LOAD_QUERY = (
    "SELECT id, description, career, date_scraped, salary_min, salary_max "
    "FROM jobs "
    "WHERE description IS NOT NULL"
)

#: Regex patterns applied to plain text after HTML stripping.
_URL_PATTERN = re.compile(r"https?://\S+|www\.\S+")
_MARKDOWN_HEADER_PATTERN = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)
_MARKDOWN_BOLD_PATTERN = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_MARKDOWN_ITALIC_PATTERN = re.compile(r"\*(.+?)\*|_(.+?)_")
_MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_MARKDOWN_LIST_PATTERN = re.compile(r"^\s*[-*+]\s+", re.MULTILINE)
_BULLET_PATTERN = re.compile(r"[\u2022\u2023\u25e6\u2043\u204c\uf0b7]")
_SPECIAL_CHARS_PATTERN = re.compile(r"[^\w\s,.;:()\-/+#\u00C0-\u017F\u00C0-\u00FF]")
_WHITESPACE_PATTERN = re.compile(r"\s+")

#: Recruiter noise and HTML artifacts that survive BS4 (applied after URLs,
#: before special-char cleanup). Each entry is a (compiled regex, replacement)
#: pair. Order matters: specific multi-word phrases run before the generic
#: repeated-word deduper so they do not get split apart first.
_GARBAGE_PATTERNS = [
    (re.compile(r"please\s+click\s+here", re.IGNORECASE), ""),
    (re.compile(r"click\s+here", re.IGNORECASE), ""),
    (re.compile(r"ntt\s+ntt", re.IGNORECASE), ""),
    (re.compile(r"ntt\s+data", re.IGNORECASE), ""),
    (re.compile(r"\b(\w+)\s+\1\b"), r"\1"),  # repeated adjacent words
]

class TextPreprocessor:
    """Load job descriptions from Supabase and clean them for NLP.

    Args:
        min_description_length: Minimum character length for a cleaned
            description to be kept. Shorter descriptions are filtered out
            during :meth:`clean_dataframe` because they carry little signal
            for embedding or topic modeling.
    """

    def __init__(self, min_description_length: int = 50) -> None:
        self.min_description_length = min_description_length
        self._nlp_en = None
        self._en_stopwords = None

    def load_descriptions(self) -> pd.DataFrame:
        """Fetch job descriptions from Supabase.

        Connects to the configured Supabase PostgreSQL instance via
        :func:`src.database.models.db_connect`, selects jobs whose
        ``description`` is not null, and returns the result as a pandas
        DataFrame.

        Returns:
            DataFrame with columns ``id``, ``description``, ``career``,
            and ``date_scraped``.

        Raises:
            RuntimeError: If the database query fails.
        """
        logger.info("Loading descriptions from Supabase")
        engine = db_connect()
        try:
            with Session(engine) as session:
                rows = session.execute(text(_LOAD_QUERY)).mappings().all()
            df = pd.DataFrame(rows)
            logger.info("Loaded %d descriptions", len(df))
            return df
        except Exception as exc:  # pragma: no cover - re-raised
            raise RuntimeError("Failed to load descriptions from Supabase") from exc
        finally:
            engine.dispose()

    def clean_text(self, text: str) -> str:
        """Clean a single job description string.

        Strips HTML tags via BeautifulSoup, removes markdown formatting
        (headers, bold/italic, links, list markers), URLs, bullet point
        characters, and other special characters, then collapses
        whitespace into single spaces.

        Args:
            text: Raw description string. May be ``None`` or empty.

        Returns:
            Cleaned text with normalized whitespace. Returns an empty
            string for non-strings or empty input.
        """
        if not isinstance(text, str) or not text.strip():
            return ""

        # Strip HTML tags (handles nested/malformed markup gracefully).
        if "<" in text and ">" in text:
            text = BeautifulSoup(text, "html.parser").get_text(separator=" ")

        # Markdown: links -> keep label text only.
        text = _MARKDOWN_LINK_PATTERN.sub(r"\1", text)
        # Markdown: bold -> unwrap emphasis.
        text = _MARKDOWN_BOLD_PATTERN.sub(lambda m: m.group(1) or m.group(2), text)
        text = _MARKDOWN_ITALIC_PATTERN.sub(lambda m: m.group(1) or m.group(2), text)
        # Markdown: headers -> remove leading # markers.
        text = _MARKDOWN_HEADER_PATTERN.sub("", text)
        # Markdown and other bullet markers.
        text = _MARKDOWN_LIST_PATTERN.sub("", text)
        text = _BULLET_PATTERN.sub("", text)
        # URLs.
        text = _URL_PATTERN.sub("", text)
        # Recruiter noise and HTML artifacts that survive BS4.
        for pattern, repl in _GARBAGE_PATTERNS:
            text = pattern.sub(repl, text)
        # Special characters (preserve accented Latin letters).
        text = _SPECIAL_CHARS_PATTERN.sub(" ", text)
        # Whitespace normalization.
        text = _WHITESPACE_PATTERN.sub(" ", text).strip()
        return text

    def clean_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply :meth:`clean_text` to a descriptions DataFrame.

        Adds a ``cleaned_description`` column, filters out rows whose
        cleaned text is shorter than ``min_description_length``, and
        returns a new DataFrame without mutating the input.

        Args:
            df: DataFrame with a ``description`` column.

        Returns:
            Copy of ``df`` with a ``cleaned_description`` column and rows
            shorter than the minimum length removed.
        """
        result = df.copy()
        result["cleaned_description"] = (
            result["description"].apply(lambda value: self.clean_text(value)).astype(str)
        )
        mask = result["cleaned_description"].str.len() >= self.min_description_length
        filtered = result.loc[mask].reset_index(drop=True)
        logger.info(
            "Cleaned %d descriptions, kept %d after length filter",
            len(df),
            len(filtered),
        )
        return filtered

    def load_and_clean(self) -> pd.DataFrame:
        """Convenience wrapper: load descriptions then deep-clean them.

        Returns:
            Cleaned DataFrame as produced by :meth:`clean_dataframe_deep`
            applied to :meth:`load_descriptions`.
        """
        raw = self.load_descriptions()
        return self.clean_dataframe_deep(raw)

    # ── Language-aware deep cleaning ────────────────────────────────

    def _load_en_nlp(self) -> None:
        """Lazy-load the English spaCy model and NLTK stopwords."""
        if self._nlp_en is not None:
            return

        if importlib.util.find_spec("spacy") is None:
            logger.warning("spaCy not installed — English deep cleaning disabled.")
            return

        import spacy

        try:
            self._nlp_en = spacy.load("en_core_web_sm")
        except Exception:
            logger.warning("en_core_web_sm not available — English deep cleaning disabled.")
            self._nlp_en = None

        if importlib.util.find_spec("nltk") is not None:
            try:
                from nltk.corpus import stopwords as nltk_stopwords

                self._en_stopwords = set(nltk_stopwords.words("english"))
            except Exception:
                logger.warning("NLTK English stopwords not available.")
                self._en_stopwords = set()

    def clean_text_deep(self, text: str, lang: str) -> str:
        """Return universally-cleaned text unchanged.

        Language-specific lemmatization is deliberately skipped for all
        languages. The multilingual transformer (paraphrase-multilingual-
        MiniLM-L12-v2) handles morphology natively in the embedding
        space, and spaCy lemmatization on short technical EN job text
        produces garbled keywords (e.g. "two_box", "service_difference",
        "datum") that poison c-TF-IDF topic representations.

        Args:
            text: Universally cleaned text string.
            lang: Language code (``"en"`` or ``"es"``). Ignored — all
                languages pass through unchanged.

        Returns:
            Cleaned text string, identical to the input ``text``.
        """
        if not text or not text.strip():
            return ""
        return text

    def clean_dataframe_deep(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply universal + language-aware deep cleaning to a DataFrame.

        Detects the language of each row, applies :meth:`clean_text`
        (universal) then :meth:`clean_text_deep` (language-specific),
        and returns a new DataFrame with ``cleaned_description`` and
        ``lang`` columns.

        Args:
            df: DataFrame with a ``description`` column.

        Returns:
            Copy of ``df`` with ``cleaned_description`` and ``lang``
            columns, rows shorter than the minimum length removed.
        """
        result = df.copy()
        # Universal cleaning first.
        result["cleaned_description"] = (
            result["description"].apply(lambda value: self.clean_text(value)).astype(str)
        )

        # Detect language on the universally-cleaned text.
        result["lang"] = detect_languages(result, text_column="cleaned_description")

        # Apply deep cleaning per row based on detected language.
        result["cleaned_description"] = result.apply(
            lambda row: self.clean_text_deep(row["cleaned_description"], row["lang"]),
            axis=1,
        )

        mask = result["cleaned_description"].str.len() >= self.min_description_length
        filtered = result.loc[mask].reset_index(drop=True)

        es_count = int((filtered["lang"] == "es").sum())
        en_count = int((filtered["lang"] == "en").sum())
        logger.info(
            "Deep-cleaned %d descriptions, kept %d after length filter "
            "(ES: %d, EN: %d).",
            len(df),
            len(filtered),
            es_count,
            en_count,
        )
        return filtered


__all__: list[Any] = ["TextPreprocessor", "Job"]