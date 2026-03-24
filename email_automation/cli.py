from __future__ import annotations

import argparse
from pathlib import Path
from typing import List

from .reporting import group_rows_by_event
from .reporting import load_ticket_plan_rows
from .reporting import load_distribution_config
from .reporting import summarize_event
from .reporting import write_event_outputs
from .reporting import write_index_page


DEFAULT_DATA_PATH = "data/demo_ticket_plan_data.csv"
DEFAULT_OUTPUT_DIR = "output"
DEFAULT_DISTRIBUTION_CONFIG_PATH = "config/demo_distribution.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Golden-record executive attachment demo.")
    subparsers = parser.add_subparsers(dest="command")

    build_parser = subparsers.add_parser("build-demo", help="Build executive attachment outputs from the sample or supplied CSV file")
    build_parser.add_argument("--data-path", default=DEFAULT_DATA_PATH, help="CSV input path")
    build_parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="Directory for generated outputs")
    build_parser.add_argument("--event-name", help="Optional event name filter")
    build_parser.set_defaults(command="build-demo")

    list_parser = subparsers.add_parser("list-events", help="List available event names from the source CSV")
    list_parser.add_argument("--data-path", default=DEFAULT_DATA_PATH, help="CSV input path")
    list_parser.set_defaults(command="list-events")

    distribution_parser = subparsers.add_parser(
        "show-distribution",
        help="Print the configured audiences and schedule controls",
    )
    distribution_parser.add_argument(
        "--distribution-config",
        default=DEFAULT_DISTRIBUTION_CONFIG_PATH,
        help="JSON file describing recipients and send timing",
    )
    distribution_parser.set_defaults(command="show-distribution")

    return parser


def list_events(data_path: str) -> int:
    rows = load_ticket_plan_rows(Path(data_path))
    for event_name in sorted(group_rows_by_event(rows)):
        print(event_name)
    return 0


def show_distribution(distribution_config_path: str) -> int:
    distribution = load_distribution_config(Path(distribution_config_path))
    print("{0}".format(distribution.report_name))
    print("Sender: {0} <{1}>".format(distribution.sender_name, distribution.sender_email))
    print("Reply-To: {0}".format(distribution.reply_to))
    print("Owner: {0}".format(distribution.distribution_owner))
    print("Latest source refresh: {0}".format(distribution.latest_source_refresh))
    print("Final lock time: {0}".format(distribution.final_lock_time))
    for audience in distribution.audiences:
        print("")
        print("[{0}]".format(audience.name))
        print("Purpose: {0}".format(audience.purpose))
        print("To: {0}".format(", ".join(audience.to_recipients)))
        print("CC: {0}".format(", ".join(audience.cc_recipients)))
        print("Send: {0} {1}".format(audience.send_time_local, audience.timezone))
        print("Cadence: {0}".format(audience.cadence))
        print("Rule: {0}".format(audience.status_gate))
    return 0


def build_demo(
    data_path: str,
    output_dir: str,
    event_name: str = "",
) -> int:
    rows = load_ticket_plan_rows(Path(data_path))
    grouped = group_rows_by_event(rows)
    selected_event_names: List[str] = [event_name] if event_name else sorted(grouped)
    output_paths = []

    for current_event_name in selected_event_names:
        if current_event_name not in grouped:
            raise SystemExit("Event not found: {0}".format(current_event_name))
        summary = summarize_event(grouped[current_event_name])
        paths = write_event_outputs(summary, Path(output_dir))
        output_paths.append(
            {
                "event_name": current_event_name,
                "html_name": paths["html"].name,
                "pdf_name": paths["pdf"].name,
                "json_name": paths["json"].name,
            }
        )
        print("Built outputs for {0}".format(current_event_name))

    index_path = write_index_page(output_paths, Path(output_dir))
    print("Index written to {0}".format(index_path.resolve()))
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "list-events":
        return list_events(args.data_path)

    if args.command == "show-distribution":
        return show_distribution(args.distribution_config)

    if args.command == "build-demo":
        return build_demo(
            args.data_path,
            args.output_dir,
            args.event_name or "",
        )

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
