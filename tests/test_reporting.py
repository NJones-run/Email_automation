import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from email_automation.reporting import load_distribution_config
from email_automation.reporting import load_ticket_plan_rows
from email_automation.reporting import render_email_html
from email_automation.reporting import render_distribution_plan_html
from email_automation.reporting import summarize_event
from email_automation.reporting import write_event_outputs


class ReportingTests(unittest.TestCase):
    def test_load_ticket_plan_rows(self) -> None:
        rows = load_ticket_plan_rows(Path("data/demo_ticket_plan_data.csv"))

        self.assertEqual(len(rows), 20)
        self.assertEqual(rows[0].acct_id, "A1001")
        self.assertEqual(rows[0].revenue, 850.0)

    def test_summarize_event(self) -> None:
        rows = load_ticket_plan_rows(Path("data/demo_ticket_plan_data.csv"))
        event_rows = [row for row in rows if row.plan_event_name == "2026-03-19 | Bruins vs Rangers"]
        summary = summarize_event(event_rows)

        self.assertEqual(summary.unique_accounts, 10)
        self.assertEqual(summary.total_seats, 40)
        self.assertEqual(round(summary.total_revenue, 2), 10358.00)
        self.assertEqual(summary.top_plan_type, "Suite")
        self.assertEqual(summary.data_quality["revenue_mismatch_count"], 0)

    def test_render_email_html(self) -> None:
        rows = load_ticket_plan_rows(Path("data/demo_ticket_plan_data.csv"))
        event_rows = [row for row in rows if row.plan_event_name == "2026-03-21 | Bruins vs Canadiens"]
        summary = summarize_event(event_rows)
        html = render_email_html(summary)

        self.assertIn("Executive Event Truth Attachment", html)
        self.assertIn("Executive Readout", html)
        self.assertIn("Source Of Truth Status", html)
        self.assertIn("Locked revenue is", html)
        self.assertIn("Plan Mix", html)
        self.assertIn("Price Level Mix", html)

    def test_load_distribution_config(self) -> None:
        distribution = load_distribution_config(Path("config/demo_distribution.json"))

        self.assertEqual(distribution.report_name, "Bruins Morning Event Truth Report")
        self.assertEqual(len(distribution.audiences), 2)
        self.assertEqual(distribution.audiences[0].send_time_local, "6:15 AM")

    def test_render_distribution_plan_html(self) -> None:
        distribution = load_distribution_config(Path("config/demo_distribution.json"))
        html = render_distribution_plan_html(distribution)

        self.assertIn("Distribution Governance", html)
        self.assertIn("Morning Control Sequence", html)
        self.assertIn("Audience Map", html)
        self.assertIn("bruins.executive.leadership@bruins-demo.local", html)

    def test_write_event_outputs_creates_pdf(self) -> None:
        rows = load_ticket_plan_rows(Path("data/demo_ticket_plan_data.csv"))
        event_rows = [row for row in rows if row.plan_event_name == "2026-03-19 | Bruins vs Rangers"]
        summary = summarize_event(event_rows)

        with TemporaryDirectory() as temp_dir:
            paths = write_event_outputs(summary, Path(temp_dir))

            self.assertTrue(paths["html"].exists())
            self.assertTrue(paths["pdf"].exists())
            self.assertTrue(paths["json"].exists())
            self.assertGreater(paths["pdf"].stat().st_size, 0)
            self.assertEqual(paths["pdf"].read_bytes()[:4], b"%PDF")


if __name__ == "__main__":
    unittest.main()
