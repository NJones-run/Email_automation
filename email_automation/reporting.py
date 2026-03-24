from __future__ import annotations

import csv
import html
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict
from typing import Iterable
from typing import List
from typing import Optional
from typing import Sequence

from .models import BreakdownRow
from .models import DistributionAudience
from .models import DistributionConfig
from .models import EventSummary
from .models import TicketPlanRow


SOURCE_COLUMNS = [
    "acct_id",
    "price_level",
    "plan_event_name",
    "num_seats",
    "plan_type",
    "section_type",
    "number_of_events",
    "full_season_equivalence",
    "ticket_price",
    "revenue",
]


def money(value: float) -> str:
    return "${0:,.2f}".format(value)


def slugify(value: str) -> str:
    pieces = []
    for char in value.lower():
        if char.isalnum():
            pieces.append(char)
        elif char in {" ", "-", "|", "_"}:
            pieces.append("-")
    slug = "".join(pieces).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "event"


def now_label() -> str:
    return datetime.now().strftime("%B %d, %Y at %I:%M %p")


def join_recipients(recipients: Sequence[str]) -> str:
    return ", ".join(recipients) if recipients else "None"


def load_distribution_config(config_path: Path) -> DistributionConfig:
    with config_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    audiences = [
        DistributionAudience(
            name=audience["name"],
            purpose=audience["purpose"],
            to_recipients=list(audience.get("to", [])),
            cc_recipients=list(audience.get("cc", [])),
            send_time_local=audience["send_time_local"],
            timezone=audience["timezone"],
            status_gate=audience["status_gate"],
            cadence=audience["cadence"],
        )
        for audience in payload.get("audiences", [])
    ]

    return DistributionConfig(
        report_name=payload["report_name"],
        sender_name=payload["sender_name"],
        sender_email=payload["sender_email"],
        reply_to=payload["reply_to"],
        distribution_owner=payload["distribution_owner"],
        latest_source_refresh=payload["latest_source_refresh"],
        final_lock_time=payload["final_lock_time"],
        demo_note=payload["demo_note"],
        audiences=audiences,
    )


def load_ticket_plan_rows(csv_path: Path) -> List[TicketPlanRow]:
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = []
        for raw_row in reader:
            rows.append(
                TicketPlanRow(
                    acct_id=raw_row["acct_id"],
                    price_level=raw_row["price_level"],
                    plan_event_name=raw_row["plan_event_name"],
                    num_seats=int(raw_row["num_seats"]),
                    plan_type=raw_row["plan_type"],
                    section_type=raw_row["section_type"],
                    number_of_events=int(raw_row["number_of_events"]),
                    full_season_equivalence=float(raw_row["full_season_equivalence"]),
                    ticket_price=float(raw_row["ticket_price"]),
                    revenue=float(raw_row["revenue"]),
                )
            )
    return rows


def group_rows_by_event(rows: Iterable[TicketPlanRow]) -> Dict[str, List[TicketPlanRow]]:
    grouped: Dict[str, List[TicketPlanRow]] = defaultdict(list)
    for row in rows:
        grouped[row.plan_event_name].append(row)
    return dict(grouped)


def build_breakdown(rows: Sequence[TicketPlanRow], attribute: str, total_revenue: float) -> List[BreakdownRow]:
    grouped: Dict[str, Dict[str, object]] = defaultdict(lambda: {"accounts": set(), "seats": 0, "revenue": 0.0})

    for row in rows:
        label = getattr(row, attribute)
        grouped[label]["accounts"].add(row.acct_id)
        grouped[label]["seats"] += row.num_seats
        grouped[label]["revenue"] += row.revenue

    breakdown = []
    for label, aggregate in grouped.items():
        seats = int(aggregate["seats"])
        revenue = float(aggregate["revenue"])
        breakdown.append(
            BreakdownRow(
                label=label,
                accounts=len(aggregate["accounts"]),
                seats=seats,
                revenue=revenue,
                average_ticket_price=(revenue / seats) if seats else 0.0,
                revenue_share=(revenue / total_revenue) if total_revenue else 0.0,
            )
        )

    return sorted(
        breakdown,
        key=lambda row: (-row.revenue, row.label),
    )


def summarize_event(rows: Sequence[TicketPlanRow]) -> EventSummary:
    if not rows:
        raise ValueError("Cannot summarize an empty event.")

    total_seats = sum(row.num_seats for row in rows)
    total_revenue = sum(row.revenue for row in rows)
    revenue_mismatch_count = sum(
        1
        for row in rows
        if round(row.ticket_price * row.num_seats, 2) != round(row.revenue, 2)
    )
    missing_required_values = sum(
        1
        for row in rows
        if not all(
            [
                row.acct_id,
                row.price_level,
                row.plan_event_name,
                row.plan_type,
                row.section_type,
            ]
        )
    )

    summary = EventSummary(
        event_name=rows[0].plan_event_name,
        row_count=len(rows),
        unique_accounts=len({row.acct_id for row in rows}),
        total_seats=total_seats,
        total_revenue=total_revenue,
        weighted_average_ticket_price=(total_revenue / total_seats) if total_seats else 0.0,
        total_full_season_equivalence=sum(row.full_season_equivalence for row in rows),
        weighted_average_events=(
            sum(row.number_of_events * row.num_seats for row in rows) / total_seats
            if total_seats
            else 0.0
        ),
        source_columns=list(SOURCE_COLUMNS),
        data_quality={
            "rows_processed": len(rows),
            "required_column_coverage": "100%" if missing_required_values == 0 else "Incomplete",
            "revenue_mismatch_count": revenue_mismatch_count,
            "missing_required_values": missing_required_values,
            "status": "Final" if revenue_mismatch_count == 0 and missing_required_values == 0 else "Review Required",
        },
    )

    summary.plan_type_breakdown = build_breakdown(rows, "plan_type", total_revenue)
    summary.section_type_breakdown = build_breakdown(rows, "section_type", total_revenue)
    summary.price_level_breakdown = build_breakdown(rows, "price_level", total_revenue)
    return summary


