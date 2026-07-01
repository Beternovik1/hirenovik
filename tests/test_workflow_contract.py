"""Contract tests for ``.github/workflows/daily_scout.yml``.

These tests parse the real workflow file on disk (not a mocked dispatch) so
drift between the GitHub Actions runtime contract and the Python code that
relies on it is caught at test time.

Asserts the external runtime contract consumed by ``src/main.py``:
- ``EXECUTION_MODE`` is ``multi_profile_cloud_extraction``.
- ``PROFILE_COOLDOWN_SECONDS`` is ``60``.
- ``concurrency.group`` is ``daily-scout`` and ``cancel-in-progress`` is False.
- The schedule (cron) and manual (``workflow_dispatch``) triggers are present.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

WORKFLOW_PATH = (
    Path(__file__).resolve().parent.parent / ".github" / "workflows" / "daily_scout.yml"
)


def _load_workflow() -> dict:
    """Parse the daily scout workflow YAML into a dict.

    Returns:
        The parsed workflow mapping. Fails the test (via pytest.fail) if the
        file is missing or unparseable so the contract is enforced visibly.
    """
    if not WORKFLOW_PATH.exists():
        pytest.fail(f"Workflow file not found: {WORKFLOW_PATH}")
    with WORKFLOW_PATH.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _docker_env_vars(run_script: str) -> dict[str, str]:
    """Extract ``-e KEY="value"`` env vars from a workflow ``run`` script block.

    The daily scout passes runtime env vars inside a ``run: |`` docker command
    rather than the workflow ``env:`` mapping, so they must be parsed from the
    script text.

    Args:
        run_script: The raw text of the workflow ``run`` step.

    Returns:
        Mapping of env var name to its declared string value.
    """
    pattern = re.compile(r'-e\s+([A-Z_]+)="([^"]*)"')
    return {name: value for name, value in pattern.findall(run_script)}


@pytest.fixture
def workflow():
    return _load_workflow()


class TestWorkflowTriggers:
    def test_schedule_cron_present(self, workflow):
        # The scout runs daily at 12:17 UTC. Presence matters more than the
        # exact minute, which is a tunable ops detail.
        assert "schedule" in workflow[True]
        cron_entries = workflow[True]["schedule"]
        assert cron_entries, "schedule must define at least one cron entry"

    def test_workflow_dispatch_present(self, workflow):
        # Manual trigger is required for ad-hoc test runs from the Actions UI.
        # ``workflow_dispatch:`` parses to a None value, so we assert key
        # presence, not a non-None value.
        assert "workflow_dispatch" in workflow[True]


class TestWorkflowConcurrency:
    def test_concurrency_group_is_daily_scout(self, workflow):
        # A stable group name ensures scheduled and manual runs share one queue
        # so they never overlap against the same datacenter IP.
        assert workflow["concurrency"]["group"] == "daily-scout"

    def test_concurrency_does_not_cancel_in_progress(self, workflow):
        # cancel-in-progress must be False: canceling a scraper mid-run can leave
        # the DB in a partial PENDING_ENRICHMENT state.
        assert workflow["concurrency"]["cancel-in-progress"] is False


class TestWorkflowRuntimeEnv:
    def _docker_run_script(self, workflow: dict) -> str:
        steps = workflow["jobs"]["run-docker-pipeline"]["steps"]
        for step in steps:
            if step.get("name") == "Executing the container":
                return step["run"]
        pytest.fail("Executing the container step not found")

    def test_execution_mode_is_multi_profile_cloud_extraction(self, workflow):
        # Drift here would silently change the entire daily scraping behavior.
        # This pins the contract consumed by main()'s dispatch.
        env_vars = _docker_env_vars(self._docker_run_script(workflow))
        assert env_vars.get("EXECUTION_MODE") == "multi_profile_cloud_extraction"

    def test_profile_cooldown_seconds_is_60(self, workflow):
        env_vars = _docker_env_vars(self._docker_run_script(workflow))
        assert env_vars.get("PROFILE_COOLDOWN_SECONDS") == "60"

    def test_worker_name_preserved_for_scraped_by_metadata(self, workflow):
        # WORKER_NAME is the scraped_by audit label; GitHub_Actions is the
        # historical value that downstream reporting depends on.
        env_vars = _docker_env_vars(self._docker_run_script(workflow))
        assert env_vars.get("WORKER_NAME") == "GitHub_Actions"