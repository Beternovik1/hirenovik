"""Weekly topic trend computation.

Aggregates topic assignments per ISO week so the FastAPI backend can
surface weekly trending topics, average salary mid-points, and
week-over-week percentage changes. Pure pandas: no DB access, no ML.
"""

import json
import logging
import os

import pandas as pd

logger = logging.getLogger(__name__)

#: Default on-disk path for the computed trends artifact.
DEFAULT_STATS_PATH = "src/nlp/models/topic_stats.json"

#: Count increase (percent) needed to flag a week as trending.
TREND_THRESHOLD_PCT = 20.0


class TopicTrends:
    """Compute weekly topic trends from assigned topic ids.

    Args:
        topic_model: Fitted TopicModel. Currently used only to keep API
            symmetry with the other NLP workers; trend computation does
            not invoke the model.
    """

    DEFAULT_STATS_PATH = DEFAULT_STATS_PATH

    def __init__(self, topic_model) -> None:  # noqa: ANN001 - duck-typed
        self.topic_model = topic_model

    def compute_weekly_trends(
        self,
        df: pd.DataFrame,
        date_column: str = "date_scraped",
    ) -> pd.DataFrame:
        """Aggregate topic counts and salary means per ISO week.

        Args:
            df: DataFrame with ``id``, ``cleaned_description``,
                ``topic_id``, ``date_scraped``, ``salary_min`` and
                ``salary_max`` columns.
            date_column: Name of the timestamp column to group by.

        Returns:
            DataFrame with columns ``week``, ``topic_id``, ``count``,
            ``avg_salary``, ``pct_change`` and ``is_trending`` sorted by
            week then topic id.
        """
        required = {"topic_id", date_column, "salary_min", "salary_max"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"Missing required columns: {sorted(missing)}")

        working = df.copy()
        working[date_column] = pd.to_datetime(working[date_column], errors="coerce")
        working = working.dropna(subset=[date_column, "topic_id"])
        working["week"] = working[date_column].dt.isocalendar().week.astype(int)
        working["year"] = working[date_column].dt.isocalendar().year.astype(int)
        working["week_label"] = (
            working["year"].astype(str) + "-W" + working["week"].astype(str).str.zfill(2)
        )
        working["salary_mid"] = (
            working[["salary_min", "salary_max"]].mean(axis=1, skipna=True)
        )

        grouped = (
            working.groupby(["week_label", "topic_id"])
            .agg(
                count=("id", "size"),
                avg_salary=("salary_mid", "mean"),
            )
            .reset_index()
            .rename(columns={"week_label": "week", "avg_salary": "avg_salary"})
        )
        grouped["avg_salary"] = grouped["avg_salary"].where(grouped["count"] > 0)
        grouped = grouped.sort_values(["topic_id", "week"]).reset_index(drop=True)
        grouped["pct_change"] = grouped.groupby("topic_id")["count"].pct_change() * 100.0
        grouped["is_trending"] = grouped["pct_change"] >= TREND_THRESHOLD_PCT
        grouped["is_trending"] = grouped["is_trending"].fillna(False)
        grouped = grouped.sort_values(["week", "topic_id"]).reset_index(drop=True)
        logger.info("Computed weekly trends for %d rows", len(grouped))
        return grouped

    def get_trending_topics(
        self,
        trends_df: pd.DataFrame,
        min_count: int = 3,
    ) -> list[int]:
        """Return topic ids that are trending, respecting ``min_count``.

        A topic is trending when at least one of its weeks has
        ``is_trending == True`` and a ``count`` >= ``min_count``.

        Args:
            trends_df: Trends DataFrame from :meth:`compute_weekly_trends`.
            min_count: Minimum per-week count for a topic to qualify.

        Returns:
            Sorted list of trending topic ids.
        """
        if trends_df.empty:
            return []
        qualifying = trends_df[
            (trends_df["is_trending"]) & (trends_df["count"] >= min_count)
        ]
        return sorted(int(t) for t in qualifying["topic_id"].unique().tolist())

    def to_dict(self, trends_df: pd.DataFrame) -> list[dict]:
        """Convert a trends DataFrame to a JSON-serializable list of dicts.

        Args:
            trends_df: Trends DataFrame.

        Returns:
            List of dicts with native Python types (int, float, bool,
            str) so :func:`json.dumps` succeeds.
        """
        records: list[dict] = []
        for row in trends_df.itertuples(index=False):
            avg_salary = row.avg_salary
            pct_change = row.pct_change
            records.append(
                {
                    "week": str(row.week),
                    "topic_id": int(row.topic_id),
                    "count": int(row.count),
                    "avg_salary": None if pd.isna(avg_salary) else float(avg_salary),
                    "pct_change": None if pd.isna(pct_change) else float(pct_change),
                    "is_trending": bool(row.is_trending),
                }
            )
        return records

    def save_trends(
        self,
        trends_df: pd.DataFrame,
        path: str = DEFAULT_STATS_PATH,
    ) -> None:
        """Persist trends as JSON to ``path``.

        Args:
            trends_df: Trends DataFrame.
            path: Destination file path.
        """
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(trends_df), fh, ensure_ascii=False, indent=2)
        logger.info("Saved topic trends to %s", path)


__all__: list[str] = ["TopicTrends", "DEFAULT_STATS_PATH"]