def breakdown_to_dict(rows: Sequence[BreakdownRow]) -> List[Dict[str, object]]:
    payload = []
    for row in rows:
        payload.append(
            {
                "label": row.label,
                "accounts": row.accounts,
                "seats": row.seats,
                "revenue": round(row.revenue, 2),
                "average_ticket_price": round(row.average_ticket_price, 2),
                "revenue_share": round(row.revenue_share, 4),
            }
        )
    return payload


def summary_to_payload(summary: EventSummary, distribution: Optional[DistributionConfig] = None) -> Dict[str, object]:
    payload = {
        "event_name": summary.event_name,
        "generated_at": now_label(),
        "status": summary.data_quality["status"],
        "source_columns": summary.source_columns,
        "topline_metrics": {
            "unique_accounts": summary.unique_accounts,
            "total_seats": summary.total_seats,
            "total_revenue": round(summary.total_revenue, 2),
            "weighted_average_ticket_price": round(summary.weighted_average_ticket_price, 2),
            "total_full_season_equivalence": round(summary.total_full_season_equivalence, 2),
            "weighted_average_events": round(summary.weighted_average_events, 2),
        },
        "highlights": {
            "top_plan_type": summary.top_plan_type,
            "top_section_type": summary.top_section_type,
            "top_price_level": summary.top_price_level,
        },
        "data_quality": summary.data_quality,
        "breakdowns": {
            "plan_type": breakdown_to_dict(summary.plan_type_breakdown),
            "section_type": breakdown_to_dict(summary.section_type_breakdown),
            "price_level": breakdown_to_dict(summary.price_level_breakdown),
        },
    }
    if distribution:
        payload["distribution"] = {
            "report_name": distribution.report_name,
            "sender_name": distribution.sender_name,
            "sender_email": distribution.sender_email,
            "reply_to": distribution.reply_to,
            "distribution_owner": distribution.distribution_owner,
            "latest_source_refresh": distribution.latest_source_refresh,
            "final_lock_time": distribution.final_lock_time,
            "audiences": [
                {
                    "name": audience.name,
                    "purpose": audience.purpose,
                    "to": audience.to_recipients,
                    "cc": audience.cc_recipients,
                    "send_time_local": audience.send_time_local,
                    "timezone": audience.timezone,
                    "status_gate": audience.status_gate,
                    "cadence": audience.cadence,
                }
                for audience in distribution.audiences
            ],
        }
    return payload


def render_columns(summary: EventSummary) -> str:
    return "".join(
        '<div class="column-chip">{0}</div>'.format(html.escape(column))
        for column in summary.source_columns
    )


def render_metric(label: str, value: str, note: str) -> str:
    return """
    <div class="metric-card">
      <div class="metric-label">{label}</div>
      <div class="metric-value">{value}</div>
      <div class="metric-note">{note}</div>
    </div>
    """.format(label=html.escape(label), value=html.escape(value), note=html.escape(note))


def render_distribution_cards(audiences: Sequence[DistributionAudience]) -> str:
    return "".join(
        """
        <article class="audience-card">
          <div class="audience-head">
            <div>
              <div class="audience-name">{name}</div>
              <div class="audience-purpose">{purpose}</div>
            </div>
            <div class="send-badge">{send_time} {timezone}</div>
          </div>
          <dl class="distribution-list">
            <div>
              <dt>To</dt>
              <dd>{to_recipients}</dd>
            </div>
            <div>
              <dt>CC</dt>
              <dd>{cc_recipients}</dd>
            </div>
            <div>
              <dt>Cadence</dt>
              <dd>{cadence}</dd>
            </div>
            <div>
              <dt>Release Rule</dt>
              <dd>{status_gate}</dd>
            </div>
          </dl>
        </article>
        """.format(
            name=html.escape(audience.name),
            purpose=html.escape(audience.purpose),
            send_time=html.escape(audience.send_time_local),
            timezone=html.escape(audience.timezone),
            to_recipients=html.escape(join_recipients(audience.to_recipients)),
            cc_recipients=html.escape(join_recipients(audience.cc_recipients)),
            cadence=html.escape(audience.cadence),
            status_gate=html.escape(audience.status_gate),
        )
        for audience in audiences
    )


