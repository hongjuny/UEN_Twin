# Backlog (v1 and later)

- **Per-direction link modeling.** v0 sums both directions into one load per link. Internet traffic is mostly
  downstream, so the sum approximates real downstream utilization and overstates upstream.
- **Containerlab YAML / ns-3 scenario export.** Convert `data/topology/*.yaml` into higher-fidelity backend inputs
  (a future `export` command; removed from the v0 scope).
- Failure scenarios (Godzilla library), anomaly detection, agents, MCP tool server, evaluation metrics.
- Candidate first scenarios: the links listed under "links whose failure overloads other links" in
  `uetn-twin report --spof`.
- Parallel circuits as separate links with shared-conduit failure groups (see README, modeling assumptions).
