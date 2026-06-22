"""Tests for the Supabase description loader and text cleaner."""

import re
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.nlp.preprocess import TextPreprocessor


class TestCleanText:
    def test_clean_text_strips_html(self) -> None:
        cleaner = TextPreprocessor()
        assert cleaner.clean_text("<p>hello</p>") == "hello"

    def test_clean_text_strips_nested_html(self) -> None:
        cleaner = TextPreprocessor()
        result = cleaner.clean_text("<div><span>hello</span> world</div>")
        assert result == "hello world"

    def test_clean_text_strips_markdown_bold(self) -> None:
        cleaner = TextPreprocessor()
        assert cleaner.clean_text("**bold** text") == "bold text"

    def test_clean_text_strips_markdown_header(self) -> None:
        cleaner = TextPreprocessor()
        assert cleaner.clean_text("# Header here") == "Header here"
        assert cleaner.clean_text("### Subsection") == "Subsection"

    def test_clean_text_strips_markdown_links(self) -> None:
        cleaner = TextPreprocessor()
        result = cleaner.clean_text("see [Google](https://google.com) now")
        assert "https://google.com" not in result
        assert "Google" in result

    def test_clean_text_strips_markdown_list(self) -> None:
        cleaner = TextPreprocessor()
        result = cleaner.clean_text("- item one\n- item two")
        assert "-" not in result
        assert "item one" in result

    def test_clean_text_strips_urls(self) -> None:
        cleaner = TextPreprocessor()
        result = cleaner.clean_text("apply at https://example.com/jobs today")
        assert "https://example.com" not in result
        assert "apply" in result and "today" in result

    def test_clean_text_strips_www_urls(self) -> None:
        cleaner = TextPreprocessor()
        result = cleaner.clean_text("visit www.example.com now")
        assert "www.example.com" not in result

    def test_clean_text_normalizes_whitespace(self) -> None:
        cleaner = TextPreprocessor()
        result = cleaner.clean_text("hello    world\n\n  foo  \tbar")
        assert result == "hello world foo bar"

    def test_clean_text_empty_returns_empty(self) -> None:
        cleaner = TextPreprocessor()
        assert cleaner.clean_text("") == ""

    def test_clean_text_none_returns_empty(self) -> None:
        cleaner = TextPreprocessor()
        assert cleaner.clean_text(None) == ""  # type: ignore[arg-type]

    def test_clean_text_preserves_accents(self) -> None:
        cleaner = TextPreprocessor()
        result = cleaner.clean_text("Título con acentos y ñ incorporados")
        assert "Título" in result and "ñ" in result

    def test_clean_text_removes_please_click_here(self) -> None:
        cleaner = TextPreprocessor()
        result = cleaner.clean_text("please click here to apply now")
        # The phrase is removed; surrounding words remain.
        assert "please click here" not in result
        assert "apply" in result

    def test_clean_text_removes_click_here(self) -> None:
        cleaner = TextPreprocessor()
        result = cleaner.clean_text("click here for more info")
        assert "click here" not in result

    def test_clean_text_removes_ntt_noise(self) -> None:
        cleaner = TextPreprocessor()
        result = cleaner.clean_text("ntt ntt data is hiring")
        assert "ntt ntt" not in result
        assert "ntt data" not in result
        assert "hiring" in result

    def test_clean_text_removes_ntt_data(self) -> None:
        cleaner = TextPreprocessor()
        result = cleaner.clean_text("ntt data engineers wanted")
        assert "ntt data" not in result

    def test_clean_text_removes_repeated_adjacent_words(self) -> None:
        cleaner = TextPreprocessor()
        result = cleaner.clean_text("python python is great great")
        # Each adjacent duplicate is collapsed to a single occurrence.
        words = result.split()
        assert words.count("python") == 1
        assert words.count("great") == 1