def render_schedule_timeline(distribution: Optional[DistributionConfig]) -> str:
    if distribution and distribution.audiences:
        primary_audience = distribution.audiences[0]
        secondary_audience = distribution.audiences[1] if len(distribution.audiences) > 1 else None
        steps = [
            (
                distribution.latest_source_refresh,
                "Source Refresh",
                "Pull the latest event inputs into the morning file before leadership starts the day.",
            ),
            (
                distribution.final_lock_time,
                "Final Lock",
                "Reconcile and freeze the shared numbers so every audience works from the same version.",
            ),
            (
                "{0} {1}".format(primary_audience.send_time_local, primary_audience.timezone),
                primary_audience.name,
                primary_audience.purpose,
            ),
        ]
        if secondary_audience:
            steps.append(
                (
                    "{0} {1}".format(secondary_audience.send_time_local, secondary_audience.timezone),
                    secondary_audience.name,
                    secondary_audience.purpose,
                )
            )
    else:
        steps = [
            ("6:00 AM ET", "Source Refresh", "Pull the latest event inputs into the morning file."),
            ("6:10 AM ET", "Final Lock", "Reconcile and freeze the numbers for the day."),
            ("6:15 AM ET", "Executive Digest", "Release the topline report to leadership."),
        ]

    return "".join(
        """
        <div class="timeline-step">
          <div class="timeline-time">{time}</div>
          <div class="timeline-label">{label}</div>
          <div class="timeline-note">{note}</div>
        </div>
        """.format(
            time=html.escape(step[0]),
            label=html.escape(step[1]),
            note=html.escape(step[2]),
        )
        for step in steps
    )


def render_breakdown_table(title: str, rows: Sequence[BreakdownRow]) -> str:
    body = "".join(
        """
        <tr>
          <td>{label}</td>
          <td>{accounts}</td>
          <td>{seats}</td>
          <td>{revenue}</td>
          <td>{average_ticket_price}</td>
          <td>{revenue_share}</td>
        </tr>
        """.format(
            label=html.escape(row.label),
            accounts=row.accounts,
            seats=row.seats,
            revenue=html.escape(money(row.revenue)),
            average_ticket_price=html.escape(money(row.average_ticket_price)),
            revenue_share="{0:.1%}".format(row.revenue_share),
        )
        for row in rows
    )

    return """
    <section class="panel">
      <h2>{title}</h2>
      <table>
        <thead>
          <tr>
            <th>Label</th>
            <th>Accounts</th>
            <th>Seats</th>
            <th>Revenue</th>
            <th>Avg Ticket</th>
            <th>Rev Share</th>
          </tr>
        </thead>
        <tbody>{body}</tbody>
      </table>
    </section>
    """.format(title=html.escape(title), body=body)


def render_quality_checks(summary: EventSummary) -> str:
    checks = [
        "Rows processed: {0}".format(summary.data_quality["rows_processed"]),
        "Required column coverage: {0}".format(summary.data_quality["required_column_coverage"]),
        "Revenue mismatches: {0}".format(summary.data_quality["revenue_mismatch_count"]),
        "Missing required values: {0}".format(summary.data_quality["missing_required_values"]),
    ]
    return "".join(
        '<li>{0}</li>'.format(html.escape(item))
        for item in checks
    )


def quality_check_items(summary: EventSummary) -> List[str]:
    return [
        "Rows processed: {0}".format(summary.data_quality["rows_processed"]),
        "Required column coverage: {0}".format(summary.data_quality["required_column_coverage"]),
        "Revenue mismatches: {0}".format(summary.data_quality["revenue_mismatch_count"]),
        "Missing required values: {0}".format(summary.data_quality["missing_required_values"]),
    ]


def executive_readout_items(summary: EventSummary) -> List[str]:
    return [
        "Locked revenue is {0} across {1} seats from {2} unique accounts.".format(
            money(summary.total_revenue),
            summary.total_seats,
            summary.unique_accounts,
        ),
        "Top plan type by revenue: {0}. Top section type by revenue: {1}.".format(
            summary.top_plan_type,
            summary.top_section_type,
        ),
        "Leading price level by revenue: {0}. Weighted average ticket price is {1}.".format(
            summary.top_price_level,
            money(summary.weighted_average_ticket_price),
        ),
        "Total full-season equivalence is {0:.2f}, and average package length is {1:.1f} events.".format(
            summary.total_full_season_equivalence,
            summary.weighted_average_events,
        ),
    ]


