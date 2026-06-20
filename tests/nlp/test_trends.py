"""Tests for weekly topic trend computation."""

import json

import numpy as np
import pandas as pd
import pytest

from src.nlp.trends import TopicTrends


@pytest.fixture
def trends() -> TopicTrends:
    # topic_model is duck-typed; any object works since trends do not call it.
    return TopicTrends(topic_model=object())


def _row(
    idx: int,
    topic_id: int,
    date: str,
    salary_min,
    salary_max,
) -> dict:
    return {
        "id": idx,
        "cleaned_description": f"desc {idx}",
        "topic_id": topic_id,
        "date_scraped": pd.Timestamp(date),
        "salary_min": salary_min,
        "salary_max": salary_max,
    }


def _df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


class TestComputeWeeklyTrends:
    def test_compute_weekly_trends_returns_dataframe(self, trends) -> None:
        df = _df(
            [
                _row(1, 0, "2026-05-04", 25000, 35000),
                _row(2, 0, "2026-05-06", 30000, 40000),
                _row(3, 1, "2026-05-04", 40000, 60000),
            ]
        )
        result = trends.compute_weekly_trends(df)
        assert isinstance(result, pd.DataFrame)
        assert not result.empty

    def test_compute_weekly_trends_has_required_columns(self, trends) -> None:
        df = _df([_row(1, 0, "2026-05-04", 25000, 35000)])
        result = trends.compute_weekly_trends(df)
        expected = {"week", "topic_id", "count", "avg_salary", "pct_change", "is_trending"}
        assert expected.issubset(set(result.columns))

    def test_is_trending_with_20_percent_increase(self, trends) -> None:
        # Topic 0: 5 jobs in week A (W19), 7 in week B (W20) -> 40% increase.
        rows = []
        for i in range(5):
            rows.append(_row(i, 0, "2026-05-04", 25000, 35000))
        for i in range(7):
            rows.append(_row(100 + i, 0, "2026-05-11", 25000, 35000))
        df = _df(rows)
        result = trends.compute_weekly_trends(df)
        assert result["is_trending"].any()
        later_week = result[result["week"] == "2026-W20"].iloc[0]
        assert bool(later_week["is_trending"]) is True

    def test_is_trending_with_decrease_returns_false(self, trends) -> None:
        rows = []
        for i in range(10):
            rows.append(_row(i, 0, "2026-05-04", 25000, 35000))
        for i in range(5):
            rows.append(_row(100 + i, 0, "2026-05-11", 25000, 35000))
        df = _df(rows)
        result = trends.compute_weekly_trends(df)
        assert not result["is_trending"].any()

    def test_compute_weekly_trends_handles_missing_salary(self, trends) -> None:
        df = _df(
            [
                _row(1, 0, "2026-05-04", np.nan, np.nan),
                _row(2, 0, "2026-05-04", 25000, 35000),
                _row(3, 0, "2026-05-11", None, None),
            ]
        )
        result = trends.compute_weekly_trends(df)
        # Should not crash; avg_salary for the all-NaN week (W20) must be NaN.
        assert "avg_salary" in result.columns
        nan_only_week = result[result["week"] == "2026-W20"]
        if not nan_only_week.empty:
            assert pd.isna(nan_only_week.iloc[0]["avg_salary"])

    def test_compute_weekly_trends_missing_column_raises(self, trends) -> None:
        df = pd.DataFrame({"topic_id": [0], "date_scraped": [pd.Timestamp("2026-05-04")]})
        with pytest.raises(ValueError):
            trends.compute_weekly_trends(df)

    def test_compute_weekly_trends_empty_returns_empty(self, trends) -> None:
        df = pd.DataFrame(
            columns=["id", "cleaned_description", "topic_id", "date_scraped", "salary_min", "salary_max"]
        )
        result = trends.compute_weekly_trends(df)
        assert len(result) == 0


class TestGetTrendingTopics:
    def test_get_trending_topics_filters_by_min_count(self, trends) -> None:
        rows = []
        # topic 0: 3 -> 5 (67% increase over min_count threshold)
        for i in range(3):
            rows.append(_row(i, 0, "2026-05-04", 25000, 35000))
        for i in range(5):
            rows.append(_row(100 + i, 0, "2026-05-11", 25000, 35000))
        df = _df(rows)
        trends_df = trends.compute_weekly_trends(df)
        # With min_count=5, the trending week (count=5) qualifies.
        assert 0 in trends.get_trending_topics(trends_df, min_count=5)
        # With min_count=6, no week reaches the threshold so topic 0 is excluded.
        assert 0 not in trends.get_trending_topics(trends_df, min_count=6)

    def test_get_trending_topics_returns_empty_when_none_trending(self, trends) -> None:
        rows = []
        for i in range(5):
            rows.append(_row(i, 0, "2026-05-04", 25000, 35000))
        for i in range(2):  # decrease, not trending
            rows.append(_row(100 + i, 0, "2026-05-11", 25000, 35000))
        df = _df(rows)
        trends_df = trends.compute_weekly_trends(df)
        assert trends.get_trending_topics(trends_df) == []

    def test_get_trending_topics_empty_df(self, trends) -> None:
        empty = pd.DataFrame(
            columns=["week", "topic_id", "count", "avg_salary", "pct_change", "is_trending"]
        )
        assert trends.get_trending_topics(empty) == []


class TestToDict:
    def test_to_dict_returns_json_serializable(self, trends) -> None:
        df = _df(
            [
                _row(1, 0, "2026-05-04", 25000, 35000),
                _row(2, 0, "2026-05-06", np.nan, np.nan),
                _row(3, 1, "2026-05-04", 40000, 60000),
            ]
        )
        trends_df = trends.compute_weekly_trends(df)
        records = trends.to_dict(trends_df)
        # Should not raise.
        serialized = json.dumps(records)
        assert isinstance(records, list)
        assert isinstance(serialized, str)
        for record in records:
            assert set(record.keys()) == {
                "week",
                "topic_id",
                "count",
                "avg_salary",
                "pct_change",
                "is_trending",
            }


class TestSaveTrends:
    def test_save_trends_writes_json(self, trends, tmp_path) -> None:
        df = _df([_row(1, 0, "2026-05-04", 25000, 35000)])
        trends_df = trends.compute_weekly_trends(df)
        out_path = str(tmp_path / "trends.json")
        trends.save_trends(trends_df, path=out_path)
        with open(out_path, encoding="utf-8") as fh:
            loaded = json.load(fh)
        assert isinstance(loaded, list)
        assert len(loaded) == len(trends_df)