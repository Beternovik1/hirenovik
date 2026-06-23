"""Language configuration and detection for bilingual (ES/EN) processing.

Provides metadata for supported languages (spaCy model names, NLTK
stopword corpus names, lemmatization flags, negation tokens, and
sentiment backends) plus lightweight language detection utilities
that route documents to the appropriate preprocessing path.

Language detection prefers ``langdetect`` when available and falls
back to a stopword-count heuristic so the module degrades gracefully
in minimal installations.
"""

from __future__ import annotations

import importlib.util
import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

#: Language registry — metadata only, never imports NLP models.
_LANG_CONFIGS: dict[str, dict] = {
    "es": {
        "spacy_model": "es_core_news_sm",
        "stopwords_name": "spanish",
        "use_lemmatization": False,
        "negation_tokens": (
            "no", "nunca", "jamás", "tampoco", "sin", "ni",
            "nada", "nadie", "ningún", "ninguna",
        ),
        "sentiment_backend": "pysentimiento",
    },
    "en": {
        "spacy_model": "en_core_web_sm",
        "stopwords_name": "english",
        "use_lemmatization": True,
        "negation_tokens": (
            "not", "never", "no", "neither", "nor",
            "without", "hardly", "barely", "scarcely",
        ),
        "sentiment_backend": "vader",
    },
}

#: Languages supported by this project.
SUPPORTED_LANGUAGES = frozenset(_LANG_CONFIGS)

#: Default language when detection is inconclusive.
DEFAULT_LANGUAGE = "es"

#: Spanish stopword set used by the heuristic fallback detector.
_ES_STOPWORDS = {
    "de", "la", "que", "el", "en", "y", "a", "los", "se", "del",
    "las", "un", "por", "con", "no", "una", "su", "para", "es",
    "al", "lo", "como", "mas", "pero", "sus", "le", "ya", "o",
}

#: English stopword set used by the heuristic fallback detector.
_EN_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at",
    "to", "for", "of", "with", "from", "by", "as", "is", "was",
    "are", "be", "been", "being", "have", "has", "had", "do",
}


class LanguageConfig:
    """NLP configuration metadata for a single language.

    Attributes:
        lang: ISO 639-1 language code.
        spacy_model: Name of the spaCy model to load.
        stopwords_name: NLTK stopwords corpus name.
        use_lemmatization: Whether the preprocessor should lemmatize
            (``True`` for VADER/English, ``False`` for transformer-based).
        negation_tokens: Tokens that flip sentiment polarity. Only
            meaningful for the VADER (English) path.
        sentiment_backend: ``"pysentimiento"`` or ``"vader"``.
    """

    def __init__(self, lang: str) -> None:
        config = _LANG_CONFIGS.get(lang)
        if config is None:
            raise ValueError(
                f"Unsupported language code: '{lang}'. "
                f"Supported codes: {', '.join(sorted(SUPPORTED_LANGUAGES))}."
            )
        self.lang: str = lang
        self.spacy_model: str = config["spacy_model"]
        self.stopwords_name: str = config["stopwords_name"]
        self.use_lemmatization: bool = config["use_lemmatization"]
        self.negation_tokens: tuple[str, ...] = config["negation_tokens"]
        self.sentiment_backend: str = config["sentiment_backend"]

    def __repr__(self) -> str:
        return (
            f"LanguageConfig(lang={self.lang!r}, "
            f"backend={self.sentiment_backend!r})"
        )


def _detect_with_langdetect(text: str) -> str | None:
    """Detect language using langdetect, returning None on failure.

    Args:
        text: Input text to classify.

    Returns:
        ``"es"`` or ``"en"`` if detected, ``None`` if langdetect is
        unavailable or cannot classify.
    """
    if importlib.util.find_spec("langdetect") is None:
        return None
    try:
        from langdetect import DetectorFactory, detect

        DetectorFactory.seed = 0
        result = detect(text)
        if result.startswith("es"):
            return "es"
        if result.startswith("en"):
            return "en"
        return None
    except Exception:
        logger.debug("langdetect failed for text preview: %s", text[:80])
        return None


def _detect_heuristic(text: str) -> str:
    """Detect language by counting Spanish vs English stopwords.

    Args:
        text: Input text to classify.

    Returns:
        ``"es"`` or ``"en"`` depending on which stopword set has more
        matches; defaults to :data:`DEFAULT_LANGUAGE` on a tie.
    """
    tokens = set(text.lower().split())
    es_count = len(tokens & _ES_STOPWORDS)
    en_count = len(tokens & _EN_STOPWORDS)
    if en_count > es_count:
        return "en"
    if es_count > en_count:
        return "es"
    return DEFAULT_LANGUAGE


def detect_language(text: str) -> str:
    """Detect the language of a single text.

    Uses ``langdetect`` when available, falling back to a stopword
    counting heuristic when it is not installed or fails.

    Args:
        text: Input string.

    Returns:
        ``"es"`` or ``"en"``.
    """
    if not isinstance(text, str) or not text.strip():
        return DEFAULT_LANGUAGE

    result = _detect_with_langdetect(text)
    if result is not None:
        return result

    logger.debug("langdetect unavailable or failed; using heuristic.")
    return _detect_heuristic(text)


def detect_languages(
    df: pd.DataFrame,
    text_column: str = "cleaned_description",
) -> pd.Series:
    """Detect language for every row in a DataFrame column.

    Args:
        df: DataFrame containing ``text_column``.
        text_column: Name of the text column to classify.

    Returns:
        pandas Series with ``"es"`` or ``"en"`` for each row, aligned
        with ``df`` indexes.

    Raises:
        ValueError: If ``text_column`` is not in ``df``.
    """
    if text_column not in df.columns:
        raise ValueError(
            f"Column '{text_column}' not found in DataFrame. "
            f"Available columns: {df.columns.tolist()}"
        )

    results = df[text_column].apply(detect_language)

    es_count = int((results == "es").sum())
    en_count = int((results == "en").sum())
    logger.info(
        "Language detection: %d ES docs, %d EN docs (total %d).",
        es_count,
        en_count,
        len(results),
    )
    return results


def split_by_language(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Split a DataFrame by detected language.

    Args:
        df: DataFrame with a ``cleaned_description`` column.

    Returns:
        Dict ``{"es": es_df, "en": en_df}``. Rows whose detected
        language is neither are grouped under the key matching
        :data:`DEFAULT_LANGUAGE`.
    """
    langs = detect_languages(df)
    result: dict[str, pd.DataFrame] = {"es": pd.DataFrame(), "en": pd.DataFrame()}

    work = df.copy()
    work["_lang"] = langs

    for lang, group in work.groupby("_lang"):
        key = lang if lang in result else DEFAULT_LANGUAGE
        result[key] = group.drop(columns=["_lang"]).reset_index(drop=True)

    return result


__all__: list[Any] = [
    "LanguageConfig",
    "SUPPORTED_LANGUAGES",
    "detect_language",
    "detect_languages",
    "split_by_language",
]