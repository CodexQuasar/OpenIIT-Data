"""Updated data models for real dataset with local coordinate system."""

from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime


@dataclass
class AccountData:
    """Account data from real dataset."""
    account_id: str
    lender_id: str
    portfolio: str
    income_type: str
    town_id: str
    preferred_language: str
    bucket_start: str
    dpd_start: int
    emi_amount: float
    overdue_start: float
    outstanding: float
    salary_credit_day: Optional[float] = None
    bureau_score_band: str = ""
    other_active_loans: int = 0
    paid_other_lenders_30d: bool = False
    last_bounce_reason: str = ""
    ability_to_pay_estimate: Optional[float] = None
    prev_ptp_count: int = 0
    prev_ptp_broken: int = 0
    dialling_arm: str = ""


@dataclass
class AddressData:
    """Address data from real dataset."""
    address_id: str
    account_id: str
    address_type: str
    source: str
    added_date: str
    town_id: str
    address_text: str


@dataclass
class FieldVisitData:
    """Field visit data from real dataset."""
    visit_id: str
    account_id: str
    address_id: str
    agent_id: str
    visit_date: str
    start_ts: str
    checkin_ts: str
    checkin_x: float
    checkin_y: float
    gps_accuracy_m: float
    dwell_s: int
    outcome: str
    ptp_id: Optional[str] = None
    remark: Optional[str] = None
    photo_hash: Optional[str] = None


@dataclass
class VisitGPSPoint:
    """Visit GPS point from real dataset."""
    visit_id: str
    seq: int
    point_ts: str
    x: float
    y: float
    accuracy_m: float


@dataclass
class BaselineGeocode:
    """Baseline geocode from real dataset."""
    address_id: str
    geocoder_x: float
    geocoder_y: float
    precision: str


@dataclass
class LandmarkData:
    """Landmark/POI data from real dataset."""
    poi_id: str
    town_id: str
    landmark_type: str
    name: str
    x: float
    y: float


@dataclass
class SurveyedAddress:
    """Surveyed address (ground truth) from real dataset."""
    address_id: str
    surveyed_x: float
    surveyed_y: float


@dataclass
class LocalityData:
    """Locality data from real dataset."""
    locality_id: str
    town_id: str
    locality_name: str
    pincode: str
    centroid_x: float
    centroid_y: float


@dataclass
class TownData:
    """Town data from real dataset."""
    town_id: str
    town_name: str
    address_style: str
    approx_radius_m: float


@dataclass
class AgentData:
    """Agent data from real dataset."""
    agent_id: str
    channel: str
    language_team: str
    town_id: Optional[str]
    tenure_months: float
    shift: str


# Outcome mapping from real dataset to our format
OUTCOME_MAPPING = {
    "address_not_traceable": "ADDRESS_NOT_TRACEABLE",
    "locked_premises": "FAILED_SEARCH",
    "met_family": "PARTIAL_CONTACT",
    "met_borrower": "SUCCESSFUL_CONTACT",
    "wrong_address": "WRONG_ADDRESS",
    "borrower_moved": "BORROWER_MOVED",
    "other": "OTHER",
}


def map_outcome(outcome: str) -> str:
    """Map real dataset outcome to our format."""
    return OUTCOME_MAPPING.get(outcome, "OTHER")