class TestCleanDataframe:
    def _make_df(self, descriptions: list[str]) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "id": list(range(len(descriptions))),
                "description": descriptions,
                "career": ["Data Engineer"] * len(descriptions),
                "date_scraped": pd.to_datetime(["2026-05-01"] * len(descriptions)),
            }
        )

    def test_clean_dataframe_adds_column(self) -> None:
        cleaner = TextPreprocessor(min_description_length=1)
        df = self._make_df(["<p>This is a valid description with enough text</p>"])
        result = cleaner.clean_dataframe(df)
        assert "cleaned_description" in result.columns

    def test_clean_dataframe_filters_short(self) -> None:
        cleaner = TextPreprocessor(min_description_length=50)
        df = self._make_df(
            [
                "<p>This is a very short bio</p>",  # < 50 chars
                "<p>This description is long enough to pass the filter threshold applied here</p>",
            ]
        )
        result = cleaner.clean_dataframe(df)
        assert len(result) == 1
        assert len(result.iloc[0]["cleaned_description"]) >= 50

    def test_clean_dataframe_returns_copy(self) -> None:
        cleaner = TextPreprocessor(min_description_length=1)
        df = self._make_df(["original description content here"])
        original_columns = list(df.columns)
        cleaner.clean_dataframe(df)
        assert list(df.columns) == original_columns
        assert "cleaned_description" not in df.columns

    def test_clean_dataframe_empty_input(self) -> None:
        cleaner = TextPreprocessor()
        df = self._make_df([])
        result = cleaner.clean_dataframe(df)
        assert len(result) == 0
        assert "cleaned_description" in result.columns

    def test_clean_dataframe_applied_to_all_rows(self) -> None:
        cleaner = TextPreprocessor(min_description_length=1)
        df = self._make_df(["<b>row one</b>", "<i>row two</i>"])
        result = cleaner.clean_dataframe(df)
        assert len(result) == 2
        assert result.iloc[0]["cleaned_description"] == "row one"
        assert result.iloc[1]["cleaned_description"] == "row two"


class TestLoadDescriptions:
    @patch("src.nlp.preprocess.Session")
    @patch("src.nlp.preprocess.db_connect")
    def test_load_descriptions_queries_jobs(
        self, mock_db_connect: MagicMock, mock_session_cls: MagicMock
    ) -> None:
        mock_engine = MagicMock()
        mock_db_connect.return_value = mock_engine
        mock_session = MagicMock()
        mock_session.__enter__.return_value = mock_session
        mock_session.__exit__.return_value = False
        mock_session_cls.return_value = mock_session
        rows = [
            {"id": 1, "description": "desc one", "career": "DE", "date_scraped": None, "salary_min": None, "salary_max": None}
        ]
        mock_session.execute.return_value.mappings.return_value.all.return_value = rows
        cleaner = TextPreprocessor()
        df = cleaner.load_descriptions()
        assert list(df.columns) == ["id", "description", "career", "date_scraped", "salary_min", "salary_max"]
        assert len(df) == 1
        mock_session.execute.assert_called_once()
        mock_engine.dispose.assert_called_once()

    @patch("src.nlp.preprocess.Session")
    @patch("src.nlp.preprocess.db_connect")
    def test_load_and_clean_uses_mock_db(
        self, mock_db_connect: MagicMock, mock_session_cls: MagicMock
    ) -> None:
        mock_engine = MagicMock()
        mock_db_connect.return_value = mock_engine
        mock_session = MagicMock()
        mock_session.__enter__.return_value = mock_session
        mock_session.__exit__.return_value = False
        mock_session_cls.return_value = mock_session
        rows = [
            {
                "id": 1,
                "description": "<p>This description is long enough to pass the filter</p>",
                "career": "DE",
                "date_scraped": None,
                "salary_min": None,
                "salary_max": None,
            }
        ]
        mock_session.execute.return_value.mappings.return_value.all.return_value = rows
        cleaner = TextPreprocessor(min_description_length=20)
        result = cleaner.load_and_clean()
        assert "cleaned_description" in result.columns
        assert len(result) == 1