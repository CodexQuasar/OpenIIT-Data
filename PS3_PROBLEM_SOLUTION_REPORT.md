# PS3 Geocoder: Problem, Solution, Evidence and Delivery Plan

## Executive summary

CreditNirvana's field-collections teams need to find borrowers whose addresses
are often written as descriptions rather than postal locations. A commercial
geocoder may return a locality centre even when the useful operational answer is
"behind the ration shop, two lanes after the temple." The resulting search
time is expensive, productive visits are lost, and an account can be marked
address-not-traceable even though the borrower is present.

This project implements an address-intelligence service for that problem. It
combines address text, landmarks, localities, historical visit evidence, GPS
quality, dwell time, visit outcomes, remarks, integrity signals and shared-place
evidence. It returns a predicted location, an uncertainty radius, an
explainable evidence trail and an operational recommendation. Reliable
successful visits improve future predictions, while confirmed and predicted
locations remain separate so a weak prediction cannot overwrite a strong
observation.

The service is deliberately conservative. It uses projected PS3 coordinates as
metres during evaluation, does not pretend that every check-in is ground truth,
and refuses to report causal treatment effects when the supplied data lacks
treatment assignment and an independent recovery outcome. Every reproducible
evaluation run includes a run ID, artifact version, configuration, source-file
hashes, metrics and explicit limitations.

## 1. The business problem

### 1.1 Operational setting

The platform serves secured and unsecured retail, MSME and microfinance
portfolios. A lender may have millions of accounts across delinquency buckets.
Field work is expensive compared with digital contact:

| Channel | Typical fully-loaded cost |
| --- | ---: |
| SMS / WhatsApp | Fraction of a rupee |
| AI voice | Approximately INR 1-3 per call |
| Human tele-caller | Approximately INR 15-30 per connect |
| Productive field visit | Approximately INR 150-400 |

The correct objective is therefore recovery net of contact cost, customer
goodwill and compliance risk. A geocoder is useful only if it improves the
probability that a field visit is productive without encouraging unlawful or
excessive contact.

### 1.2 Why ordinary geocoding fails

Indian collection addresses frequently contain:

* mixed Devanagari, Roman, Kannada, Hindi and English text;
* transliteration differences such as `mandir`, `mandir`, and `temple`;
* abbreviations, spelling errors and inconsistent house numbers;
* relational descriptions such as "behind", "near", "opposite" and "next
  lane";
* informal landmarks that are not represented in a global geocoder;
* locality names shared by several towns;
* an address that identifies a shop, workplace or landmark rather than a
  precise residence.

Returning the pincode centroid is technically a geocode but operationally
unhelpful. In a dense or rural area, the error can be hundreds of metres or
several kilometres.

### 1.3 Why visit GPS is valuable but imperfect

The answer is often present in the platform already: a prior agent may have
met the borrower. However, a check-in is evidence, not unquestionable truth:

* the borrower may have been met at work or on a road;
* GPS accuracy may be poor;
* a device may have checked in at a tea stall or an agent's home;
* a failed search may be near the address but not at the address;
* a successful outcome can still be recorded with a misleading location.

The solution must combine evidence with reliability weights and uncertainty,
not copy the latest latitude and longitude.

## 2. Product requirements translated into system behaviour

| Requirement | Implemented behaviour |
| --- | --- |
| Location pin | Canonical account location plus predicted and confirmed fields |
| Honest uncertainty | Radius in metres, calibration metrics and fallback states |
| Landmark directions | Address entities and operational evidence are returned to the UI |
| Noisy evidence | GPS accuracy, dwell, outcome and integrity influence weights |
| Multilingual addresses | Unicode normalization, transliteration and entity pipeline |
| Shared places | Cluster enrichment and guarded propagation |
| Fake-visit resistance | Integrity and reliability scores reduce low-quality evidence |
| Offline field use | Service worker caching and queued visit synchronization |
| Planner integration | Explainable `visit_directly`, `verify_first` and skip actions |
| PS2 integration | Location-confidence RPC contract for right-party-contact models |
| Auditability | Authenticated routes, source fields, timestamps and persisted evidence |
| Compliance boundary | Collections purpose, access controls and explicit deployment limits |
| Evaluation | Versioned JSON artifacts with baselines, ablations and split metadata |