def render_email_html(summary: EventSummary, distribution: Optional[DistributionConfig] = None) -> str:
    generated_at = now_label()
    report_name = "Executive Event Truth Attachment"
    metrics = "".join(
        [
            render_metric("Accounts", str(summary.unique_accounts), "Unique accounts represented in the event file"),
            render_metric("Seats", str(summary.total_seats), "Seat total from the reconciled morning file"),
            render_metric("Revenue", money(summary.total_revenue), "Locked ticket revenue for the shared morning readout"),
            render_metric("Avg Ticket", money(summary.weighted_average_ticket_price), "Revenue divided by seats"),
            render_metric("Full Season Eq.", "{0:.2f}".format(summary.total_full_season_equivalence), "Plan volume converted into a common season-equivalent lens"),
            render_metric("Avg Package Length", "{0:.1f}".format(summary.weighted_average_events), "Average number of events weighted by seats"),
        ]
    )
    quality_checks = render_quality_checks(summary)
    readout_items = "".join(
        '<li>{0}</li>'.format(html.escape(item))
        for item in executive_readout_items(summary)
    )
    status_label = str(summary.data_quality["status"])

    return """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{report_name}</title>
  <style>
    @page {{
      size: Letter;
      margin: 0.55in;
    }}
    :root {{
      --bg: #ebe7de;
      --page: #fffdfa;
      --panel: #f8f3e7;
      --ink: #1d1a15;
      --muted: #655e52;
      --accent: #a88321;
      --accent-soft: #efe1b8;
      --line: #d8ccb2;
      --good: #2f6240;
      --shadow: 0 16px 36px rgba(29, 26, 21, 0.12);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Arial, Helvetica, sans-serif;
      color: var(--ink);
      background: linear-gradient(180deg, #f0ece4 0%, #e8e2d6 100%);
    }}
    .page {{
      width: min(980px, calc(100% - 24px));
      margin: 24px auto 36px;
      background: var(--page);
      border: 1px solid rgba(216, 204, 178, 0.92);
      border-radius: 24px;
      padding: 26px;
      box-shadow: var(--shadow);
    }}
    .hero {{
      border-top: 8px solid var(--accent);
      padding-top: 12px;
    }}
    .eyebrow {{
      text-transform: uppercase;
      letter-spacing: 0.16em;
      font-size: 11px;
      color: var(--muted);
      margin-bottom: 8px;
    }}
    h1 {{
      margin: 0 0 8px;
      font-family: Georgia, "Times New Roman", serif;
      font-size: clamp(32px, 5vw, 46px);
      line-height: 1.04;
    }}
    .hero-subhead {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      flex-wrap: wrap;
      margin-bottom: 16px;
    }}
    .hero-copy {{
      color: var(--muted);
      line-height: 1.6;
      max-width: 760px;
      margin: 0;
    }}
    .status-chip {{
      display: inline-flex;
      align-items: center;
      padding: 8px 12px;
      border-radius: 999px;
      background: #e7f1e9;
      color: var(--good);
      font-weight: 700;
      font-size: 13px;
    }}
    .meta-grid {{
      grid-template-columns: repeat(3, minmax(0, 1fr));
      display: grid;
      gap: 12px;
      margin-top: 18px;
    }}
    .meta-card {{
      background: var(--panel);
      border: 1px solid rgba(216, 204, 178, 0.92);
      border-radius: 18px;
      padding: 16px;
    }}
    .meta-label {{
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.12em;
      font-size: 11px;
      margin-bottom: 6px;
    }}
    .meta-value {{
      font-size: 15px;
      line-height: 1.5;
    }}
    .section {{
      margin-top: 18px;
    }}
    .metrics-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
    }}
    .metric-card {{
      position: relative;
      overflow: hidden;
      background: var(--panel);
      border: 1px solid rgba(216, 204, 178, 0.92);
      border-radius: 18px;
      padding: 18px;
    }}
    .metric-card::before {{
      content: "";
      position: absolute;
      left: 0;
      top: 0;
      width: 100%;
      height: 4px;
      background: linear-gradient(90deg, var(--accent), #d4bb70);
    }}
    .metric-label {{
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      color: var(--muted);
      margin-bottom: 10px;
    }}
    .metric-value {{
      font-size: 30px;
      font-weight: 700;
      margin-bottom: 6px;
    }}
    .metric-note {{
      color: var(--muted);
      line-height: 1.45;
      font-size: 14px;
    }}
    .content-grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 14px;
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid rgba(216, 204, 178, 0.92);
      border-radius: 18px;
      padding: 20px;
    }}
    .panel h2 {{
      margin: 0 0 12px;
      font-family: Georgia, "Times New Roman", serif;
      font-size: 28px;
    }}
    .panel-copy {{
      color: var(--muted);
      line-height: 1.55;
      margin: 0 0 14px;
    }}
    .bullet-list {{
      margin: 0;
      padding-left: 18px;
      line-height: 1.7;
      color: var(--muted);
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      min-width: 680px;
    }}
    th, td {{
      padding: 12px 10px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
    }}
    th {{
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      color: var(--muted);
    }}
    .table-wrap {{
      overflow-x: auto;
    }}
    .source-note {{
      margin-top: 16px;
      padding: 16px 18px;
      border-radius: 18px;
      background: linear-gradient(135deg, rgba(168, 131, 33, 0.16), rgba(168, 131, 33, 0.08));
      border: 1px solid rgba(168, 131, 33, 0.24);
      line-height: 1.6;
    }}
    @media (max-width: 900px) {{
      .meta-grid, .metrics-grid, .content-grid {{
        grid-template-columns: 1fr;
      }}
    }}
    @media (max-width: 640px) {{
      .page {{
        width: min(100% - 12px, 980px);
      }}
      .page, .panel, .metric-card, .meta-card {{
        border-radius: 18px;
        padding: 16px;
      }}
      .hero-subhead {{
        align-items: start;
      }}
    }}
    @media print {{
      body {{
        background: white;
      }}
      .page {{
        width: auto;
        margin: 0;
        box-shadow: none;
        border: none;
        border-radius: 0;
        padding: 0;
      }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <section class="hero">
        <div class="eyebrow">{report_name}</div>
        <h1>{event_name}</h1>
        <div class="hero-subhead">
          <p class="hero-copy">
            This attachment reflects the locked morning event file and should be treated as the source of truth for post-event ticket reporting.
          </p>
          <div class="status-chip">{status_label}</div>
        </div>
        <div class="meta-grid">
          <div class="meta-card">
            <div class="meta-label">Prepared</div>
            <div class="meta-value">{generated_at}</div>
          </div>
          <div class="meta-card">
            <div class="meta-label">Event Status</div>
            <div class="meta-value">{status_label}</div>
          </div>
          <div class="meta-card">
            <div class="meta-label">Data Scope</div>
            <div class="meta-value">Ticket plans, seat volume, package mix, price levels, and locked event revenue.</div>
          </div>
        </div>
    </section>

    <section class="section metrics-grid">
      {metrics}
    </section>

    <section class="section content-grid">
      <div class="panel">
        <h2>Executive Readout</h2>
        <p class="panel-copy">
          These are the most important locked takeaways from the event-level file.
        </p>
        <ul class="bullet-list">{readout_items}</ul>
      </div>
      <div class="panel">
        <h2>Source Of Truth Status</h2>
        <p class="panel-copy">
          These checks describe the integrity of the locked morning file behind the attachment.
        </p>
        <ul class="bullet-list">{quality_checks}</ul>
      </div>
    </section>

    <div class="section table-wrap">
      {plan_mix_table}
    </div>
    <div class="section table-wrap">
      {section_mix_table}
    </div>
    <div class="section table-wrap">
      {price_mix_table}
    </div>

    <section class="section">
      <div class="panel">
        <h2>Source Of Truth Statement</h2>
        <div class="source-note">
          This attachment is intended to be the single shared view of post-event ticket performance. If downstream views differ from this file,
          this attachment should be treated as the locked baseline while any variance is reconciled.
        </div>
      </div>
    </section>
  </div>
</body>
</html>
    """.format(
        report_name=html.escape(report_name),
        event_name=html.escape(summary.event_name),
        generated_at=html.escape(generated_at),
        status_label=html.escape(status_label),
        metrics=metrics,
        readout_items=readout_items,
        plan_mix_table=render_breakdown_table("Plan Mix", summary.plan_type_breakdown),
        section_mix_table=render_breakdown_table("Section Mix", summary.section_type_breakdown),
        price_mix_table=render_breakdown_table("Price Level Mix", summary.price_level_breakdown),
        quality_checks=quality_checks,
    )


