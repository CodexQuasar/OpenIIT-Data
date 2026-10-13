"""Evidence-fusion geocoder that learns from field visits.

Every address is located from two kinds of evidence:

* its own field visits - check-ins where the agent reached the premises;
* its text - locality, street structure and landmark, mapped to coordinates
  using the confirmed locations of *other* addresses (so the model keeps
  improving as visits accumulate), the landmark gazetteer and the commercial
  geocoder.

Each source carries an empirical error (sigma) measured by leave-one-account-out
validation, sources are fused by inverse variance, and the result comes with a
calibrated confidence and radius.
"""

import json
import logging
import math
import statistics
import threading
import weakref
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

import numpy as np

from ml.gazetteer_parser import LANDMARK_TYPES, ParsedAddress, parse_address

logger = logging.getLogger(__name__)

DEFAULT_PARAMS_PATH = Path(__file__).resolve().parents[1] / "models" / "evidence_geocoder.json"

SUCCESS_OUTCOMES = {"met_borrower", "met_family", "cash_collected"}
# Outcomes used as a confirmed location when an address has no successful visit
FALLBACK_LABEL_OUTCOMES = {"neighbour_says_shifted"}
# Prior probability that a check-in with this outcome was made at the premises
DEFAULT_VISIT_RELIABILITY = {
    "met_family": 0.94, "met_borrower": 0.88, "cash_collected": 0.92,
    "neighbour_says_shifted": 0.90, "locked_premises": 0.88, "no_such_person": 0.73,
}
ACCURACY_THRESHOLD_M = 250.0          # "correct" means within this distance
COVERAGE = 0.80                       # target coverage of the confidence radius
RAYLEIGH_MEDIAN = 1.1774              # median radial error = 1.1774 * sigma (2-D Gaussian)
LOCALITY_LEVEL_SOURCES = ("locality", "base_locality", "base_pincode")

_POI_RADIUS_M = 600.0                 # a landmark further than this from the anchor is another landmark
_LABEL_CUT_M = 1500.0                 # confirmed visit this far from its locality is another place
_MIN_LOCALITY_POINTS = 6
_CLUSTER_LINK_M = 150.0
_MIN_SIGMA_OBSERVATIONS = 8

_SOURCE_DESCRIPTIONS = {
    "base_rooftop": "Commercial geocoder (rooftop precision)",
    "base_street": "Commercial geocoder (street precision)",
    "base_locality": "Commercial geocoder (locality precision)",
    "base_pincode": "Commercial geocoder (pincode precision only)",
    "locality": "Locality centre",
    "poi_near": "Landmark named in the address",
    "poi_behind": "Landmark named in the address (behind)",
    "poi_opposite": "Landmark named in the address (opposite)",
    "st_exact_1": "A confirmed address on the same street",
    "st_exact_2": "Confirmed addresses on the same street",
}


def _dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


@dataclass
class EvidenceEstimate:
    """Location estimate with its supporting evidence."""

    x: float
    y: float
    sigma_m: float
    confidence: float                 # calibrated P(error <= 250 m)
    radius_m: float                   # ~80% coverage radius
    method: str                       # field_visits | address_text
    sources: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    visits_used: int = 0
    visits_rejected: int = 0
    landmark: Optional[str] = None


