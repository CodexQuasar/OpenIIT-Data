"""Load real dataset from CSV files."""

import csv
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from datetime import datetime


# Dataset path
DATASET_PATH = Path(__file__).parent.parent.parent / "Dataset"


@dataclass
class RealAccount:
    """Real account from dataset."""
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
    salary_credit_day: Optional[float]
    bureau_score_band: str
    other_active_loans: int
    paid_other_lenders_30d: bool
    last_bounce_reason: str
    ability_to_pay_estimate: Optional[float]
    prev_ptp_count: int
    prev_ptp_broken: int
    dialling_arm: str


@dataclass
class RealAddress:
    """Real address from dataset."""
    address_id: str
    account_id: str
    address_type: str
    source: str
    added_date: str
    town_id: str
    address_text: str


@dataclass
class RealFieldVisit:
    """Real field visit from dataset."""
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
    ptp_id: Optional[str]
    remark: Optional[str]
    photo_hash: Optional[str]


@dataclass
class RealVisitGPSPoint:
    """Real visit GPS point from dataset."""
    visit_id: str
    seq: int
    point_ts: str
    x: float
    y: float
    accuracy_m: float


@dataclass
class RealBaselineGeocode:
    """Real baseline geocode from dataset."""
    address_id: str
    geocoder_x: float
    geocoder_y: float
    precision: str


@dataclass
class RealLandmark:
    """Real landmark/POI from dataset."""
    poi_id: str
    town_id: str
    landmark_type: str
    name: str
    x: float
    y: float


@dataclass
class RealSurveyedAddress:
    """Real surveyed address (ground truth) from dataset."""
    address_id: str
    surveyed_x: float
    surveyed_y: float


@dataclass
class RealLocality:
    """Real locality from dataset."""
    locality_id: str
    town_id: str
    locality_name: str
    pincode: str
    centroid_x: float
    centroid_y: float


@dataclass
class RealTown:
    """Real town from dataset."""
    town_id: str
    town_name: str
    address_style: str
    approx_radius_m: float


@dataclass
class RealAgent:
    """Real agent from dataset."""
    agent_id: str
    channel: str
    language_team: str
    town_id: Optional[str]
    tenure_months: float
    shift: str


