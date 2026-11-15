# Predictive Maintenance Agent for Power Electronics

Portfolio demonstrator for predictive maintenance of utility-scale Freesun
solar inverters and NB-series EV chargers. The system will generate synthetic
SCADA-like telemetry, estimate progressive degradation, investigate anomalies
with Google ADK agents, and present a traceable, safety-gated maintenance
recommendation.

## Status

- Phase 1 — domain research and infographic brief: complete; the source
  document is present locally but has not been added to this public repository.
- Phase 2 — state of the art and sequence-model definition: in progress.
- Target demo/review: **15 January 2027**.

The target assumes approximately 8–10 hours of solo work per week from
16 November 2026, with a demonstrable synthetic-data path and simulated
management/control actions. Allow roughly one additional week if access to
Google Cloud services or observability tooling takes longer than expected.

## Planned demo

1. Generate reproducible Freesun- and NB-like telemetry profiles.
2. Inject gradual IGBT thermal and DC-link ESR degradation, plus humidity-linked
   insulation-resistance drops.
3. Use a sequence model as an experimental predictor; report its performance
   on held-out synthetic scenarios without implying validation on real assets.
4. Route anomalies through a root orchestrator and thermal/dielectric
   specialist agents.
5. Apply a policy gate before any action. Jira/SAP operations and power
   derating/isolation are **simulations only**; this portfolio project will not
   connect to or command real OT equipment.
6. Show telemetry, predictions, agent hand-offs, safety decisions, and the
   resulting simulated work order in a live demo.

## Initial scope

- Primary telemetry: estimated IGBT junction temperature, DC-link ESR,
  insulation resistance to ground, and AC phase-current asymmetry.
- Supporting context: ambient temperature, humidity, irradiance, load/current,
  heatsink temperature, and device family.
- Compare windowing/sequence handling for smooth solar operating profiles and
  the faster 20–40 minute EV-charging thermal ramps.
- Keep synthetic data generation, model evaluation, agent reasoning, and
  action execution separable and testable.

## Tracking

The GitHub repository contains dated milestones and issues. The companion
GitHub Project board is the working kanban; development is intentionally on
`main` because this is a solo portfolio project.

See [docs/roadmap.md](docs/roadmap.md) for the schedule, acceptance criteria,
assumptions, and demo gate.
