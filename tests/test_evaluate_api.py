import unittest

from scripts.evaluate_api import check_case, contains_all


class EvaluateApiTests(unittest.TestCase):
    def test_size_unit_spacing_is_equivalent(self):
        ok, missing = contains_all("Giới hạn là 5MB.", ["5 MB"])

        self.assertTrue(ok)
        self.assertEqual(missing, [])

    def test_must_include_any_accepts_valid_status_alternative(self):
        verdict = check_case(
            {"must_include_any": ["400", "422"]},
            {"answer": "API trả về 422.", "citations": [], "metrics": {}},
            None,
        )

        self.assertTrue(verdict["passed"])


if __name__ == "__main__":
    unittest.main()
