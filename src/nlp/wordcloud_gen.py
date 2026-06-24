"""Word cloud images and interactive Plotly n-gram charts for outliers.

Generates professional, self-contained visual assets for outlier
analysis. Files are saved to disk (PNG for word clouds, HTML for
n-gram charts) rather than returned as base64 data URIs, because
this module supports a data pipeline, not an HTML report.

Heavy visualization dependencies (matplotlib, plotly, wordcloud,
scikit-learn) are imported lazily inside the methods that use them
so importing this module never requires optional packages.
"""

from __future__ import annotations

import importlib
import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

#: Number of top n-grams to display in each chart.
NGRAM_TOP_N = 15

#: Minimum document frequency for an n-gram to be included.
NGRAM_MIN_DF = 3

#: Word cloud dimensions (pixels).
WC_WIDTH = 1200
WC_HEIGHT = 600

#: Reproducibility seed for word cloud layout.
WC_RANDOM_SEED = 42

#: Combined Spanish + English stopwords reused from topic_model.py so
#: common function words do not dominate the visualisations.
_ES_STOPWORDS = {
    "de", "la", "que", "el", "en", "y", "a", "los", "se", "del",
    "las", "un", "por", "con", "no", "una", "su", "para", "es",
    "al", "lo", "como", "mas", "pero", "sus", "le", "ya", "o",
    "este", "si", "porque", "esta", "entre", "cuando", "muy",
    "sin", "sobre", "tambien", "me", "hasta", "hay", "donde",
    "quien", "todo", "nos", "durante", "todos", "uno", "les",
    "ni", "contra", "otros", "ese", "eso", "ante", "ellos",
    "e", "esto", "mi", "antes", "algunos", "que", "otro",
    "otras", "otra", "el", "tanto", "esa", "estos", "mucho",
    "poco", "ella", "estar", "estas", "algunas", "algo",
    "nosotros", "mi", "mis", "tu", "te", "ti", "vos",
}

_EN_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at",
    "to", "for", "of", "with", "from", "by", "as", "is", "was",
    "are", "be", "been", "being", "have", "has", "had", "do",
    "does", "did", "will", "would", "could", "should", "may",
    "might", "can", "shall", "you", "your", "we", "our", "they",
    "them", "their", "it", "its", "he", "she", "his", "her",
    "this", "that", "these", "those", "not", "no", "if", "so",
    "than", "then", "also", "just", "now", "very", "too", "all",
    "some", "any", "each", "every", "both", "few", "more", "most",
    "other", "such", "only", "own", "same", "into", "up", "out",
    "about", "over", "after", "before", "between", "under",
    "again", "further", "here", "there", "when", "where", "why",
    "how", "which", "who", "whom", "what",
}

#: Default combined ES + EN stopwords.
DEFAULT_STOPWORDS = _ES_STOPWORDS | _EN_STOPWORDS

#: N-gram size to filename suffix mapping.
_NGRAM_SUFFIX = {1: "unigrams", 2: "bigrams", 3: "trigrams"}


def _check_dep(module_name: str) -> bool:
    """Check if a module is importable, logging a warning if not."""
    spec = importlib.util.find_spec(module_name)
    if spec is None:
        logger.warning("Optional dependency '%s' not installed.", module_name)
        return False
    return True


def _empty_chart_html(message: str) -> str:
    """Return a minimal HTML page with a text annotation.

    Args:
        message: Text to display in the empty chart.

    Returns:
        Self-contained HTML string.
    """
    return (
        "<!DOCTYPE html>\n<html>\n<head><meta charset='utf-8'>\n"
        f"<title>{message}</title>\n</head>\n<body>\n"
        f"<p style='font-family:sans-serif;font-size:16px;text-align:center;"
        f"margin-top:40vh'>{message}</p>\n"
        "</body>\n</html>"
    )