def render_distribution_plan_html(distribution: DistributionConfig) -> str:
    audience_cards = render_distribution_cards(distribution.audiences)
    timeline_steps = render_schedule_timeline(distribution)
    return """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{report_name} Distribution Plan</title>
  <style>
    :root {{
      --bg: #101217;
      --panel: #f6f1e8;
      --panel-soft: #fffdfa;
      --ink: #18120b;
      --muted: #685f52;
      --accent: #c7a13a;
      --line: #d3c19a;
      --dark: #181b1f;
      --shadow: 0 24px 56px rgba(0, 0, 0, 0.28);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Arial, Helvetica, sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(199, 161, 58, 0.16), transparent 22%),
        linear-gradient(180deg, #111419 0%, #0a0c0f 100%);
    }}
    .page {{
      width: min(1080px, calc(100% - 24px));
      margin: 24px auto 38px;
    }}
    .hero {{
      display: grid;
      grid-template-columns: 1.05fr 0.95fr;
      gap: 18px;
      margin-bottom: 18px;
    }}
    .hero-main {{
      background: linear-gradient(145deg, rgba(33, 38, 44, 0.96), rgba(17, 19, 23, 0.98));
      color: white;
      border-radius: 30px;
      padding: 30px;
      border: 1px solid rgba(255, 255, 255, 0.08);
      box-shadow: var(--shadow);
    }}
    .hero-side {{
      background: var(--panel);
      border-radius: 30px;
      padding: 24px;
      border: 1px solid rgba(211, 193, 154, 0.84);
      box-shadow: var(--shadow);
    }}
    .eyebrow {{
      text-transform: uppercase;
      letter-spacing: 0.18em;
      font-size: 12px;
      color: rgba(255, 255, 255, 0.72);
      margin-bottom: 12px;
    }}
    h1 {{
      margin: 0 0 12px;
      font-family: Georgia, "Times New Roman", serif;
      font-size: clamp(34px, 5vw, 52px);
      line-height: 1.04;
    }}
    .hero-main p {{
      margin: 0;
      color: rgba(255, 255, 255, 0.82);
      line-height: 1.6;
    }}
    .side-label {{
      text-transform: uppercase;
      letter-spacing: 0.14em;
      font-size: 11px;
      color: var(--muted);
      margin-bottom: 10px;
    }}
    .side-title {{
      font-family: Georgia, "Times New Roman", serif;
      font-size: 28px;
      margin-bottom: 18px;
    }}
    .hero-side dl {{
      margin: 0;
      display: grid;
      gap: 14px;
    }}
    .hero-side div {{
      padding-top: 14px;
      border-top: 1px solid rgba(211, 193, 154, 0.8);
    }}
    dt {{
      text-transform: uppercase;
      letter-spacing: 0.12em;
      font-size: 11px;
      color: var(--muted);
      margin-bottom: 4px;
    }}
    dd {{
      margin: 0;
      line-height: 1.55;
    }}
    .panel {{
      background: var(--panel);
      border-radius: 28px;
      padding: 24px;
      border: 1px solid rgba(211, 193, 154, 0.84);
      box-shadow: 0 18px 34px rgba(0, 0, 0, 0.16);
      margin-bottom: 18px;
    }}
    .panel h2 {{
      margin: 0 0 14px;
      font-family: Georgia, "Times New Roman", serif;
      font-size: 29px;
    }}
    .panel-copy {{
      color: var(--muted);
      line-height: 1.55;
      margin: 0 0 14px;
    }}
    .timeline {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
    }}
    .timeline-step {{
      background: var(--panel-soft);
      border: 1px solid rgba(211, 193, 154, 0.84);
      border-radius: 18px;
      padding: 16px;
    }}
    .timeline-time {{
      font-size: 24px;
      font-weight: 700;
      margin-bottom: 6px;
    }}
    .timeline-label {{
      text-transform: uppercase;
      letter-spacing: 0.12em;
      font-size: 11px;
      color: var(--muted);
      margin-bottom: 8px;
    }}
    .timeline-note {{
      color: var(--muted);
      line-height: 1.5;
      font-size: 14px;
    }}
    .distribution-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 16px;
    }}
    .audience-card {{
      background: linear-gradient(180deg, #21262c, #181b1f);
      color: rgba(255, 255, 255, 0.92);
      border-radius: 22px;
      padding: 18px;
      border: 1px solid rgba(255, 255, 255, 0.08);
    }}
    .audience-head {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: start;
      margin-bottom: 14px;
    }}
    .audience-name {{
      font-family: Georgia, "Times New Roman", serif;
      font-size: 22px;
      font-weight: 700;
      margin-bottom: 4px;
    }}
    .audience-purpose {{
      color: rgba(255, 255, 255, 0.72);
      line-height: 1.5;
      font-size: 14px;
    }}
    .send-badge {{
      white-space: nowrap;
      background: rgba(199, 161, 58, 0.14);
      border: 1px solid rgba(199, 161, 58, 0.3);
      color: #f3d983;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.1em;
      padding: 8px 10px;
      border-radius: 999px;
      font-weight: 700;
    }}
    .distribution-list {{
      display: grid;
      gap: 10px;
      margin: 0;
    }}
    .distribution-list div {{
      display: grid;
      grid-template-columns: 96px 1fr;
      gap: 10px;
    }}
    .distribution-list dt {{
      color: rgba(255, 255, 255, 0.5);
      text-transform: uppercase;
      letter-spacing: 0.1em;
      font-size: 11px;
      font-weight: 700;
    }}
    .distribution-list dd {{
      margin: 0;
      line-height: 1.55;
    }}
    ul {{
      margin: 0;
      padding-left: 18px;
      color: var(--muted);
      line-height: 1.7;
    }}
    @media (max-width: 980px) {{
      .hero, .timeline, .distribution-grid {{
        grid-template-columns: 1fr;
      }}
    }}
    @media (max-width: 640px) {{
      .page {{
        width: min(100% - 12px, 1080px);
      }}
      .hero-main, .hero-side, .panel, .audience-card {{
        border-radius: 20px;
        padding: 16px;
      }}
      .distribution-list div {{
        grid-template-columns: 1fr;
        gap: 4px;
      }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <section class="hero">
      <div class="hero-main">
        <div class="eyebrow">Distribution Governance</div>
        <h1>{report_name}</h1>
        <p>{demo_note}</p>
      </div>
      <aside class="hero-side">
        <div class="side-label">Control Summary</div>
        <div class="side-title">Release Ownership</div>
        <dl>
          <div>
            <dt>Sender</dt>
            <dd>{sender_name} &lt;{sender_email}&gt;</dd>
          </div>
          <div>
            <dt>Reply-To</dt>
            <dd>{reply_to}</dd>
          </div>
          <div>
            <dt>Owner</dt>
            <dd>{distribution_owner}</dd>
          </div>
        </dl>
      </aside>
    </section>

    <section class="panel">
      <h2>Morning Control Sequence</h2>
      <p class="panel-copy">
        This is the governance story to show the Bruins: refresh the event file, lock the numbers, send the executive digest,
        and then follow with the more detailed operational version.
      </p>
      <div class="timeline">{timeline_steps}</div>
    </section>

    <section class="panel">
      <h2>Audience Map</h2>
      <p class="panel-copy">
        Recipients, timing, and release rules live outside the code so the business can own them directly.
      </p>
      <div class="distribution-grid">{audience_cards}</div>
    </section>

    <section class="panel">
      <h2>How To Present This To The Bruins</h2>
      <ul>
        <li>Lead with the release sequence so they see the operating rhythm before the email itself.</li>
        <li>Show that recipients and send times are governed in configuration rather than hard-coded in the automation.</li>
        <li>Explain that the same locked event record feeds every audience, which removes morning number debates.</li>
      </ul>
    </section>
  </div>
</body>
</html>
    """.format(
        report_name=html.escape(distribution.report_name),
        demo_note=html.escape(distribution.demo_note),
        sender_name=html.escape(distribution.sender_name),
        sender_email=html.escape(distribution.sender_email),
        reply_to=html.escape(distribution.reply_to),
        distribution_owner=html.escape(distribution.distribution_owner),
        audience_cards=audience_cards,
        timeline_steps=timeline_steps,
    )


