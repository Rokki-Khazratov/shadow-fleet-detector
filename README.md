# Shadow Fleet Detector

```text
                   ·              .
    ~ ~ ~    >──────●     ~ ~ ~
             maritime signals / visible evidence
```

**An exploratory vessel map for following maritime signals and investigating the evidence behind them.**

Shadow Fleet Detector is a research-driven project with a long-term ambition: make maritime movement easier to explore, and help researchers examine potential connections to the shadow fleet with transparent sources and uncertainty. The intended experience is a global map for all types of vessels, using free data where possible.

> **Current status: local prototype.** The current implementation uses Fintraffic as its position source and has been tested locally with synthetic data. Global coverage, continuous live operation and public deployment have not been established. The project does not identify vessels as part of a shadow fleet.

## What you can explore today

- **Current positions:** a local map and read API show available Fintraffic observations, their timestamps, freshness and source status. Coverage is limited to what the source provides; an empty area does not mean there are no vessels.
- **History:** an optional local history stores and displays individual observations within a bounded retention window. It does not reconstruct a complete route.
- **Dossier:** a local catalogue can hold dated links and external claims with source references. It is empty by default, and ambiguous identities remain unresolved.
- **Data quality:** a neutral summary describes gaps between saved observations, time conflicts and clock differences. It does not infer the causes of those gaps.
- **Synthetic demo:** explore the interface without a database, API or live AIS connection. Demo observations are explicitly labelled as synthetic.

AIS observations are signals, not proof of misconduct. A sanctions listing, an unusual movement pattern and an association with the shadow fleet are distinct claims. The project aims to keep observations, external claims and analytical hypotheses separate and traceable.

## Try the synthetic demo

The demo needs Node.js in the range specified in [web/package.json](web/package.json). From the repository root:

```sh
cd web
npm ci
npm run dev
```

Open **http://127.0.0.1:5173/?demo=1**. The demo uses synthetic data and does not need the backend or PostgreSQL. The map background and city labels use local Natural Earth assets; see the [interface and attribution notes](docs/design/workspace.md).

For the full local setup, including Python 3.12, Docker, PostgreSQL/PostGIS, migrations and a read-only API role, follow the [local run guide](docs/run-local.md). The collector is a separate process: running it connects to the real Fintraffic service. Live collection and source coverage need further verification before use beyond a local experiment.

## How it fits together

```text
 Fintraffic REST + MQTT
           │
           ▼
 Collector → PostgreSQL / PostGIS → Read API → MapLibre interface
                    │
                    └── optional local history and dossier data
```

The collector reconciles a snapshot with incoming updates and writes the current position projection. The API reads stored observations and source health; the browser displays them with their age and attribution. The architecture and thresholds remain under review as the implementation develops.

**Current stack:** Python, FastAPI, PostgreSQL/PostGIS, Paho MQTT, TypeScript, Vite and MapLibre GL JS. See the [system design](docs/architecture/system-design.md), [database design](docs/architecture/database-design.md) and [API reference](docs/api/v1.md) for details.

## Data and limitations

The project prioritizes free sources, but free access does not imply global coverage, complete records or unrestricted redistribution. Fintraffic is the current position source; other sources are being researched separately in the [data and API register](docs/data-and-api.md).

Positions may be delayed, incomplete, duplicated or incorrect. An MMSI identifies an observed signal in this prototype and is not by itself a verified vessel identity. History is limited to data actually collected locally. The dossier is not an automatically verified ownership or sanctions registry. Do not use this prototype for navigation or as the sole basis for consequential conclusions.

Fintraffic open data is provided under [CC BY 4.0 and its attribution terms](https://www.digitraffic.fi/en/terms-of-service/). Source data, map assets, dependencies and project code have separate licensing conditions.

## Verification and development

The documented local acceptance run uses synthetic data and an isolated test database. To run it after completing the prerequisites in the local guide:

```sh
.venv/bin/python scripts/accept_local.py
```

This requires Docker, the installed Python and web dependencies, and Chrome. Consult the [acceptance record](docs/development/acceptance.md) for what was actually tested and the [release-readiness assessment](docs/development/release-readiness.md) for remaining limitations. A successful synthetic run does not establish live coverage or production readiness.

Please keep secrets, database dumps and raw external datasets out of Git. Research contributions should identify their sources, dates and limitations. The repository also includes a [Postman collection](postman/README.md) for the local API.

## Documentation

| Topic | Start here |
| --- | --- |
| Project direction and decisions | [Context](docs/context.md) · [Decision log](docs/decisions.md) |
| Product and architecture | [Technical specification](docs/architecture/technical-spec.md) · [System design](docs/architecture/system-design.md) · [Database design](docs/architecture/database-design.md) |
| Implementation and handoff | [Development plan](docs/superpowers/plans/2026-11-14-first-development.md) · [Handoff guide](docs/handoff/README.md) |
| Data research | [Sources and APIs](docs/data-and-api.md) · [Source research](docs/research/source-foundation-plan.md) |
| Local features | [History](docs/api/history.md) · [Dossier](docs/api/dossier.md) · [Quality summary](docs/api/quality.md) |
| Design and reference material | [Design direction](docs/design-direction.md) · [Original blueprint](docs/reference/README.md) |
| Rights and third-party materials | [Licensing notes](docs/licenses.md) · [Third-party notices](THIRD_PARTY_NOTICES.md) |

Much of the project documentation is currently in Russian. The original blueprint is reference material; later recorded decisions and the current implementation should be read alongside it.

## License

A license for the project's own code and documentation has **not yet been selected**. A public repository alone does not grant a general license to reuse its contents. Third-party components and datasets retain their respective licenses; see [licensing notes](docs/licenses.md) and [third-party notices](THIRD_PARTY_NOTICES.md).
