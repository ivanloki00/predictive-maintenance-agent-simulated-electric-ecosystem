# Phase 2 implementation notes

## Status and interpretation

The SOTA report is included at [phase-2-sota.md](phase-2-sota.md). It is an
architecture proposal and literature synthesis, not evidence that the proposed
models have been trained or validated on Freesun/NB field data.

In particular, treat reported numerical accuracy, specific material
coefficients, and remaining-useful-life claims as unverified until their source,
dataset, operating conditions, and evaluation method have been checked. The
simulator can test whether a method recovers its own generated ground truth; it
cannot establish field accuracy.

## MVP decisions

- **Temperature estimation:** generate a hidden junction-temperature target
  from a simple, documented thermal RC model. Start with that physical/naive
  baseline; compare an LSTM on held-out scenarios before considering a PINN,
  attention, or convolutional sequence architecture.
- **Adaptive windows:** select bounded window durations through deterministic
  operating-regime logic (solar profile, idle, or NB charging transient).
  Record both duration and sample count. Do not delegate sampling cadence or
  protection decisions to an LLM agent.
- **Insulation degradation:** use a configurable humidity-exposure accumulator
  as a synthetic mechanism. A Peck-inspired formulation is a hypothesis, not a
  calibrated lifetime law without material-specific parameters and evidence.
- **Trend extraction:** compare a simple baseline/trend estimator first; add STL
  only if the generated sampling cadence and seasonal behavior make it useful.
- **Evaluation:** split by complete generated runs/scenarios in chronological
  order to prevent overlapping-window leakage. Report temperature error,
  event false alarms/misses, detection lead time, and early-versus-late
  prediction costs. Report RUL only after the simulator defines a failure
  threshold and ground-truth failure time.
- **Agent boundary:** conventional code handles telemetry, regime selection,
  prediction, and policy checks. ADK agents explain event evidence and request
  simulated actions; they do not issue commands to live equipment.

## Next implementation step: freeze the telemetry contract

Complete GitHub issue
[#2 — Define the telemetry contract and synthetic data schema](https://github.com/ivanloki00/predictive-maintenance-agent-simulated-electric-ecosystem/issues/2)
before implementing `telemetry_sim.py`.

The schema should specify timestamp/cadence, asset and scenario IDs, profile,
units, missing-value rules, and at least:

- Observable context: ambient temperature, relative humidity, irradiance or
  charger load/session state, heatsink temperature, DC bus voltage/current,
  and three AC phase currents.
- Simulated targets/labels kept separate from model inputs: estimated IGBT
  junction temperature, ESR, insulation resistance, degradation mode, onset
  time, severity, and failure threshold/time where applicable.
- Reproducibility and evaluation metadata: random seed, scenario/run ID, and
  train/validation/test group.

**Exit check:** a versioned schema and example healthy/degraded records are
reviewed; every feature is labelled as measured-like input, derived feature,
or simulator-only ground truth. Only then should the generator and its
fault-injection functions be implemented.
