import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from symbolic_analysis.analysis.bindiff_backend import (
    build_bindiff_mapping,
    load_bindiff_mapping_artifact,
)
from symbolic_analysis.analysis.hybrid_path_matching import (
    HybridConfig,
    hybrid_rank_paths,
)


PATH_TEMPLATE = """\
(declare-fun arg_0 () (_ BitVec 32))
(assert (= arg_0 (_ bv1 32)))
; Execution trace: [4194304]
"""


def write_paths(root: Path) -> tuple[Path, Path]:
    old = root / "symbolic_oldV_path_1.txt"
    new = root / "symbolic_newV_path_1.txt"
    old.write_text(PATH_TEMPLATE, encoding="utf-8")
    new.write_text(PATH_TEMPLATE, encoding="utf-8")
    return old, new


class HybridGraphPolicyTests(unittest.TestCase):
    def test_high_confidence_skips_graph_provider(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            old, new = write_paths(Path(raw_dir))
            provider = mock.Mock(side_effect=AssertionError("graph must not load"))
            result = hybrid_rank_paths(
                [old],
                [new],
                config=HybridConfig(
                    high_threshold=0.0,
                    margin_threshold=-1.0,
                ),
                graph_provider=provider,
            )
            provider.assert_not_called()
            self.assertEqual(result["queries"][0]["decision"], "feature_confident")
            self.assertEqual(result["graph_backend"]["status"], "not_loaded")

    def test_low_confidence_loads_graph_once_and_reranks(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            old, new = write_paths(root)
            second_old = root / "symbolic_oldV_path_2.txt"
            second_old.write_text(PATH_TEMPLATE, encoding="utf-8")
            provider = mock.Mock(
                return_value=(
                    {4194304: 4194304},
                    {"status": "ok", "backend": "google_bindiff_v8"},
                )
            )
            result = hybrid_rank_paths(
                [old, second_old],
                [new],
                config=HybridConfig(high_threshold=1.1),
                graph_provider=provider,
            )
            provider.assert_called_once()
            self.assertEqual(result["queries"][0]["decision"], "graph_rerank_lazy")
            self.assertEqual(result["queries"][1]["decision"], "graph_rerank")
            self.assertEqual(result["graph_backend"]["backend"], "google_bindiff_v8")

    def test_top_k_and_profile_metadata_are_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            old, new = write_paths(root)
            second_new = root / "symbolic_newV_path_2.txt"
            second_new.write_text(PATH_TEMPLATE, encoding="utf-8")
            marker_profile = {"id": "osf.test", "custom": True}
            result = hybrid_rank_paths(
                [old],
                [new, second_new],
                config=HybridConfig(
                    high_threshold=0.0,
                    margin_threshold=-1.0,
                ),
                profile_id="osf.test",
                profile=marker_profile,
                max_results_per_query=1,
            )

        self.assertEqual(result["profile_id"], "osf.test")
        self.assertIs(result["profile"], marker_profile)
        self.assertEqual(result["max_results_per_query"], 1)
        self.assertEqual(len(result["queries"][0]["ranking"]), 1)


class BinDiffFallbackTests(unittest.TestCase):
    def test_missing_tools_is_an_explicit_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            old = root / "old"
            new = root / "new"
            old.write_bytes(b"old")
            new.write_bytes(b"new")
            result = build_bindiff_mapping(
                old,
                new,
                root / "out",
                old_traces=[],
                new_traces=[],
                bindiff_binary=str(root / "missing-bindiff"),
                ghidra_headless=str(root / "missing-ghidra"),
            )
            self.assertEqual(result["status"], "unavailable")
            self.assertEqual(result["backend"], "feature_only_fallback")
            self.assertIsNone(result["mapping"])

    def test_export_timeout_is_an_explicit_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            old = root / "old"
            new = root / "new"
            old.write_bytes(b"old")
            new.write_bytes(b"new")
            bindiff = root / "bindiff"
            ghidra = root / "ghidra"
            bindiff.write_text("", encoding="utf-8")
            ghidra.write_text("", encoding="utf-8")
            script = root / "BinExportHeadless.java"
            script.write_text("", encoding="utf-8")
            with mock.patch(
                "symbolic_analysis.analysis.bindiff_backend.subprocess.run",
                side_effect=subprocess.TimeoutExpired("ghidra", 1),
            ):
                result = build_bindiff_mapping(
                    old,
                    new,
                    root / "out",
                    old_traces=[],
                    new_traces=[],
                    bindiff_binary=str(bindiff),
                    ghidra_headless=str(ghidra),
                    export_script=script,
                    timeout_seconds=1,
                )
            self.assertEqual(result["status"], "export_failed")
            self.assertEqual(result["backend"], "feature_only_fallback")
            self.assertIsNone(result["mapping"])

    def test_cache_rejects_mismatched_elf_hash(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            old = root / "old"
            new = root / "new"
            old.write_bytes(b"old")
            new.write_bytes(b"new")
            artifact = root / "basic_block_map.json"
            artifact.write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "backend": "google_bindiff_v8",
                        "old_binary_sha256": hashlib.sha256(b"different").hexdigest(),
                        "new_binary_sha256": hashlib.sha256(new.read_bytes()).hexdigest(),
                        "matching_bb_addrs": {"0x400000": "0x400000"},
                    }
                ),
                encoding="utf-8",
            )
            self.assertIsNone(
                load_bindiff_mapping_artifact(artifact, old, new)
            )


if __name__ == "__main__":
    unittest.main()