class _LocalityRegressor:
    """Robust ridge regression of the offset from the locality centre on street structure and landmark."""

    def __init__(self, style: str, lam_street: float = 1.0, lam_landmark: float = 3.0):
        self.style = style
        self.lam_street = lam_street
        self.lam_landmark = lam_landmark
        self.c1 = self.c2 = 0.0
        self.W: Optional[np.ndarray] = None
        self.n = 0

    def _row(self, p: ParsedAddress) -> tuple[list[float], list[float]]:
        f, pen = [1.0], [1e-6]
        has1, has2 = p.s1 is not None, p.s2 is not None
        if self.style == "metro":
            # A block is a place of its own; roads run inside it
            for block in range(1, 9):
                f.append(1.0 if has2 and int(p.s2) == block else 0.0)
                pen.append(self.lam_street)
            for block in range(1, 9):
                f.append((p.s1 - 3.5) if (has1 and has2 and int(p.s2) == block) else 0.0)
                pen.append(self.lam_street * 4)
            f.append((p.s1 - 3.5) if has1 else 0.0)
            pen.append(self.lam_street)
        else:
            # Grid of crosses and mains, or numbered lanes
            f.append((p.s1 - self.c1) if has1 else 0.0)
            pen.append(self.lam_street * 0.01)
            f.append((p.s2 - self.c2) if has2 else 0.0)
            pen.append(self.lam_street * 0.01)
            f.append(0.0 if has1 else 1.0)
            pen.append(self.lam_street)
            f.append(0.0 if has2 else 1.0)
            pen.append(self.lam_street)
        for landmark_type in LANDMARK_TYPES:
            f.append(1.0 if p.landmark_type == landmark_type else 0.0)
            pen.append(self.lam_landmark)
        return f, pen

    def fit(self, parsed: Sequence[ParsedAddress], offsets: Sequence[tuple[float, float]]) -> "_LocalityRegressor":
        s1 = [p.s1 for p in parsed if p.s1 is not None]
        s2 = [p.s2 for p in parsed if p.s2 is not None]
        self.c1 = float(np.median(s1)) if s1 else 0.0
        self.c2 = float(np.median(s2)) if s2 else 0.0
        rows = [self._row(p) for p in parsed]
        X = np.array([r[0] for r in rows])
        penalty = np.diag(rows[0][1])
        Y = np.array(offsets, dtype=float)
        keep = np.ones(len(Y), dtype=bool)
        # Trimmed fit: confirmed visits can be at the wrong place (e.g. met at the office)
        for _ in range(3):
            Xk, Yk = X[keep], Y[keep]
            self.W = np.linalg.solve(Xk.T @ Xk + penalty, Xk.T @ Yk)
            residual = np.hypot(*(Y - X @ self.W).T)
            trimmed = residual <= max(150.0, 3.0 * float(np.median(residual[keep])))
            if trimmed.sum() < max(4, 0.6 * len(Y)) or (trimmed == keep).all():
                break
            keep = trimmed
        self.n = int(keep.sum())
        return self

    def predict(self, p: ParsedAddress) -> np.ndarray:
        return np.array(self._row(p)[0]) @ self.W


