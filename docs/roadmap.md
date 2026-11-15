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
| M1 — SOTA and sequence-model specification | 4 Dec 2026 | Degradation mechanisms, signal definitions, labels, window policy, and evaluation protocol documented. |
| M2 — Simulator and predictive baseline | 18 Dec 2026 | Reproducible Freesun/NB telemetry and degradation scenarios; baseline evaluated on held-out synthetic runs; model callable through a stable interface. |
| M3 — Multi-agent investigation and safe actions | 8 Jan 2027 | ADK orchestration and specialist agents use typed tools; all proposed actions pass a fail-closed policy gate; external actions remain mocked. |
| M4 — Observability and demo-ready package | 15 Jan 2027 | End-to-end scenario, dashboard/visualization, traces, runbook, limitations, and review checklist are ready. |

## Demo acceptance gate

- A single documented command or short command sequence starts the simulator
  and demo application from a clean local environment.
- A fixed random seed reproduces the selected degradation scenario.
- Anomaly detection and prediction outputs identify the simulated signal,
  asset profile, confidence/uncertainty, and prediction horizon.
- Evaluation uses chronological train/validation/test separation and includes
  at least one baseline; report false alarms and lead-time on synthetic test
  scenarios.
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
