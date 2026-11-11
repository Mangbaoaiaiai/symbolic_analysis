from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import binary_identity  # noqa: E402


class BinaryIdentityTests(unittest.TestCase):
    def _fixture(self, raw: str) -> tuple[Path, dict, dict, list[dict], Path]:
        root = Path(raw)
        uid = "task"
        (root / "build/bin" / uid).mkdir(parents=True)
        (root / "build/cases" / uid / "paths").mkdir(parents=True)
        (root / "src").mkdir()
        old = root / "build/bin" / uid / "symbolic_oldV"
        new = root / "build/bin" / uid / "symbolic_newV"
        old.write_bytes(b"old-binary")
        new.write_bytes(b"new-binary")
        old.chmod(0o755)
        new.chmod(0o755)
        old_source = root / "src/old.c"
        new_source = root / "src/new.c"
        old_source.write_text("int f(void){return 0;}\n", encoding="utf-8")
        new_source.write_text("int f(void){return 1;}\n", encoding="utf-8")
        contract = {
            "schema_hash": binary_identity.canonical_json_hash([]),
            "domain_hash": "d" * 64,
            "profile_id": "ardiff_numeric_bounds_v1",
            "inputs": [],
        }
        contract_path = root / "contract.json"
        contract_path.write_text(json.dumps(contract), encoding="utf-8")
        profile = root / "profile.json"
        profile.write_text('{"profile_id":"ardiff_numeric_bounds_v1"}\n')
        build_row = {
            "task_uid": uid,
            "build_status": "completed",
            "old_process_status": "completed",
            "new_process_status": "completed",
            "old_source": "src/old.c",
            "new_source": "src/new.c",
            "old_source_sha256": binary_identity.sha256_file(old_source),
            "new_source_sha256": binary_identity.sha256_file(new_source),
            "expected_old_binary": f"build/bin/{uid}/symbolic_oldV",
            "expected_new_binary": f"build/bin/{uid}/symbolic_newV",
            "old_binary": f"build/bin/{uid}/symbolic_oldV",
            "new_binary": f"build/bin/{uid}/symbolic_newV",
            "old_binary_sha256": binary_identity.sha256_file(old),
            "new_binary_sha256": binary_identity.sha256_file(new),
        }
        paths_dir = f"build/cases/{uid}/paths"
        se_rows = [
            {
                "task_uid": uid,
                "side": side,
                "source": f"src/{side}.c",
                "binary": f"build/bin/{uid}/symbolic_{side}V",
                "paths_dir": paths_dir,
            }
            for side in ("old", "new")
        ]
        identity = binary_identity.build_task_artifact_identity(
            run_root=root,
            project_root=root,
            build_row=build_row,
            se_rows=se_rows,
            contract_path=contract_path,
            profile_path=profile,
            require_executable=False,
        )
        return root, build_row, identity, se_rows, contract_path

    def test_identity_is_built_from_exact_manifest_paths(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root, _row, identity, _se_rows, _contract = self._fixture(raw)
            self.assertEqual(identity["task_uid"], "task")
            self.assertEqual(
                Path(identity["old"]["binary_path"]).name,
                "symbolic_oldV",
            )
            self.assertTrue(
                binary_identity.validate_live_artifact_identity(
                    identity,
                    paths_dir=root / "build/cases/task/paths",
                    old_binary=root / "build/bin/task/symbolic_oldV",
                    new_binary=root / "build/bin/task/symbolic_newV",
                    task_uid="task",
                    require_executable=False,
                )["pass"]
            )

    def test_swapped_binary_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root, _row, identity, _se_rows, _contract = self._fixture(raw)
            with self.assertRaisesRegex(
                binary_identity.ArtifactIdentityError,
                "old_replay_binary_path_identity_mismatch",
            ):
                binary_identity.validate_live_artifact_identity(
                    identity,
                    paths_dir=root / "build/cases/task/paths",
                    old_binary=root / "build/bin/task/symbolic_newV",
                    new_binary=root / "build/bin/task/symbolic_oldV",
                    task_uid="task",
                    require_executable=False,
                )

    def test_post_manifest_binary_change_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root, _row, identity, _se_rows, _contract = self._fixture(raw)
            (root / "build/bin/task/symbolic_oldV").write_bytes(b"tampered")
            with self.assertRaisesRegex(
                binary_identity.ArtifactIdentityError,
                "sha256_mismatch",
            ):
                binary_identity.validate_live_artifact_identity(
                    identity,
                    paths_dir=root / "build/cases/task/paths",
                    old_binary=root / "build/bin/task/symbolic_oldV",
                    new_binary=root / "build/bin/task/symbolic_newV",
                    task_uid="task",
                    require_executable=False,
                )

    def test_missing_replay_binary_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root, _row, identity, _se_rows, _contract = self._fixture(raw)
            with self.assertRaisesRegex(
                binary_identity.ArtifactIdentityError,
                "old_replay_binary_missing",
            ):
                binary_identity.validate_live_artifact_identity(
                    identity,
                    paths_dir=root / "build/cases/task/paths",
                    old_binary=root / "build/bin/task/missing",
                    new_binary=root / "build/bin/task/symbolic_newV",
                    task_uid="task",
                    require_executable=False,
                )


class CustomProfileTests(unittest.TestCase):
    _fixture = BinaryIdentityTests._fixture
    def test_custom_profile_requires_explicit_identity_and_matching_content(self):
        with tempfile.TemporaryDirectory() as raw:
            root, row, _identity, se_rows, path = self._fixture(raw)
            contract = json.loads(path.read_text())
            profile = {"profile_id": "compiler_case_full_type_v1", "integer": {"minimum": 0, "maximum": 4294967295}}
            contract.update(profile_id=profile["profile_id"], profile=profile)
            path.write_text(json.dumps(contract))
            (root / "profile.json").write_text(json.dumps(profile))
            kwargs = dict(run_root=root, project_root=root, build_row=row,
                          se_rows=se_rows, contract_path=path, profile_path=root / "profile.json",
                          require_executable=False)
            with self.assertRaisesRegex(binary_identity.ArtifactIdentityError, "unexpected_input_domain_profile"):
                binary_identity.build_task_artifact_identity(**kwargs)
            result = binary_identity.build_task_artifact_identity(**kwargs, expected_profile_id=profile["profile_id"])
            self.assertEqual(result["profile_id"], profile["profile_id"])
            profile["integer"]["maximum"] = 100
            (root / "profile.json").write_text(json.dumps(profile))
            with self.assertRaisesRegex(binary_identity.ArtifactIdentityError, "custom_profile_contract_mismatch"):
                binary_identity.build_task_artifact_identity(**kwargs, expected_profile_id=profile["profile_id"])


if __name__ == "__main__":
    unittest.main()
