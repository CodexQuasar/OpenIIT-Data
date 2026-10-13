"""Tests for the gazetteer address parser and the evidence-fusion geocoder."""
import math
import os

os.environ["TESTING"] = "1"

import pytest

from data.real_data import RealDatasetLoader
from geospatial.real_geocoder import RealDataGeocoder
from ml.evidence_geocoder import EvidenceGeocoder
from ml.gazetteer_parser import parse_address

LOCALITIES = [("L1", "Kuvempu Layout"), ("L2", "Nehru Colony"), ("L3", "Green Park Layout")]


class TestGazetteerParser:
    def test_cross_main_and_abbreviated_locality(self):
        parsed = parse_address("No. 328, 4th Cross, 3rd Main Rd, Kuvempu Layt, Kaveripura - 960102", LOCALITIES, "Kaveripura")
        assert parsed.locality_id == "L1"
        assert (parsed.s1, parsed.s2) == (4.0, 3.0)
        assert parsed.pincode == "960102"
        assert parsed.landmark_type is None

    def test_native_script_landmark(self):
        parsed = parse_address("6th Cross, 5th Main, ಚರ್ಚ್ ಹತ್ತಿರ, Kuvempu Layt, Kaveripura - 960102", LOCALITIES, "Kaveripura")
        assert parsed.landmark_type == "church"
        assert parsed.relation == "near"

    def test_romanised_landmark_and_relation(self):
        parsed = parse_address("3rd cross 3rd main bhd hanuman temple kuvempu layout kaveripura", LOCALITIES, "Kaveripura")
        assert parsed.landmark_type == "hanuman_temple"
        assert parsed.relation == "behind"

    def test_block_and_road(self):
        parsed = parse_address("367/3 e block 2nd road green park layt navanagara east - 980301", LOCALITIES, "Navanagara East")
        assert parsed.locality_id == "L3"
        assert (parsed.s1, parsed.s2) == (2.0, 5.0)
        # "park" belongs to the locality name, not to a landmark
        assert parsed.landmark_type is None

    def test_gali_number_is_not_taken_from_house_number(self):
        parsed = parse_address("NO. 393, GALI NO-, DOODH DAIRY KE PAAS, NEHRU COLONY", LOCALITIES, "Devgarh Nagar")
        assert parsed.s1 is None
        assert parsed.landmark_type == "milk_dairy"

    def test_unknown_locality(self):
        parsed = parse_address("4TH CROSS, 2ND MN, KAVERIPURA - 960102", LOCALITIES, "Kaveripura")
        assert parsed.locality_id is None
        assert (parsed.s1, parsed.s2) == (4.0, 2.0)


@pytest.fixture(scope="module")
def loader():
    loader = RealDatasetLoader()
    loader.load_all("train")
    return loader


@pytest.fixture(scope="module")
def geocoder(loader):
    return EvidenceGeocoder(loader)


def _median(values):
    values = sorted(values)
    return values[len(values) // 2]


class TestEvidenceGeocoder:
    def test_beats_commercial_geocoder_on_surveyed_addresses(self, loader, geocoder):
        errors, baseline = [], []
        for address_id, surveyed in loader.surveyed_addresses.items():
            estimate = geocoder.predict(address_id)
            assert estimate is not None
            errors.append(math.hypot(estimate.x - surveyed.surveyed_x, estimate.y - surveyed.surveyed_y))
            geocode = loader.baseline_geocodes.get(address_id)
            if geocode:
                baseline.append(math.hypot(geocode.geocoder_x - surveyed.surveyed_x, geocode.geocoder_y - surveyed.surveyed_y))
        assert _median(errors) < 200
        assert _median(errors) < 0.5 * _median(baseline)
        assert sum(e <= 250 for e in errors) / len(errors) > 0.7

    def test_text_alone_beats_commercial_geocoder(self, loader, geocoder):
        """Addresses are located from their text when their own visits are withheld."""
        errors, baseline = [], []
        for address_id, surveyed in loader.surveyed_addresses.items():
            address = loader.addresses[address_id]
            geocode = loader.baseline_geocodes.get(address_id)
            estimate = geocoder.predict_for(
                address.address_text, address.town_id, geocode, (),
                exclude=geocoder._labels_by_account.get(address.account_id, frozenset()), use_visits=False)
            if estimate is None or geocode is None:
                continue
            errors.append(math.hypot(estimate.x - surveyed.surveyed_x, estimate.y - surveyed.surveyed_y))
            baseline.append(math.hypot(geocode.geocoder_x - surveyed.surveyed_x, geocode.geocoder_y - surveyed.surveyed_y))
        assert _median(errors) < _median(baseline)

    def test_confidence_and_radius_are_usable(self, loader, geocoder):
        estimates = [(geocoder.predict(a), s) for a, s in loader.surveyed_addresses.items()]
        covered = sum(math.hypot(e.x - s.surveyed_x, e.y - s.surveyed_y) <= e.radius_m for e, s in estimates)
        assert all(0.0 <= e.confidence <= 1.0 and e.radius_m > 0 for e, _ in estimates)
        assert 0.65 <= covered / len(estimates) <= 0.95
        # Confidence separates good from bad predictions
        confident = [math.hypot(e.x - s.surveyed_x, e.y - s.surveyed_y) for e, s in estimates if e.confidence >= 0.85]
        doubtful = [math.hypot(e.x - s.surveyed_x, e.y - s.surveyed_y) for e, s in estimates if e.confidence < 0.5]
        assert confident and doubtful
        assert _median(confident) < _median(doubtful)

    def test_unknown_address(self, geocoder):
        assert geocoder.predict("does-not-exist") is None

    def test_real_data_geocoder_uses_evidence(self, loader):
        results = RealDataGeocoder(loader).evaluate_on_surveyed()
        assert results["total_evaluated"] == len(loader.surveyed_addresses)
        assert results["median_error_m"] < results["baselines"]["commercial_geocoder"]["median_error_m"]
        result = RealDataGeocoder(loader).geocode_address(next(iter(loader.surveyed_addresses)))
        assert result.prediction_method in ("field_visits", "address_text")
        assert result.evidence["strongest_evidence"]
