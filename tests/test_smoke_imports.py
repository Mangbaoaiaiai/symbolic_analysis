"""Smoke tests for the public Python entry points used by the artifact."""

from symbolic_analysis.analysis.path_constraint_features import extract_features
from symbolic_analysis.cli import main


def test_feature_extractor_imports() -> None:
    assert callable(extract_features)


def test_cli_entry_imports() -> None:
    assert callable(main)
