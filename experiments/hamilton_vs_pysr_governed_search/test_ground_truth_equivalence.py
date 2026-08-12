from __future__ import annotations

import unittest

from .ground_truth_equivalence import parse_expression, verify_equivalence


class GroundTruthEquivalenceTests(unittest.TestCase):
    def test_static_algebraic_rearrangement_is_equivalent(self) -> None:
        result = verify_equivalence("static_s01", "0.5*x2*x1*x2")
        self.assertTrue(result["algebraic_equivalent"])
        self.assertTrue(result["equivalent_ground_truth"])
        self.assertEqual(result["variable_selection"]["precision"], 1.0)
        self.assertEqual(result["variable_selection"]["recall"], 1.0)

    def test_dynamic_algebraic_rearrangement_is_equivalent(self) -> None:
        result = verify_equivalence("dynamic_d01", "10*(x2 + x1/3 - x1**3/3)")
        self.assertTrue(result["algebraic_equivalent"])
        self.assertTrue(result["challenge_grid"]["numerically_equivalent"])

    def test_wrong_equation_is_not_equivalent(self) -> None:
        result = verify_equivalence("static_s01", "x1*x2**2")
        self.assertFalse(result["algebraic_equivalent"])
        self.assertFalse(result["challenge_grid"]["numerically_equivalent"])
        self.assertFalse(result["equivalent_ground_truth"])

    def test_viv_is_explicitly_not_applicable(self) -> None:
        result = verify_equivalence("viv_u248", "-161*x")
        self.assertFalse(result["applicable"])
        self.assertIsNone(result["equivalent_ground_truth"])

    def test_parser_rejects_unknown_identifiers(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown identifiers"):
            parse_expression("open(x1)", ["x1"])


if __name__ == "__main__":
    unittest.main()