def ensure_pdf_space(pdf: object, height: float) -> None:
    if pdf.get_y() + height > pdf.h - pdf.b_margin:
        pdf.add_page()


def draw_pdf_metric_card(
    pdf: object,
    x: float,
    y: float,
    width: float,
    height: float,
    label: str,
    value: str,
    note: str,
) -> None:
    pdf.set_fill_color(248, 243, 231)
    pdf.set_draw_color(216, 204, 178)
    pdf.rect(x, y, width, height, style="DF")

    pdf.set_fill_color(168, 131, 33)
    pdf.rect(x, y, width, 3, style="F")

    pdf.set_xy(x + 4, y + 6)
    pdf.set_text_color(101, 94, 82)
    pdf.set_font("Helvetica", "B", 8)
    pdf.multi_cell(width - 8, 4, label.upper())

    pdf.set_x(x + 4)
    pdf.set_text_color(29, 26, 21)
    pdf.set_font("Helvetica", "B", 16)
    pdf.multi_cell(width - 8, 6, value)

    pdf.set_x(x + 4)
    pdf.set_text_color(101, 94, 82)
    pdf.set_font("Helvetica", "", 8)
    pdf.multi_cell(width - 8, 4, note)


def draw_pdf_bullet_panel(pdf: object, title: str, intro: str, items: Sequence[str]) -> None:
    ensure_pdf_space(pdf, 40 + (len(items) * 7))
    page_width = pdf.w - pdf.l_margin - pdf.r_margin

    pdf.set_fill_color(248, 243, 231)
    pdf.set_draw_color(216, 204, 178)
    panel_top = pdf.get_y()
    estimated_height = 22 + (len(items) * 8)
    pdf.rect(pdf.l_margin, panel_top, page_width, estimated_height, style="DF")

    pdf.set_xy(pdf.l_margin + 6, panel_top + 6)
    pdf.set_text_color(29, 26, 21)
    pdf.set_font("Times", "B", 18)
    pdf.cell(0, 7, title, new_x="LMARGIN", new_y="NEXT")

    pdf.set_x(pdf.l_margin + 6)
    pdf.set_text_color(101, 94, 82)
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(page_width - 12, 5, intro)
    pdf.ln(1)

    pdf.set_font("Helvetica", "", 10)
    for item in items:
        pdf.set_x(pdf.l_margin + 8)
        pdf.set_text_color(29, 26, 21)
        pdf.cell(4, 5, "-", new_x="RIGHT", new_y="TOP")
        pdf.set_text_color(101, 94, 82)
        pdf.multi_cell(page_width - 18, 5, item)

    pdf.set_y(panel_top + estimated_height + 6)


