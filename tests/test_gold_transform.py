import unittest
from datetime import datetime, timedelta

try:
    from pyspark.sql import SparkSession
except ImportError:
    SparkSession = None


@unittest.skipIf(SparkSession is None, "PySpark is available in the Spark container")
class GoldTransformTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from src.gold_transform import calculate_gold_frames

        cls.spark = (
            SparkSession.builder.master("local[2]")
            .appName("gold-transform-test")
            .config("spark.sql.defaultCatalog", "spark_catalog")
            .config("spark.sql.session.timeZone", "UTC")
            .getOrCreate()
        )
        cls.spark.sparkContext.setLogLevel("ERROR")
        cls.calculate_gold_frames = staticmethod(calculate_gold_frames)

    @classmethod
    def tearDownClass(cls):
        if SparkSession is not None:
            cls.spark.stop()

    def _frames(self):
        start = datetime(2026, 1, 1)
        rows = [
            ("video-a", start, 100, 10, None),
            ("video-a", start, 100, 10, None),
            ("video-a", start + timedelta(hours=1), 120, None, 5),
            ("video-a", start + timedelta(hours=24), 90, 8, 4),
            ("video-a", start + timedelta(hours=25, minutes=30), 150, 12, 2),
            ("video-b", start, 50, None, None),
            ("video-zero", start, 0, 1, 1),
            ("video-zero", start + timedelta(hours=25), 5, 2, 2),
        ]
        schema = (
            "video_id string, observed_at timestamp, view_count long, "
            "like_count long, comment_count long"
        )
        return self.calculate_gold_frames(self.spark.createDataFrame(rows, schema))

    def test_previous_observation_deltas_and_nullable_metrics(self):
        rows = {
            (row.video_id, row.observed_at): row
            for row in self._frames().video_metrics_hourly.collect()
        }
        start = datetime(2026, 1, 1)
        self.assertEqual(7, len(rows))
        self.assertIsNone(rows[("video-a", start)].view_delta)
        one_hour = rows[("video-a", start + timedelta(hours=1))]
        self.assertEqual(20, one_hour.view_delta)
        self.assertIsNone(one_hour.like_delta)
        self.assertIsNone(one_hour.comment_delta)
        negative = rows[("video-a", start + timedelta(hours=24))]
        self.assertEqual(-30, negative.view_delta)

    def test_exact_and_missing_hour_24h_baselines(self):
        rows = {
            (row.video_id, row.observed_at): row
            for row in self._frames().video_growth_24h.collect()
        }
        start = datetime(2026, 1, 1)
        exact = rows[("video-a", start + timedelta(hours=24))]
        self.assertEqual(-10, exact.view_delta_24h)
        self.assertEqual(-2, exact.like_delta_24h)
        self.assertIsNone(exact.comment_delta_24h)
        self.assertAlmostEqual(-0.1, exact.view_growth_rate_24h)

        missing_hour = rows[("video-a", start + timedelta(hours=25, minutes=30))]
        self.assertEqual(30, missing_hour.view_delta_24h)
        self.assertIsNone(missing_hour.like_delta_24h)
        self.assertEqual(-3, missing_hour.comment_delta_24h)
        self.assertAlmostEqual(0.25, missing_hour.view_growth_rate_24h)

    def test_insufficient_history_and_zero_denominator_are_null(self):
        rows = {
            (row.video_id, row.observed_at): row
            for row in self._frames().video_growth_24h.collect()
        }
        start = datetime(2026, 1, 1)
        self.assertIsNone(rows[("video-b", start)].view_delta_24h)
        zero = rows[("video-zero", start + timedelta(hours=25))]
        self.assertEqual(5, zero.view_delta_24h)
        self.assertIsNone(zero.view_growth_rate_24h)


if __name__ == "__main__":
    unittest.main()
