import unittest

from microheart import bench


class BenchTests(unittest.TestCase):
    def test_percentiles(self):
        v = list(range(1, 101))
        self.assertEqual(bench.percentile(v, 50), 50)
        self.assertEqual(bench.percentile(v, 95), 95)
        self.assertEqual(bench.percentile(v, 100), 100)
        self.assertEqual(bench.percentile([7], 99), 7)

    def test_percentile_needs_values(self):
        with self.assertRaises(ValueError):
            bench.percentile([], 50)

    def test_summary_is_in_milliseconds(self):
        line = bench.summary("x", [0.5, 1.0])
        self.assertIn("min=    500", line)
        self.assertIn("max=   1000", line)


if __name__ == "__main__":
    unittest.main()