def draw_pdf_breakdown_table(pdf: object, title: str, rows: Sequence[BreakdownRow]) -> None:
    column_widths = [50, 18, 18, 34, 26, 22]
    headers = ["Label", "Accts", "Seats", "Revenue", "Avg Tix", "Share"]
    row_height = 7
    required_height = 16 + row_height * (len(rows) + 1)
    ensure_pdf_space(pdf, required_height)

    pdf.set_text_color(29, 26, 21)
    pdf.set_font("Times", "B", 18)
    pdf.cell(0, 9, title, new_x="LMARGIN", new_y="NEXT")

    pdf.set_fill_color(168, 131, 33)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 9)
    for width, header in zip(column_widths, headers):
        pdf.cell(width, row_height, header, border=1, align="C", fill=True)
    pdf.ln(row_height)

    pdf.set_font("Helvetica", "", 9)
    for row in rows:
        ensure_pdf_space(pdf, row_height + 2)
        pdf.set_fill_color(255, 253, 250)
        pdf.set_text_color(29, 26, 21)
        values = [
            row.label,
            str(row.accounts),
            str(row.seats),
            money(row.revenue),
            money(row.average_ticket_price),
            "{0:.1%}".format(row.revenue_share),
        ]
        aligns = ["L", "C", "C", "R", "R", "R"]
        for width, value, align in zip(column_widths, values, aligns):
            pdf.cell(width, row_height, value, border=1, align=align, fill=True)
        pdf.ln(row_height)

    pdf.ln(6)