class OutlierVisualizer:
    """Generate word clouds and n-gram charts for outlier analysis.

    Args:
        stopwords: Set of stopword strings to filter from the
            visualisations. If ``None``, uses :data:`DEFAULT_STOPWORDS`.
    """

    def __init__(self, stopwords: set[str] | None = None) -> None:
        self._stopwords = stopwords if stopwords is not None else set(DEFAULT_STOPWORDS)

    # ── Public API ─────────────────────────────────────────────────

    def generate(
        self,
        df: pd.DataFrame,
        output_dir: Path,
    ) -> dict[str, str]:
        """Generate word cloud + n-gram charts for outlier documents.

        Args:
            df: Outlier DataFrame with a ``cleaned_description`` column.
            output_dir: Directory to save image and HTML files.

        Returns:
            Dict with keys ``wordcloud_path``, ``unigrams_path``,
            ``bigrams_path``, ``trigrams_path`` (file paths as strings).
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        if df.empty:
            logger.warning(
                "No outliers detected. Returning empty placeholder files."
            )
            return {
                "wordcloud_path": "",
                "unigrams_path": "",
                "bigrams_path": "",
                "trigrams_path": "",
            }

        text = " ".join(df["cleaned_description"].dropna().tolist())

        wordcloud_path = self._generate_wordcloud(text, output_dir)
        unigrams_path = self._generate_ngram_chart(df, 1, output_dir)
        bigrams_path = self._generate_ngram_chart(df, 2, output_dir)
        trigrams_path = self._generate_ngram_chart(df, 3, output_dir)

        return {
            "wordcloud_path": str(wordcloud_path),
            "unigrams_path": str(unigrams_path),
            "bigrams_path": str(bigrams_path),
            "trigrams_path": str(trigrams_path),
        }

    # ── Word cloud ─────────────────────────────────────────────────

    def _generate_wordcloud(
        self,
        text: str,
        output_dir: Path,
    ) -> Path:
        """Build and save a word cloud PNG.

        Args:
            text: Concatenated outlier text.
            output_dir: Directory to save the PNG file.

        Returns:
            Path to the saved word cloud PNG.
        """
        out_path = output_dir / "outliers_wordcloud.png"

        if not _check_dep("wordcloud") or not _check_dep("matplotlib"):
            logger.warning(
                "WordCloud or matplotlib not installed. "
                "Cannot generate outlier word cloud."
            )
            out_path.write_text("wordcloud dependency missing", encoding="utf-8")
            return out_path

        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from wordcloud import STOPWORDS as WC_STOPWORDS, WordCloud

        wc_stop = self._stopwords | WC_STOPWORDS

        # Guard: all-stopword text produces no tokens.
        tokens = [w for w in text.split() if w.lower() not in wc_stop]
        if not tokens:
            logger.warning(
                "No non-stopword tokens for outlier word cloud. "
                "Returning empty image."
            )
            fig, ax = plt.subplots(figsize=(12, 6))
            ax.axis("off")
            fig.savefig(str(out_path), dpi=100, bbox_inches="tight")
            plt.close(fig)
            return out_path

        wc = WordCloud(
            background_color="white",
            stopwords=wc_stop,
            width=WC_WIDTH,
            height=WC_HEIGHT,
            random_state=WC_RANDOM_SEED,
            colormap="viridis",
        ).generate(text)

        wc.to_file(str(out_path))
        logger.info("Saved outlier word cloud to %s", out_path)
        return out_path

    # ── N-gram charts (Plotly) ──────────────────────────────────────

    def _generate_ngram_chart(
        self,
        df: pd.DataFrame,
        n: int,
        output_dir: Path,
    ) -> Path:
        """Build and save a Plotly n-gram bar chart as self-contained HTML.

        Args:
            df: DataFrame with a ``cleaned_description`` column.
            n: N-gram size (1, 2, or 3).
            output_dir: Directory to save the HTML file.

        Returns:
            Path to the saved HTML file.
        """
        suffix = _NGRAM_SUFFIX.get(n, f"{n}grams")
        out_path = output_dir / f"outliers_{suffix}.html"

        if not _check_dep("sklearn") or not _check_dep("plotly"):
            logger.warning(
                "scikit-learn or plotly not installed. "
                "Cannot generate %d-gram chart.", n
            )
            out_path.write_text(_empty_chart_html("Dependency missing"), encoding="utf-8")
            return out_path

        from sklearn.feature_extraction.text import CountVectorizer
        import plotly.express as px

        stop_list = list(self._stopwords) if self._stopwords else None

        vectorizer = CountVectorizer(
            ngram_range=(n, n),
            stop_words=stop_list,
            max_features=NGRAM_TOP_N,
            min_df=NGRAM_MIN_DF,
            max_df=0.9,
        )

        try:
            matrix = vectorizer.fit_transform(df["cleaned_description"].dropna())
        except ValueError:
            out_path.write_text(
                _empty_chart_html(f"No {n}-grams available"),
                encoding="utf-8",
            )
            logger.warning("No %d-grams available for outlier chart.", n)
            return out_path

        frequencies = matrix.sum(axis=0).A1
        feature_names = vectorizer.get_feature_names_out()
        sorted_idx = frequencies.argsort()[::-1]
        top_features = feature_names[sorted_idx][:NGRAM_TOP_N]
        top_frequencies = frequencies[sorted_idx][:NGRAM_TOP_N]

        if len(top_features) == 0:
            out_path.write_text(
                _empty_chart_html(f"No {n}-grams available"),
                encoding="utf-8",
            )
            return out_path

        fig = px.bar(
            x=top_features,
            y=top_frequencies,
            labels={"x": "N-gram", "y": "Frequency"},
            title=f"Top {NGRAM_TOP_N} {n}-grams in Outliers",
            color_discrete_sequence=["#4c78a8"],
        )
        fig.update_xaxes(tickangle=-45)
        fig.update_traces(
            hovertemplate="<b>%{x}</b><br>Frequency: %{y}<extra></extra>"
        )

        html_standalone = fig.to_html(include_plotlyjs=True, full_html=True)
        out_path.write_text(html_standalone, encoding="utf-8")
        logger.info("Saved %d-gram chart to %s", n, out_path)
        return out_path


__all__: list[str] = ["OutlierVisualizer"]