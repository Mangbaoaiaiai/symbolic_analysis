import unittest

from scripts.split_osf_manifest import estimate_cost, split_rows


class SplitOsfManifestTests(unittest.TestCase):
    def test_split_is_disjoint_complete_and_cost_balanced(self):
        rows = [
            {"case_id": "f/fast_Eq", "support_status": "supported_function"},
            {"case_id": "f/heavy_Eq", "support_status": "supported_function"},
            {"case_id": "f/heavy_NEq", "support_status": "supported_function"},
            {"case_id": "f/other_Eq", "support_status": "supported_function"},
            {
                "case_id": "f/unsupported_Eq",
                "support_status": "unsupported",
            },
        ]
        historical = {
            "f/heavy_eq": {
                "failure_category": "sigkill_or_oom",
                "old_path_count": "100",
                "new_path_count": "100",
                "t_total": "600",
            },
            "f/heavy_neq": {
                "failure_category": "symbolic_timeout",
                "old_path_count": "0",
                "new_path_count": "0",
                "t_total": "600",
            },
        }

        shards = split_rows(rows, historical, 2)

        ids = [row["case_id"] for shard in shards for row in shard]
        self.assertCountEqual(ids, [row["case_id"] for row in rows])
        self.assertEqual(len(ids), len(set(ids)))
        loads = [
            sum(estimate_cost(row, historical) for row in shard)
            for shard in shards
        ]
        self.assertLess(abs(loads[0] - loads[1]), 30)


if __name__ == "__main__":
    unittest.main()
