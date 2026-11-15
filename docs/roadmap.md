# Roadmap and demo plan

## Estimate

**Target review date: 15 January 2027.** This is a planning estimate, not a
guarantee. It assumes solo development at 8–10 hours per week beginning
16 November 2026, approximately 72–90 hours in total, and a portfolio demo
using synthetic data and mocked actions. The date includes about one week of
integration/buffer time. Revisit the estimate if weekly availability or cloud
service access differs materially.

| Milestone | Target date | Exit criteria |
| --- | --- | --- |
| M1 — SOTA and sequence-model specification | 4 Dec 2026 | Phase 2 report incorporated; telemetry schema, bounded window policy, evaluation protocol, and review of quantitative claims completed. |
| M2 — Simulator and predictive baseline | 18 Dec 2026 | Reproducible Freesun/NB telemetry and degradation scenarios; baseline evaluated on held-out synthetic runs; model callable through a stable interface. |
| M3 — Multi-agent investigation and safe actions | 8 Jan 2027 | ADK orchestration and specialist agents use typed tools; all proposed actions pass a fail-closed policy gate; external actions remain mocked. |
| M4 — Observability and demo-ready package | 15 Jan 2027 | End-to-end scenario, dashboard/visualization, traces, runbook, limitations, and review checklist are ready. |

## Phase 2 outcome and model decisions

The [Phase 2 SOTA report](phase-2-sota.md) proposes PINN/LSTM-based hidden
temperature estimation, adaptive windows for Freesun and NB operating
profiles, humidity-informed insulation degradation, and prognostics metrics.
These are design hypotheses, not validation results for real equipment.

The implementation order is intentionally narrower; details and rationale are
in [phase-2-implementation-notes.md](phase-2-implementation-notes.md):

1. Define a versioned telemetry contract and keep observable inputs separate
   from simulator-only ground truth.
2. Build deterministic, seeded operating profiles and degradation scenarios.
3. Establish a simple physics-inspired/naive baseline before testing an LSTM.
   Add PINN, attention, or a more elaborate architecture only if the baseline
   and available data justify the complexity.
4. Make regime/window selection deterministic and bounded in code; agents
   investigate detected events and do not control high-rate sampling or
   protection behavior.
5. Treat humidity/Peck-style damage and all model performance as synthetic and
   uncalibrated unless material-specific parameters and suitable validation
   data become available.

## Demo acceptance gate

- A single documented command or short command sequence starts the simulator
  and demo application from a clean local environment.
- A fixed random seed reproduces the selected degradation scenario.
- Anomaly detection and prediction outputs identify the simulated signal,
  asset profile, confidence/uncertainty, and prediction horizon.
- Evaluation uses chronological train/validation/test separation and includes
  at least one baseline; report false alarms and lead-time on synthetic test
  scenarios.
- Do not present the report's cited temperature-accuracy figure or any
  synthetic-data metric as a guaranteed real-equipment result unless it is
  independently reproduced and its test conditions are documented.
- Agent outputs cite the telemetry/tool results they used; tool schemas and
  failures are explicit.
- Unsafe, malformed, or unapproved actions are rejected. No credentials or
  live OT endpoints are required for the demo.
- A reviewer can follow one event from telemetry through prediction, agent
  analysis, safety decision, and simulated work order.

## Scope and risk controls

- The simulator is not a validated digital twin; synthetic model performance
  does not establish real-world predictive accuracy.
- Do not connect this demo to production SCADA, inverter controls, Jira, or SAP.
  Management and power-control actions are mocked.
- Model Armor integration depends on access to Google Cloud; if unavailable,
  use a clearly labelled local policy-gate test double and document the gap.
- Phoenix or a comparable local tracing setup is sufficient for the demo;
  avoid letting an external observability account block the core story.
- Track the four primary signals first. Treat THDi and active thermal derating
  as optional context if schedule permits.

## Working cadence

Use the repository's GitHub Project board to move issues through Todo, In
Progress, Review, and Done. Keep development on `main`. Review the target date
at each milestone and trim optional scope before sacrificing testability or
the safety gate.