## 3. Data and coordinate handling

### 3.1 Source tables

The PS3 dataset is assembled from:

* shared addresses;
* shared field visits;
* surveyed addresses;
* commercial baseline geocodes;
* towns;
* localities;
* landmarks and points of interest;
* visit GPS points.

The evaluator validates the required files before running. It records SHA-256
hashes for the addresses, visits, surveyed and baseline files in every artifact
so a result can be reproduced against exactly the same inputs.

### 3.2 Projected coordinates

PS3 `x` and `y` values are projected local coordinates measured in metres. They
are not WGS84 latitude and longitude. Evaluation therefore uses Euclidean
distance:

```text
error_m = sqrt((predicted_x - surveyed_x)^2
             + (predicted_y - surveyed_y)^2)
```

This distinction is critical. Sending projected coordinates to Google Maps or
calculating a Haversine distance from them creates a plausible-looking but
invalid result. The frontend keeps projected PS3 scatter plots separate from
the optional Google Maps panel, which accepts WGS84 coordinates only.

### 3.3 Ground truth and evidence separation

Surveyed coordinates are evaluation truth. Baseline geocodes are a comparison
method. Visit check-ins are model evidence. Account records persist:

* `confirmed_*` fields for strong, confirmed operational observations;
* `predicted_*` fields for the latest model output;
* canonical location fields consumed by operational APIs;
* CRS metadata and timestamps.

A weaker prediction cannot replace a stronger confirmed location.

## 4. Address intelligence pipeline

### 4.1 Normalization

The address normalizer applies Unicode cleanup, whitespace normalization,
common abbreviation handling, transliteration-aware processing and robust
tokenization. Normalization is used for matching and candidate generation; the
original text is retained for audit and agent display.

### 4.2 Entity and relation extraction

The pipeline identifies useful address components:

* house and plot numbers;
* roads, cross roads and lanes;
* villages, towns and localities;
* temples, schools, shops and other landmarks;
* directional relations such as behind, opposite, beside and near;
* pincodes and administrative hints.

The important output is not merely a normalized string. It is a set of
searchable entities and relations that can be resolved against known landmarks
and prior account evidence.

### 4.3 Candidate generation

Candidates are generated from multiple sources:

1. commercial or open geocoder output;
2. historical successful visits;
3. nearby confirmed accounts and shared-place clusters;
4. known landmarks and locality centroids;
5. conservative corrections extracted from agent remarks.

Candidate generation intentionally produces alternatives. Ranking and
uncertainty estimation decide whether the alternatives are sufficiently
consistent for a direct visit.

### 4.4 Evidence aggregation

Successful visit evidence is weighted using:

* GPS accuracy;
* dwell time;
* visit outcome;
* trajectory and search shape;
* visit-integrity checks;
* recency and repeated independent support;
* agent-influence controls;
* shared-place corroboration.

The weighted centroid baseline in the evaluation runner is a transparent
reference implementation of this idea. The production candidate ranker adds
features and produces an explainable ranked candidate list.

### 4.5 Remarks and corrections

Remarks are retained for audit. Recognized correction phrases such as an
address being two lanes farther are captured conservatively. The system does
not claim that every free-form multilingual remark has been converted into a
precise geometric offset. This is an intentional safety boundary: a wrong
offset can move a field agent farther from the borrower.

### 4.6 Place resolution

When multiple accounts share a building or landmark, one reliable confirmed
visit can enrich the cluster. Propagation is guarded by source and reliability
thresholds. Cluster enrichment is not unconditional copying and must be
monitored at lender scale before broad write-back.

## 5. Confidence and operational decisions

The output contains a location candidate and a radius, rather than a naked
point. The radius is used by the planner and displayed to the agent. The
service can return:

* `visit_directly` when evidence and confidence are sufficient;
* `verify_first` when the location is plausible but uncertain;
* `skip_until_geocoded` when no usable coordinate candidate exists.

The frontend handles null predictions explicitly. An unresolved account shows
"No location candidate found" rather than attempting `toFixed()` on a null
value. This is important because an unresolved result is a valid model state,
not a frontend exception.

