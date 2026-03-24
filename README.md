# Email Automation Demo

This repo is a small prototype for `golden record` event reporting and an `executive PDF attachment` that can be sent the morning after each event.

The point is not just to send a file. The point is to show how one reconciled event dataset can become the single source of truth for leadership the morning after every event.

## Input Dataset Shape

The demo uses the same core columns you shared:

- `acct_id`
- `price_level`
- `plan_event_name`
- `num_seats`
- `plan_type`
- `section_type`
- `number_of_events`
- `full_season_equivalence`
- `ticket_price`
- `revenue`

Sample data lives in [demo_ticket_plan_data.csv](/Users/nathanjones/Documents/Git/Email_automation/data/demo_ticket_plan_data.csv).

## What The Demo Produces

For each event in the CSV, the generator writes:

- a `golden record JSON` with topline metrics, breakdowns, and data-quality status
- an `executive attachment HTML` preview that leadership can read in a browser
- an `executive attachment PDF` that can be used as the actual morning attachment
- an `index.html` page that links to all generated outputs

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
python -m email_automation.cli build-demo
```

Outputs are written to `output/`.

## Commands

Build all sample event outputs:

```bash
python -m email_automation.cli build-demo
```

Build only one event:

```bash
python -m email_automation.cli build-demo --event-name "2026-03-19 | Bruins vs Rangers"
```

List the available sample events:

```bash
python -m email_automation.cli list-events
```

Print the configured send list and timing controls:

```bash
python -m email_automation.cli show-distribution
```

## Executive Attachment Story

This is the framing to use when walking through the output:

1. The business problem is inconsistent post-event numbers across departments.
2. The solution is one reconciled event-level dataset with shared definitions.
3. The automation layer turns that dataset into a clean executive attachment with locked morning numbers.
4. The value is faster decision-making, less manual reconciliation, and more trust in the numbers.

## What The Attachment Shows

The attachment is intentionally focused on pure content:

- event name and report status
- locked topline metrics
- executive readout bullets
- source-of-truth data quality checks
- plan mix, section mix, and price-level mix tables

## Demo Files

- [cli.py](/Users/nathanjones/Documents/Git/Email_automation/email_automation/cli.py)
- [reporting.py](/Users/nathanjones/Documents/Git/Email_automation/email_automation/reporting.py)
- [2026-03-19-bruins-vs-rangers_executive_attachment.html](/Users/nathanjones/Documents/Git/Email_automation/output/2026-03-19-bruins-vs-rangers_executive_attachment.html)
- [2026-03-19-bruins-vs-rangers_executive_attachment.pdf](/Users/nathanjones/Documents/Git/Email_automation/output/2026-03-19-bruins-vs-rangers_executive_attachment.pdf)
- [index.html](/Users/nathanjones/Documents/Git/Email_automation/output/index.html)
