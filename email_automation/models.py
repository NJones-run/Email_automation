from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import Dict
from typing import List


@dataclass(frozen=True)
class TicketPlanRow:
    acct_id: str
    price_level: str
    plan_event_name: str
    num_seats: int
    plan_type: str
    section_type: str
    number_of_events: int
    full_season_equivalence: float
    ticket_price: float
    revenue: float


@dataclass(frozen=True)
class BreakdownRow:
    label: str
    accounts: int
    seats: int
    revenue: float
    average_ticket_price: float
    revenue_share: float


@dataclass(frozen=True)
class DistributionAudience:
    name: str
    purpose: str
    to_recipients: List[str]
    cc_recipients: List[str]
    send_time_local: str
    timezone: str
    status_gate: str
    cadence: str


@dataclass(frozen=True)
class DistributionConfig:
    report_name: str
    sender_name: str
    sender_email: str
    reply_to: str
    distribution_owner: str
    latest_source_refresh: str
    final_lock_time: str
    demo_note: str
    audiences: List[DistributionAudience]


@dataclass
class EventSummary:
    event_name: str
    row_count: int
    unique_accounts: int
    total_seats: int
    total_revenue: float
    weighted_average_ticket_price: float
    total_full_season_equivalence: float
    weighted_average_events: float
    source_columns: List[str]
    data_quality: Dict[str, object]
    plan_type_breakdown: List[BreakdownRow] = field(default_factory=list)
    section_type_breakdown: List[BreakdownRow] = field(default_factory=list)
    price_level_breakdown: List[BreakdownRow] = field(default_factory=list)

    @property
    def top_plan_type(self) -> str:
        return self.plan_type_breakdown[0].label if self.plan_type_breakdown else "Not available"

    @property
    def top_section_type(self) -> str:
        return self.section_type_breakdown[0].label if self.section_type_breakdown else "Not available"

    @property
    def top_price_level(self) -> str:
        return self.price_level_breakdown[0].label if self.price_level_breakdown else "Not available"