class RealDatasetLoader:
    """Loads real dataset from CSV files."""

    def __init__(self, dataset_path: Path = None):
        self.dataset_path = dataset_path or DATASET_PATH
        self.accounts: dict[str, RealAccount] = {}
        self.addresses: dict[str, RealAddress] = {}
        self.field_visits: dict[str, RealFieldVisit] = {}
        self.visit_gps_points: dict[str, list[RealVisitGPSPoint]] = {}
        self.baseline_geocodes: dict[str, RealBaselineGeocode] = {}
        self.landmarks: dict[str, RealLandmark] = {}
        self.surveyed_addresses: dict[str, RealSurveyedAddress] = {}
        self.localities: dict[str, RealLocality] = {}
        self.towns: dict[str, RealTown] = {}
        self.agents: dict[str, RealAgent] = {}

    def load_all(self, split: str = "train"):
        """Load all dataset files."""
        self.load_towns(split)
        self.load_localities(split)
        self.load_landmarks(split)
        self.load_accounts(split)
        self.load_addresses(split)
        self.load_field_visits(split)
        self.load_visit_gps_points(split)
        self.load_baseline_geocodes(split)
        self.load_surveyed_addresses(split)
        self.load_agents(split)
        print(f"Loaded {len(self.accounts)} accounts, {len(self.addresses)} addresses, "
              f"{len(self.field_visits)} field visits, {len(self.landmarks)} landmarks, "
              f"{len(self.surveyed_addresses)} surveyed addresses")

    def load_towns(self, split: str = "train"):
        """Load towns."""
        path = self.dataset_path / "PS_3" / "towns" / f"towns_{split}.csv"
        if not path.exists():
            return
        with open(path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                town = RealTown(
                    town_id=row['town_id'],
                    town_name=row['town_name'],
                    address_style=row['address_style'],
                    approx_radius_m=float(row['approx_radius_m']),
                )
                self.towns[town.town_id] = town

    def load_localities(self, split: str = "train"):
        """Load localities."""
        path = self.dataset_path / "PS_3" / "localities" / f"localities_{split}.csv"
        if not path.exists():
            return
        with open(path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                locality = RealLocality(
                    locality_id=row['locality_id'],
                    town_id=row['town_id'],
                    locality_name=row['locality_name'],
                    pincode=row['pincode'],
                    centroid_x=float(row['centroid_x']),
                    centroid_y=float(row['centroid_y']),
                )
                self.localities[locality.locality_id] = locality

    def load_landmarks(self, split: str = "train"):
        """Load landmarks/POI."""
        path = self.dataset_path / "PS_3" / "landmarks_poi" / f"landmarks_poi_{split}.csv"
        if not path.exists():
            return
        with open(path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                landmark = RealLandmark(
                    poi_id=row['poi_id'],
                    town_id=row['town_id'],
                    landmark_type=row['landmark_type'],
                    name=row['name'],
                    x=float(row['x']),
                    y=float(row['y']),
                )
                self.landmarks[landmark.poi_id] = landmark

    def load_accounts(self, split: str = "train"):
        """Load accounts."""
        path = self.dataset_path / "Shared" / "accounts" / f"accounts_{split}.csv"
        if not path.exists():
            return
        with open(path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                account = RealAccount(
                    account_id=row['account_id'],
                    lender_id=row['lender_id'],
                    portfolio=row['portfolio'],
                    income_type=row['income_type'],
                    town_id=row['town_id'],
                    preferred_language=row['preferred_language'],
                    bucket_start=row['bucket_start'],
                    dpd_start=int(row['dpd_start']),
                    emi_amount=float(row['emi_amount']),
                    overdue_start=float(row['overdue_start']),
                    outstanding=float(row['outstanding']),
                    salary_credit_day=float(row['salary_credit_day']) if row['salary_credit_day'] else None,
                    bureau_score_band=row['bureau_score_band'],
                    other_active_loans=int(row['other_active_loans']),
                    paid_other_lenders_30d=row['paid_other_lenders_30d'] == 'True',
                    last_bounce_reason=row['last_bounce_reason'],
                    ability_to_pay_estimate=float(row['ability_to_pay_estimate']) if row['ability_to_pay_estimate'] else None,
                    prev_ptp_count=int(row['prev_ptp_count']),
                    prev_ptp_broken=int(row['prev_ptp_broken']),
                    dialling_arm=row['dialling_arm'],
                )
                self.accounts[account.account_id] = account

    def load_addresses(self, split: str = "train"):
        """Load addresses."""
        path = self.dataset_path / "Shared" / "addresses" / f"addresses_{split}.csv"
        if not path.exists():
            return
        with open(path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                address = RealAddress(
                    address_id=row['address_id'],
                    account_id=row['account_id'],
                    address_type=row['address_type'],
                    source=row['source'],
                    added_date=row['added_date'],
                    town_id=row['town_id'],
                    address_text=row['address_text'],
                )
                self.addresses[address.address_id] = address

    def load_field_visits(self, split: str = "train"):
        """Load field visits."""
        path = self.dataset_path / "Shared" / "field_visits" / f"field_visits_{split}.csv"
        if not path.exists():
            return
        with open(path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                visit = RealFieldVisit(
                    visit_id=row['visit_id'],
                    account_id=row['account_id'],
                    address_id=row['address_id'],
                    agent_id=row['agent_id'],
                    visit_date=row['visit_date'],
                    start_ts=row['start_ts'],
                    checkin_ts=row['checkin_ts'],
                    checkin_x=float(row['checkin_x']),
                    checkin_y=float(row['checkin_y']),
                    gps_accuracy_m=float(row['gps_accuracy_m']),
                    dwell_s=int(row['dwell_s']),
                    outcome=row['outcome'],
                    ptp_id=row['ptp_id'] if row['ptp_id'] else None,
                    remark=row['remark'] if row['remark'] else None,
                    photo_hash=row['photo_hash'] if row['photo_hash'] else None,
                )
                self.field_visits[visit.visit_id] = visit

    def load_visit_gps_points(self, split: str = "train"):
        """Load visit GPS points."""
        path = self.dataset_path / "PS_3" / "visit_gps_points" / f"visit_gps_points_{split}.csv"
        if not path.exists():
            return
        with open(path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                point = RealVisitGPSPoint(
                    visit_id=row['visit_id'],
                    seq=int(row['seq']),
                    point_ts=row['point_ts'],
                    x=float(row['x']),
                    y=float(row['y']),
                    accuracy_m=float(row['accuracy_m']),
                )
                if point.visit_id not in self.visit_gps_points:
                    self.visit_gps_points[point.visit_id] = []
                self.visit_gps_points[point.visit_id].append(point)

    def load_baseline_geocodes(self, split: str = "train"):
        """Load baseline geocodes."""
        path = self.dataset_path / "PS_3" / "baseline_geocodes" / f"baseline_geocodes_{split}.csv"
        if not path.exists():
            return
        with open(path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                geocode = RealBaselineGeocode(
                    address_id=row['address_id'],
                    geocoder_x=float(row['geocoder_x']),
                    geocoder_y=float(row['geocoder_y']),
                    precision=row['precision'],
                )
                self.baseline_geocodes[geocode.address_id] = geocode

    def load_surveyed_addresses(self, split: str = "train"):
        """Load surveyed addresses (ground truth)."""
        path = self.dataset_path / "PS_3" / "surveyed_addresses" / f"surveyed_addresses_{split}.csv"
        if not path.exists():
            return
        with open(path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                surveyed = RealSurveyedAddress(
                    address_id=row['address_id'],
                    surveyed_x=float(row['surveyed_x']),
                    surveyed_y=float(row['surveyed_y']),
                )
                self.surveyed_addresses[surveyed.address_id] = surveyed

    def load_agents(self, split: str = "train"):
        """Load agents."""
        path = self.dataset_path / "Shared" / "agents" / f"agents_{split}.csv"
        if not path.exists():
            return
        with open(path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                agent = RealAgent(
                    agent_id=row['agent_id'],
                    channel=row['channel'],
                    language_team=row['language_team'],
                    town_id=row['town_id'] if row['town_id'] else None,
                    tenure_months=float(row['tenure_months']) if row['tenure_months'] else 0.0,
                    shift=row['shift'],
                )
                self.agents[agent.agent_id] = agent

    def get_addresses_for_account(self, account_id: str) -> list[RealAddress]:
        """Get all addresses for an account."""
        return [a for a in self.addresses.values() if a.account_id == account_id]

    def get_visits_for_account(self, account_id: str) -> list[RealFieldVisit]:
        """Get all field visits for an account."""
        return [v for v in self.field_visits.values() if v.account_id == account_id]

    def get_visits_for_address(self, address_id: str) -> list[RealFieldVisit]:
        """Get all field visits for an address."""
        return [v for v in self.field_visits.values() if v.address_id == address_id]

    def get_landmarks_for_town(self, town_id: str) -> list[RealLandmark]:
        """Get all landmarks in a town."""
        return [l for l in self.landmarks.values() if l.town_id == town_id]

    def get_localities_for_town(self, town_id: str) -> list[RealLocality]:
        """Get all localities in a town."""
        return [l for l in self.localities.values() if l.town_id == town_id]

    def euclidean_distance(self, x1: float, y1: float, x2: float, y2: float) -> float:
        """Calculate Euclidean distance in meters."""
        return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)


# Singleton instance
_loader: Optional[RealDatasetLoader] = None


def get_dataset_loader() -> RealDatasetLoader:
    """Get singleton dataset loader."""
    global _loader
    if _loader is None:
        _loader = RealDatasetLoader()
    return _loader


def load_dataset(split: str = "train") -> RealDatasetLoader:
    """Load dataset and return loader."""
    loader = get_dataset_loader()
    loader.load_all(split)
    return loader