Calibration is reported as an evaluation metric. A confidence score that is
not calibrated can cause the planner to over-spend on false certainty, so the
system must prefer an honest verification action over a precise-looking guess.

## 6. Integrity and adversarial evidence controls

The system treats fake or low-quality visits as a model-risk problem:

* GPS accuracy is incorporated into evidence weight;
* very short or implausible dwell is down-weighted;
* outcomes are considered with the location rather than treated as proof;
* trajectories help distinguish searching from a direct approach;
* repeated evidence from one agent is prevented from dominating a cluster;
* failed visits remain useful as search evidence but are not treated as
  successful borrower locations;
* visit validation and integrity signals are auditable.

These controls reduce, but do not eliminate, manipulation risk. Production
deployment should monitor unusual agent-location concentration, repeated
identical coordinates and implausible travel patterns under the applicable
employment and monitoring framework.

## 7. Interfaces and workflow integration

### 7.1 Field app

The field app receives the corrected pin, radius, evidence summary and
landmark directions. Static assets and selected GET responses are cached for
poor-connectivity areas. Visit submissions are queued in IndexedDB when the
network is unavailable and synchronized later with the current bearer token.

Conflict resolution, dead-letter handling and complete offline planner data
remain deployment work and must be addressed before claiming full offline
parity.

### 7.2 Visit planner

`GET /api/planner/visits` exposes coordinates, confidence, radius, source and a
recommended action. The current implementation is an explainable prioritizer,
not a full road-network route optimizer. Future cost-aware routing should
include channel cost, distance, contact-hour rules, visit capacity and
productive-visit probability.

### 7.3 PS2/right-party-contact contract

`GET /api/rpc/location-features/{account_id}` exposes location features such
as confidence, radius, source, successful visits, failed searches and confirmed
status. PS2 can use these features to distinguish:

* a borrower who may have moved; from
* a borrower whose address is valid but difficult to find.

This is an integration contract, not a claim that the PS2 model itself has
been trained or causally validated by this repository.

### 7.4 Dashboards

The dashboard and benchmark use live evaluation responses and show measured
values rather than hard-coded scores. Backend 503 failures were addressed by
making real-data evaluation and metrics paths tolerate missing or insufficient
data while surfacing explicit unavailable statuses. Frontend rendering is
null-safe.

## 8. Security, RBAC and compliance

### 8.1 Why RBAC matters

Borrower locations, visit trails, agent GPS, remarks, planner output and
territory metrics are sensitive operational data. A field agent should not
automatically receive every lender's accounts or every territory's history.
Managers need broader territory views, auditors need evidence and audit access,
and administrators need configuration access.

The backend has authenticated operational routes and permission dependencies.
Production deployment must add lender/tenant and territory scoping at the data
query boundary, not only at the UI.

### 8.2 RBI and DPDP boundaries

The prototype does not claim that a generic configuration satisfies every
lender's legal obligations. Each deployment must configure and audit:

* permitted contact hours and frequency;
* consent and purpose limitation;
* retention and deletion windows;
* access logging and export controls;
* separation of collections data from unrelated uses;
* agent monitoring governance;
* incident response and correction workflows.

The geocoder should not infer locations beyond what collections requires.

## 9. Evaluation design

### 9.1 Reproducible artifacts

Run:

```powershell
cd backend
.\venv\Scripts\python.exe -m evaluation.ps3_experiments ..\Dataset `
  --split train --output-dir ..\evaluation_artifacts