class EvidenceGeocoder:
    """Geocoder fitted on a dataset loader's addresses and field visits."""

    def __init__(self, loader, params: Optional[dict] = None, params_path: Optional[Path] = None):
        self.loader = loader
        self._visits = defaultdict(list)
        for visit in loader.field_visits.values():
            self._visits[visit.address_id].append(visit)
        self._localities_by_town = defaultdict(list)
        for loc in loader.localities.values():
            self._localities_by_town[loc.town_id].append((loc.locality_id, loc.locality_name))
        self._town_names = {t.town_id: t.town_name for t in loader.towns.values()}
        self._styles = {t.town_id: t.address_style for t in loader.towns.values()}
        self._pois = defaultdict(list)
        for poi in loader.landmarks.values():
            self._pois[(poi.town_id, poi.landmark_type)].append((poi.x, poi.y))
        self._parsed: dict[str, ParsedAddress] = {}

        # Confirmed locations of addresses that agents have reached
        self._labels: dict[str, tuple[float, float]] = {}
        self._labels_by_account = defaultdict(set)
        self._by_locality = defaultdict(list)
        for address_id, address in loader.addresses.items():
            if address.town_id not in self._town_names:
                continue
            label = self._label(self._visits.get(address_id, ()))
            if label is None:
                continue
            self._labels[address_id] = label
            self._labels_by_account[address.account_id].add(address_id)
            locality = loader.localities.get(self.parse(address_id).locality_id)
            if locality and _dist(label, (locality.centroid_x, locality.centroid_y)) <= _LABEL_CUT_M:
                self._by_locality[locality.locality_id].append(address_id)
        self._regressors = {lid: self._fit_regressor(lid, ids) for lid, ids in self._by_locality.items()}

        if params is None:
            path = params_path or DEFAULT_PARAMS_PATH
            if path.exists():
                try:
                    params = json.loads(path.read_text(encoding="utf-8"))
                except Exception as exc:
                    logger.warning("Could not read %s, refitting: %s", path, exc)
                # Saved parameters describe the visits they were fitted on
                if params and params.get("n_confirmed_addresses") != len(self._labels):
                    params = None
        self.params = params or self.fit_params()

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _label(visits) -> Optional[tuple[float, float]]:
        for outcomes in (SUCCESS_OUTCOMES, FALLBACK_LABEL_OUTCOMES):
            hits = [v for v in visits if v.outcome in outcomes]
            if hits:
                return (statistics.median(v.checkin_x for v in hits), statistics.median(v.checkin_y for v in hits))
        return None

    def parse(self, address_id: str) -> ParsedAddress:
        parsed = self._parsed.get(address_id)
        if parsed is None:
            address = self.loader.addresses[address_id]
            parsed = self.parse_text(address.address_text, address.town_id)
            self._parsed[address_id] = parsed
        return parsed

    def parse_text(self, text: str, town_id: str) -> ParsedAddress:
        return parse_address(text, self._localities_by_town.get(town_id, ()), self._town_names.get(town_id, ""))

    def _fit_regressor(self, locality_id: str, address_ids: Sequence[str]) -> Optional[_LocalityRegressor]:
        if len(address_ids) < _MIN_LOCALITY_POINTS:
            return None
        loc = self.loader.localities[locality_id]
        offsets = [(self._labels[a][0] - loc.centroid_x, self._labels[a][1] - loc.centroid_y) for a in address_ids]
        return _LocalityRegressor(self._styles.get(loc.town_id, "grid")).fit([self.parse(a) for a in address_ids], offsets)

    # ------------------------------------------------------------ text evidence
    def text_components(self, parsed: ParsedAddress, town_id: str, baseline, exclude=frozenset()) -> dict:
        """Independent location estimates from the address text, keyed by source."""
        out: dict[str, tuple[float, float]] = {}
        loc = self.loader.localities.get(parsed.locality_id) if parsed.locality_id else None
        centre = (loc.centroid_x, loc.centroid_y) if loc else None
        if baseline is not None:
            out[f"base_{baseline.precision}"] = (baseline.geocoder_x, baseline.geocoder_y)
        if centre:
            out["locality"] = centre
        all_neighbours = self._by_locality.get(parsed.locality_id, []) if parsed.locality_id else []
        neighbours = [a for a in all_neighbours if a not in exclude] if exclude else all_neighbours

        if parsed.landmark_type:
            anchor = centre or out.get("base_street") or out.get("base_rooftop") or out.get("base_locality")
            candidates = self._pois.get((town_id, parsed.landmark_type), [])
            if anchor and candidates:
                poi = min(candidates, key=lambda c: _dist(c, anchor))
                if _dist(poi, anchor) <= _POI_RADIUS_M:
                    out[f"poi_{parsed.relation}"] = poi

        has_street = parsed.s1 is not None or parsed.s2 is not None
        if centre and (has_street or parsed.landmark_type):
            regressor = (self._regressors.get(parsed.locality_id) if len(neighbours) == len(all_neighbours)
                         else self._fit_regressor(parsed.locality_id, neighbours))
            if regressor is not None:
                # A landmark only helps if confirmed addresses in this locality mention it too
                landmark_seen = parsed.landmark_type is not None and any(
                    self.parse(a).landmark_type == parsed.landmark_type for a in neighbours)
                if has_street or landmark_seen:
                    offset = regressor.predict(parsed)
                    key = ("reg_st" + ("+lm" if landmark_seen else "")) if has_street else "reg_lm"
                    key += "_n%d" % (1 if regressor.n < 12 else 2 if regressor.n < 25 else 3)
                    out[key] = (centre[0] + float(offset[0]), centre[1] + float(offset[1]))

        if parsed.s1 is not None and parsed.s2 is not None:
            exact = [a for a in neighbours if self.parse(a).s1 == parsed.s1 and self.parse(a).s2 == parsed.s2]
            if exact:
                out["st_exact_2" if len(exact) >= 2 else "st_exact_1"] = (
                    statistics.median(self._labels[a][0] for a in exact),
                    statistics.median(self._labels[a][1] for a in exact),
                )
        return out

    @staticmethod
    def fuse(components: dict, sigma: dict) -> Optional[tuple[tuple[float, float], float, list[str]]]:
        """Inverse-variance fusion of the usable components."""
        usable = [k for k in components if k in sigma]
        if not usable:
            return None
        # Sources built from the same information are strongly correlated: keep the best of each family
        coarse = [k for k in usable if k in LOCALITY_LEVEL_SOURCES]
        fine = [k for k in usable if k not in LOCALITY_LEVEL_SOURCES]
        street = [k for k in fine if k.startswith(("st_", "reg_"))]
        if len(street) > 1:
            best = min(street, key=lambda k: sigma[k])
            fine = [k for k in fine if k not in street or k == best]
        keys = fine + ([min(coarse, key=lambda k: sigma[k])] if coarse else [])
        weights = np.array([1.0 / sigma[k] ** 2 for k in keys])
        points = np.array([components[k] for k in keys])
        mean = (weights[:, None] * points).sum(0) / weights.sum()
        return (float(mean[0]), float(mean[1])), float(1.0 / math.sqrt(weights.sum())), keys

    # ------------------------------------------------------------------ fitting
    def fit_params(self) -> dict:
        """Measure every evidence source by leave-one-account-out validation and calibrate confidence."""
        loader = self.loader
        errors = defaultdict(list)
        held_out = {}
        for address_id, truth in self._labels.items():
            address = loader.addresses[address_id]
            components = self.text_components(
                self.parse(address_id), address.town_id, loader.baseline_geocodes.get(address_id),
                exclude=self._labels_by_account[address.account_id],
            )
            held_out[address_id] = components
            for key, point in components.items():
                errors[key].append(_dist(point, truth))
        sigma = {k: statistics.median(e) / RAYLEIGH_MEDIAN for k, e in errors.items() if len(e) >= _MIN_SIGMA_OBSERVATIONS}

        fused_sigma, fused_error = [], []
        for address_id, components in held_out.items():
            fused = self.fuse(components, sigma)
            if fused:
                fused_sigma.append(fused[1])
                fused_error.append(_dist(fused[0], self._labels[address_id]))
        fused_sigma, fused_error = np.array(fused_sigma), np.array(fused_error)
        radius_scale = float(np.quantile(fused_error / fused_sigma, COVERAGE)) if len(fused_error) else 2.0
        text_tail = float(np.mean(fused_error > 4.0 * fused_sigma)) if len(fused_error) else 0.1

        calibration = {"sigma": [50.0, 400.0], "p": [0.9, 0.2]}
        if len(fused_error) >= 30:
            from sklearn.isotonic import IsotonicRegression
            iso = IsotonicRegression(increasing=False, y_min=0.02, y_max=0.98, out_of_bounds="clip")
            iso.fit(fused_sigma, (fused_error <= ACCURACY_THRESHOLD_M).astype(float))
            calibration = {"sigma": [float(v) for v in iso.X_thresholds_], "p": [float(v) for v in iso.y_thresholds_]}

        # Visit reliability: how often a check-in lands at the place confirmed by the other successful visits
        distances = defaultdict(list)
        for address_id, visits in self._visits.items():
            successes = [v for v in visits if v.outcome in SUCCESS_OUTCOMES]
            for visit in visits:
                others = [s for s in successes if s.visit_id != visit.visit_id]
                if others:
                    centre = (statistics.median(s.checkin_x for s in others), statistics.median(s.checkin_y for s in others))
                    distances[visit.outcome].append(_dist((visit.checkin_x, visit.checkin_y), centre))
        reliability = dict(DEFAULT_VISIT_RELIABILITY)
        inlier_distances = []
        for outcome, values in distances.items():
            inliers = [d for d in values if d <= 300.0]
            if len(values) >= 20:
                reliability[outcome] = round(min(0.97, len(inliers) / len(values)), 3)
            if outcome in SUCCESS_OUTCOMES:
                inlier_distances.extend(inliers)
        # Median distance between two independent check-ins = 1.1774 * sqrt(2) * sigma
        visit_sigma = statistics.median(inlier_distances) / (RAYLEIGH_MEDIAN * math.sqrt(2)) if inlier_distances else 30.0

        return {
            "version": 1,
            "n_confirmed_addresses": len(self._labels),
            "sigma": {k: round(v, 1) for k, v in sorted(sigma.items())},
            "radius_scale": round(radius_scale, 3),
            "text_tail": round(text_tail, 3),
            "calibration": calibration,
            "visit_reliability": {k: v for k, v in reliability.items() if v >= 0.5},
            "visit_sigma": round(float(visit_sigma), 1),
        }

    def save_params(self, path: Optional[Path] = None) -> Path:
        path = path or DEFAULT_PARAMS_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.params, indent=2), encoding="utf-8")
        return path

    # --------------------------------------------------------------- prediction
    def _text_confidence(self, sigma_m: float) -> float:
        calibration = self.params["calibration"]
        return float(np.interp(sigma_m, calibration["sigma"], calibration["p"]))

    def _visit_clusters(self, visits) -> list[dict]:
        reliability = self.params["visit_reliability"]
        points = [(v.checkin_x, v.checkin_y, reliability[v.outcome]) for v in visits if v.outcome in reliability]
        clusters = []
        while points:
            def support(seed):
                return sum(math.log(p / (1 - p)) for x, y, p in points if _dist((x, y), seed) <= _CLUSTER_LINK_M)
            seed = max(points, key=lambda pt: support(pt[:2]))
            members = [pt for pt in points if _dist(pt[:2], seed[:2]) <= _CLUSTER_LINK_M]
            points = [pt for pt in points if pt not in members]
            if len(members) >= 3:
                centre = (statistics.median(m[0] for m in members), statistics.median(m[1] for m in members))
            else:
                total = sum(m[2] for m in members)
                centre = (sum(m[0] * m[2] for m in members) / total, sum(m[1] * m[2] for m in members) / total)
            clusters.append({"centre": centre, "members": members})
        return clusters

    def predict(self, address_id: str) -> Optional[EvidenceEstimate]:
        """Locate an address of the fitted dataset (its own account's labels are held out of the text model)."""
        address = self.loader.addresses.get(address_id)
        if address is None:
            return None
        return self.predict_for(
            address.address_text, address.town_id, self.loader.baseline_geocodes.get(address_id),
            self._visits.get(address_id, ()), exclude=self._labels_by_account.get(address.account_id, frozenset()),
            parsed=self.parse(address_id),
        )

    def predict_for(self, text: str, town_id: str, baseline, visits, exclude=frozenset(),
                    parsed: Optional[ParsedAddress] = None, use_visits: bool = True) -> Optional[EvidenceEstimate]:
        params = self.params
        parsed = parsed or self.parse_text(text, town_id)
        components = self.text_components(parsed, town_id, baseline, exclude)
        text_fused = self.fuse(components, params["sigma"])
        clusters = self._visit_clusters(visits) if use_visits else []
        if text_fused is None and not clusters:
            return None

        town = self.loader.towns.get(town_id)
        log_uniform = -math.log(math.pi * (town.approx_radius_m if town else 4000.0) ** 2)
        spread = params["visit_sigma"] * math.sqrt(2)
        tail = min(0.5, max(0.02, params["text_tail"]))

        def text_term(distance: float) -> float:
            if text_fused is None:
                return 0.0
            s = text_fused[1]
            return math.log((1 - tail) * math.exp(-distance ** 2 / (2 * s * s)) / (2 * math.pi * s * s)
                            + tail * math.exp(log_uniform))

        all_points = [m for c in clusters for m in c["members"]]
        outlier_total = sum(math.log(1 - p) + log_uniform for _, _, p in all_points)
        scores = []
        for cluster in clusters:
            score = outlier_total
            for x, y, p in cluster["members"]:
                r = _dist((x, y), cluster["centre"])
                score += (math.log(p) - math.log(2 * math.pi * spread * spread) - r * r / (2 * spread * spread)
                          - math.log(1 - p) - log_uniform)
            if text_fused is not None:
                score += text_term(_dist(cluster["centre"], text_fused[0]))
            scores.append(score)
        if text_fused is not None:
            scores.append(outlier_total + text_term(0.0))
        top = max(scores)
        posterior = [math.exp(s - top) for s in scores]
        posterior = [p / sum(posterior) for p in posterior]
        winner = max(range(len(scores)), key=lambda i: scores[i])
        p_winner = posterior[winner]

        landmark = parsed.landmark_type.replace("_", " ").title() if parsed.landmark_type else None

        # Every hypothesis: where the address would be, and its own 80% radius
        gaussian_radius = math.sqrt(-2 * math.log(1 - COVERAGE))
        cluster_sigmas = [max(15.0, params["visit_sigma"] / math.sqrt(len(c["members"]))) for c in clusters]
        centres = [c["centre"] for c in clusters]
        own_radius = [s * gaussian_radius for s in cluster_sigmas]
        if text_fused is not None:
            centres.append(text_fused[0])
            own_radius.append(params["radius_scale"] * text_fused[1])
        # The stated radius has to reach the alternatives until 80% of the probability is covered
        radius, covered = 0.0, 0.0
        for i in sorted(range(len(scores)), key=lambda i: -posterior[i]):
            radius = max(radius, _dist(centres[winner], centres[i]) + own_radius[i])
            covered += posterior[i]
            if covered >= COVERAGE:
                break

        if winner < len(clusters):
            cluster = clusters[winner]
            n = len(cluster["members"])
            sigma = cluster_sigmas[winner]
            within = 1 - math.exp(-ACCURACY_THRESHOLD_M ** 2 / (2 * sigma * sigma))
            reach = max(_dist(m[:2], cluster["centre"]) for m in cluster["members"])
            evidence = [f"{n} on-premises visits within {reach:.0f} m of their centre" if n > 1 else "1 on-premises visit"]
            if text_fused is not None:
                gap = _dist(cluster["centre"], text_fused[0])
                evidence.append(f"Address text points {gap:.0f} m away" if gap > 3 * text_fused[1]
                                else "Consistent with the address text")
            rejected = len(all_points) - n
            if rejected:
                evidence.append(f"{rejected} other check-in{'s' if rejected > 1 else ''} elsewhere ignored")
            return EvidenceEstimate(
                x=cluster["centre"][0], y=cluster["centre"][1], sigma_m=sigma,
                confidence=min(0.98, p_winner * within), radius_m=radius, method="field_visits",
                sources=["visits"], evidence=evidence, visits_used=n, visits_rejected=rejected, landmark=landmark,
            )

        point, sigma, keys = text_fused
        evidence = [self._describe(k, parsed) for k in sorted(keys, key=lambda k: params["sigma"][k])]
        if all_points:
            evidence.append(f"{len(all_points)} check-in{'s' if len(all_points) > 1 else ''} far from the address ignored")
        return EvidenceEstimate(
            x=point[0], y=point[1], sigma_m=sigma, confidence=min(0.98, p_winner * self._text_confidence(sigma)),
            radius_m=radius, method="address_text", sources=keys, evidence=evidence,
            visits_used=0, visits_rejected=len(all_points), landmark=landmark,
        )

    def _describe(self, key: str, parsed: ParsedAddress) -> str:
        if key.startswith("reg_"):
            locality = self.loader.localities.get(parsed.locality_id)
            n = len(self._by_locality.get(parsed.locality_id, ()))
            name = locality.locality_name if locality else "the locality"
            what = "landmark pattern" if key.startswith("reg_lm") else "street layout"
            return f"{name} {what} learned from {n} confirmed addresses"
        return _SOURCE_DESCRIPTIONS.get(key, key)


_geocoders: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()
_geocoders_lock = threading.Lock()


def get_evidence_geocoder(loader) -> EvidenceGeocoder:
    """Evidence geocoder for a dataset loader, fitted once per loader."""
    with _geocoders_lock:
        geocoder = _geocoders.get(loader)
        if geocoder is None:
            geocoder = EvidenceGeocoder(loader)
            _geocoders[loader] = geocoder
        return geocoder