def write_executive_attachment_pdf(summary: EventSummary, pdf_path: Path) -> None:
    try:
        from fpdf import FPDF
    except ImportError as exc:
        raise RuntimeError(
            "fpdf2 is required to generate executive PDF attachments. Install dependencies with `pip install -e .`."
        ) from exc

    class ExecutiveAttachmentPDF(FPDF):
        def footer(self) -> None:
            self.set_y(-10)
            self.set_text_color(120, 112, 98)
            self.set_font("Helvetica", "", 8)
            page_width = self.w - self.l_margin - self.r_margin
            self.set_x(self.l_margin)
            self.cell(page_width / 2, 5, "Executive Event Truth Attachment", new_x="RIGHT", new_y="TOP")
            self.cell(page_width / 2, 5, "Page {0}".format(self.page_no()), align="R")

    pdf = ExecutiveAttachmentPDF(orientation="P", unit="mm", format="Letter")
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.set_margins(15, 15, 15)
    pdf.add_page()

    page_width = pdf.w - pdf.l_margin - pdf.r_margin

    pdf.set_fill_color(29, 26, 21)
    pdf.rect(pdf.l_margin, pdf.get_y(), page_width, 36, style="F")
    pdf.set_xy(pdf.l_margin + 6, 20)
    pdf.set_text_color(239, 225, 184)
    pdf.set_font("Helvetica", "B", 8)
    pdf.cell(0, 4, "EXECUTIVE EVENT TRUTH ATTACHMENT", new_x="LMARGIN", new_y="NEXT")

    pdf.set_x(pdf.l_margin + 6)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Times", "B", 22)
    pdf.multi_cell(page_width - 12, 8, summary.event_name)

    pdf.set_x(pdf.l_margin + 6)
    pdf.set_text_color(216, 204, 178)
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(
        page_width - 12,
        5,
        "Prepared {0} | Status: {1}".format(now_label(), summary.data_quality["status"]),
    )
    pdf.ln(2)

    metric_cards = [
        ("Accounts", str(summary.unique_accounts), "Unique accounts represented in the event file"),
        ("Seats", str(summary.total_seats), "Seat total from the reconciled morning file"),
        ("Revenue", money(summary.total_revenue), "Locked ticket revenue for the shared morning readout"),
        ("Avg Ticket", money(summary.weighted_average_ticket_price), "Revenue divided by seats"),
        ("Full Season Eq.", "{0:.2f}".format(summary.total_full_season_equivalence), "Plan volume normalized into a season-equivalent view"),
        ("Avg Package Length", "{0:.1f}".format(summary.weighted_average_events), "Average number of events weighted by seats"),
    ]
    card_gap = 4
    card_width = (page_width - (card_gap * 2)) / 3
    card_height = 34
    cards_top = pdf.get_y() + 4
    for index, card in enumerate(metric_cards):
        row = index // 3
        column = index % 3
        card_x = pdf.l_margin + (column * (card_width + card_gap))
        card_y = cards_top + (row * (card_height + 5))
        draw_pdf_metric_card(pdf, card_x, card_y, card_width, card_height, card[0], card[1], card[2])
    pdf.set_y(cards_top + (2 * (card_height + 5)) + 2)

    draw_pdf_bullet_panel(
        pdf,
        "Executive Readout",
        "These are the most important locked takeaways from the event-level file.",
        executive_readout_items(summary),
    )
    draw_pdf_bullet_panel(
        pdf,
        "Source Of Truth Status",
        "These checks describe the integrity of the locked morning file behind the attachment.",
        quality_check_items(summary),
    )

    draw_pdf_breakdown_table(pdf, "Plan Mix", summary.plan_type_breakdown)
    draw_pdf_breakdown_table(pdf, "Section Mix", summary.section_type_breakdown)
    draw_pdf_breakdown_table(pdf, "Price Level Mix", summary.price_level_breakdown)

    ensure_pdf_space(pdf, 24)
    pdf.set_fill_color(239, 225, 184)
    pdf.set_draw_color(216, 204, 178)
    note_top = pdf.get_y()
    pdf.rect(pdf.l_margin, note_top, page_width, 18, style="DF")
    pdf.set_xy(pdf.l_margin + 5, note_top + 4)
    pdf.set_text_color(29, 26, 21)
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(
        page_width - 10,
        5,
        "This attachment should be treated as the locked source of truth for post-event ticket reporting while any downstream variance is reconciled.",
    )

    pdf.output(str(pdf_path))


def write_event_outputs(
    summary: EventSummary,
    output_dir: Path,
    distribution: Optional[DistributionConfig] = None,
) -> Dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    slug = slugify(summary.event_name)
    json_path = output_dir / "{0}_golden_record.json".format(slug)
    html_path = output_dir / "{0}_executive_attachment.html".format(slug)
    pdf_path = output_dir / "{0}_executive_attachment.pdf".format(slug)

    json_path.write_text(json.dumps(summary_to_payload(summary, distribution), indent=2), encoding="utf-8")
    html_path.write_text(render_email_html(summary, distribution), encoding="utf-8")
    write_executive_attachment_pdf(summary, pdf_path)

    return {"json": json_path, "html": html_path, "pdf": pdf_path}


def render_index_page(index_rows: Sequence[Dict[str, str]]) -> str:
    links = "".join(
        """
        <tr>
          <td>{event_name}</td>
          <td><a href="{html_name}">Executive HTML</a></td>
          <td><a href="{pdf_name}">Executive PDF</a></td>
          <td><a href="{json_name}">Golden Record JSON</a></td>
        </tr>
        """.format(
            event_name=html.escape(row["event_name"]),
            html_name=html.escape(row["html_name"]),
            pdf_name=html.escape(row["pdf_name"]),
            json_name=html.escape(row["json_name"]),
        )
        for row in index_rows
    )

    return """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Executive Event Truth Outputs</title>
  <style>
    body {{ font-family: Arial, Helvetica, sans-serif; margin: 24px; color: #18212b; background: #f7f9fb; }}
    .panel {{ max-width: 900px; margin: 0 auto; background: white; border: 1px solid #d6dee6; border-radius: 18px; padding: 24px; }}
    h1 {{ margin-top: 0; }}
    p {{ color: #617182; line-height: 1.55; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ padding: 12px; border-bottom: 1px solid #d6dee6; text-align: left; }}
    th {{ text-transform: uppercase; letter-spacing: 0.12em; font-size: 12px; color: #617182; }}
  </style>
</head>
<body>
  <div class="panel">
    <h1>Executive Event Truth Outputs</h1>
    <p>This index page links to the executive attachment preview, the executive PDF attachment, and the locked golden-record JSON for each sample event.</p>
    <table>
      <thead>
        <tr>
          <th>Event</th>
          <th>HTML</th>
          <th>PDF</th>
          <th>JSON</th>
        </tr>
      </thead>
      <tbody>{links}</tbody>
    </table>
  </div>
</body>
</html>
    """.format(links=links)


def write_index_page(index_rows: Sequence[Dict[str, str]], output_dir: Path) -> Path:
    index_path = output_dir / "index.html"
    index_path.write_text(render_index_page(index_rows), encoding="utf-8")
    return index_path


def write_distribution_plan(distribution: DistributionConfig, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    distribution_path = output_dir / "distribution_plan.html"
    distribution_path.write_text(render_distribution_plan_html(distribution), encoding="utf-8")
    return distribution_path