```

The output is `ps3_eval_<run_id>.json`. It contains:

* artifact version and UTC run ID;
* split and coordinate-system declaration;
* SHA-256 hashes of source files;
* dataset counts;
* baseline metrics;
* ablation metrics;
* temporal and geography split metadata;
* counterfactual estimability status;
* radar metrics and their evidence boundary.

### 9.2 Baseline comparisons

The current artifact compares:

1. commercial baseline geocoder;
2. nearest reliable visit;
3. weighted visit centroid.

Metrics include median, P90 and P95 projected-metre error, thresholds at 50,
100, 250 and 500 metres, coverage, radius coverage/calibration and measured
per-prediction evaluation latency.

The latest generated artifact on the available training split contains 66
surveyed addresses and 3,896 visits. The commercial baseline's median error is
approximately 381 m and its P90 error is approximately 746 m. The visit
baselines cover fewer accounts because they require usable successful visits;
their coverage must therefore be reported alongside accuracy.

### 9.3 Controlled ablations

The artifact separates:

* address only;
* address plus visits;
* address plus visits plus integrity weighting;
* address plus nearby evidence.

Nearby-account evidence is marked `not_estimable` when the dataset lacks an
independent nearby-account treatment/evidence table. A locality centroid must
not be substituted silently because that would confound the ablation.

### 9.4 Radar metrics

The radar reports accuracy, coverage, calibration, robustness, explainability
and latency. The currently generated radar is explicitly labelled
`baseline_coverage`: it uses measured baseline values and does not pretend to
be a complete production-model radar. Production reporting should replace
baseline values with frozen-model measurements on held-out data and document
how robustness is calculated across towns and evidence-integrity strata.

### 9.5 Temporal split

Visits are ordered by check-in time. The evaluator defines a cutoff and uses
only pre-cutoff visits for the temporal evidence calculation. Future visits
are not allowed to construct the pre-cutoff prediction. The artifact records
the cutoff and counts, plus a pre-cutoff weighted-centroid diagnostic.

For production certification, retrain or freeze the model using only data
available before the cutoff and evaluate on later outcomes. Do not tune
thresholds against the future set.

### 9.6 Geography holdout

The evaluator holds out one town and evaluates an address-only baseline on
that town without using held-out-town visit evidence. This is a leakage-safe
diagnostic, not a complete production-model generalization score. The
production model must be retrained using train-town data only, then scored on
the held-out town. Repeat across towns when sample sizes allow.

### 9.7 Account-level splitting

Visit rows from the same account must not be randomly split between training
and evaluation. Otherwise the model can memorize a visit for an account and
appear accurate. The production evaluation harness should materialize account
groups before fitting and assert that train and evaluation account IDs are
disjoint.

### 9.8 Counterfactual evaluation

IPW and doubly robust policy evaluation cannot be validly computed from the
provided PS3 files alone. The files contain visit outcomes, but no randomized
or policy-assigned treatment/action column and no independent recovery outcome.
The artifact therefore returns:

```json
{
  "status": "not_estimable",
  "estimand": "policy value / treatment effect",
  "required_columns": [
    "treatment/action/policy_arm",
    "recovery outcome",
    "pre-treatment covariates"
  ]
}
```

This is a feature, not a missing score. Fabricating a causal estimate would
violate the counterfactual-data requirement. A controlled pilot should record
policy arm, channel/action, pre-treatment covariates, contact eligibility,
recovery outcome, cost and compliance events. Once those fields exist, the
runner can calculate propensities, weight diagnostics, effective sample size,
IPW policy value and a doubly robust estimate with confidence intervals.

## 10. Notebook and submission

`Submission/PS3_Geocoder_EDA.ipynb` now includes:

* file discovery and data-quality checks;
* address, landmark, locality and town coverage;
* visit outcome, GPS accuracy, dwell and agent concentration analysis;
* projected-coordinate sanity checks;
* commercial baseline and optional production evaluation;
* calibration and town-level summaries;
* reproducible versioned experiment-artifact execution;
* baseline, ablation, split, radar and causal-status tables;
* an explicit interpretation and evidence-boundary section.

The notebook does not claim causal results when causal fields are absent.
Notebook JSON and extracted Python code have been syntax-validated. Full
notebook execution still depends on an environment with the repository's
notebook execution dependencies installed.

## 11. Frontend reliability and usability

The frontend includes:

* persistent light/dark mode in login and authenticated navigation;
* null-safe unresolved-location rendering;
* optional Google Maps JavaScript integration with a restricted browser key;
* local-coordinate scatter plots for PS3;
* offline queue and service-worker caching;
* authenticated API requests and expiry handling.

Google Maps is optional. It requires `VITE_GOOGLE_MAPS_API_KEY`, the Maps
JavaScript API, billing and HTTP-referrer restrictions. Projected PS3 values
are never sent to Google Maps as if they were WGS84.

## 12. Deployment plan

### Phase 1: shadow mode

* ingest visit evidence without changing planner decisions;
* measure distance error, coverage and calibration;
* inspect integrity alerts and remark extraction;
* establish tenant, territory and retention policies;
* review false positives with field managers.

### Phase 2: controlled pilot

* select comparable territories;
* freeze a time-based model version;
* define incumbent and geocoder-assisted policies;
* record action assignment and recovery outcomes;
* measure productive visits per agent-day and cost per recovery;
* monitor complaint, contact-hour and privacy events.

### Phase 3: guarded rollout

* enable direct visits only above calibrated thresholds;
* route low-confidence cases through verification;
* keep confirmed and predicted write-back separate;
* monitor town-level drift and agent-integrity anomalies;
* retain a rollback path to the incumbent policy.

### Phase 4: continuous governance

* version data, model, configuration and evaluation artifacts;
* rerun temporal and geography holdouts;
* recalibrate after population or device changes;
* review cluster propagation thresholds;
* delete data according to lender retention policy;
* audit access and correction requests.

## 13. Known limitations and next engineering work

1. The planner now supports an origin and maximum-distance budget with
   deterministic distance-aware prioritization, but is not yet a full
   travel-time or cost-aware route optimizer.
2. The available PS3 dataset cannot support a causal policy-value estimate.
3. Nearby-account ablation needs an independent evidence table.
4. Production-model geography holdout requires train-town-only retraining.
5. Ranker training now creates a deterministic account-level 80/20 partition
   and asserts zero overlap before fitting. A complete production harness
   should also score the held-out partition separately.
6. Multilingual remark-to-offset extraction remains conservative.
7. Cluster propagation requires lender-specific scale thresholds.
8. Offline retries now move five-time failures to a local dead-letter store.
   Conflict resolution, retry observability and server-side idempotency still
   need production hardening.
9. Tenant and territory filtering must be enforced in repository queries.
10. Full notebook execution requires notebook dependencies in the backend
    environment.

## 14. Acceptance checklist

Before a lender pilot is approved, confirm:

- [ ] all operational routes require authentication and scoped permissions;
- [ ] tenant and territory filters are enforced server-side;
- [ ] RBI contact-hour and frequency policy is configured;
- [ ] DPDP consent, purpose and retention controls are configured;
- [ ] projected and WGS84 coordinate systems are explicit at every boundary;
- [ ] confirmed locations cannot be overwritten by weak predictions;
- [ ] visit-integrity alerts are reviewed;
- [ ] baseline and ablation artifact hashes are stored;
- [ ] temporal and geography holdouts are frozen before tuning;
- [x] ranker training asserts disjoint account IDs before fitting;
- [ ] held-out account partition is scored separately;
- [ ] counterfactual fields exist before any IPW/DR claim;
- [ ] offline sync conflict handling is tested;
- [ ] field users can see directions, radius and evidence offline;
- [ ] rollback to the incumbent planner is tested;
- [ ] productive-visit and cost metrics are measured in a controlled pilot.

## Conclusion

The project addresses the core PS3 problem with a practical evidence-learning
geocoder rather than a generic address lookup. It combines messy address
understanding with noisy field observations, gives the planner uncertainty
instead of false precision, and exposes the operational contracts needed by
the field app, dashboards and PS2. The evaluation framework now makes the
remaining evidence boundaries visible: descriptive baselines can be measured
now, leakage-safe split diagnostics are recorded, and causal evaluation waits
for the data that makes it identifiable.
## Administrative operations and account discovery

The prototype now separates operational use from privileged administration.
All authenticated users can use the account workflow, while the frontend
shows the Admin route only when the login response identifies the user as an
`admin`. The Admin page exposes model metadata and a retraining request
control. The retraining endpoint is protected by the backend RBAC dependency,
so hiding the navigation item is not the security boundary. Model metadata
remains available to the existing health and operational checks, but changing
model state requires the admin permission.

Account discovery is server-side rather than limited to the browser's initial
page. `GET /api/real/accounts` accepts `search`, `limit`, and `offset`.
Matching is case-insensitive across account ID, town, preferred language, and
all address text associated with the account. This lets a collections
supervisor find an account by a local address fragment or town before opening
address intelligence, while preserving pagination for larger lender
portfolios. Production deployments should add tenant scoping and audit events
to the same route.
