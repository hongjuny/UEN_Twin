# Glossary

Network terms used in the code and documents, in plain language.

| Term | Meaning |
|---|---|
| **UEN / UTN / UETN** | Utah Education Network / Utah Telehealth Network / Utah Education and Telehealth Network: the state network that connects schools, colleges and healthcare sites. |
| **Backbone** | The high-capacity core links that carry traffic between regions (here: 400G/100G/40G/20G lines on the map). |
| **PoP (point of presence)** | A site where the network has equipment and where lines meet. In this model each core node is a PoP. |
| **Tier** | Role of a node: `core` (backbone PoP), `distribution` (regional aggregation point, e.g. a school-district office), `external` (sites outside Utah, hidden by default). |
| **Core / distribution / access layer** | The usual three levels of a network. Core = backbone; distribution = regional collection points that connect to a core PoP; access = the individual schools and clinics, which are *not* modeled as routers but as demand totals (`sites.yaml`). |
| **Router / node** | A device (or site) that forwards traffic. Each node in `nodes.yaml` is treated as one router. |
| **Link** | A connection between two nodes. Undirected in v0. |
| **Link class** | The grade of a link taken from the map legend: `backbone_400g`, `backbone_100g`, `backbone_40g`, `backbone_20g`, `ethernet_10g`, `ethernet_1g`, `microwave_200m`, `ethernet_sub1g`. It sets the default capacity. |
| **Gbps / Mbps** | Gigabits / megabits per second: the speed of a link or the volume of traffic. 1 Gbps = 1,000 Mbps. |
| **Capacity** | The most traffic a link can carry, in Gbps. |
| **Load** | Traffic currently crossing a link, in Gbps. |
| **Utilization** | load / capacity. 1.0 (100%) means the link is full; above 1.0 means more traffic than it can carry. |
| **Latency** | Delay for traffic to cross a link, in milliseconds. Here it is estimated from distance (about 5 microseconds per km of fiber, times 1.4 for route detours). |
| **Microwave link** | A wireless point-to-point link (here 200 Mbps). |
| **Shortest path routing** | Traffic takes the path with the lowest total delay. |
| **ECMP (equal-cost multi-path)** | If several paths have exactly the same delay, traffic is split equally among them. |
| **Reroute** | Traffic taking a different path after a link goes down. |
| **Internet exit** | The node where traffic to and from the internet enters the network (assumed `slc-level3`). `internet_share` is the fraction of demand sent there. |
| **Level 3** | A commercial network carrier. Its Salt Lake site is assumed to be the internet exit. |
| **Gateway link** | A link that all traffic of a region has to cross (here `uvu-orem--uvu-wasatch` for the eastern ring). |
| **Ring** | A chain of links that loops back (the eastern 20G ring). The model has no second connection back, so it is a chain. |
| **SPOF (single point of failure)** | A link or node whose failure alone cuts off part of the network. `uetn-twin report --spof` lists them. |
| **Flow-level model** | Traffic is simulated as aggregate volumes between node pairs, not as individual packets. Much cheaper, less detailed. |
| **Demand matrix** | A table of how much traffic flows between each pair of nodes. |
| **Gravity model** | A way to build a demand matrix: traffic between two nodes is proportional to the product of their sizes (here, 30% of demand; 70% goes to the internet exit). |
| **Peak demand** | Traffic a node would generate at the busiest time. |
| **Concurrency factor** | Share of users active at the same time at the daily peak (K-12 0.4, healthcare 0.5, higher-ed 1.0). The main knob for calibrating against real measurements. |
| **Hourly profile** | Multipliers by hour of day applied to peak demand (weekday during the school term, weekend, school break). |
| **K-12** | Kindergarten through 12th grade (schools). |
| **TC / SD** | Technical college / school district (suffixes in node names). |
| **Snapshot** | The state of every link at one moment (up/down, load, utilization). |
| **Parquet** | A compact column-based file format for tables; `snapshots.parquet` holds simulation results. |
| **IGP (OSPF, IS-IS)** | Protocols routers use to find paths inside one network. Not modeled; asked about in the UETN questions. |
| **BGP** | The protocol that exchanges routes between different networks (e.g. with the internet). Not modeled. |
| **MPLS / Segment Routing** | Techniques that steer traffic along chosen paths. Not modeled. |
| **Traffic engineering** | Deliberately steering traffic away from the shortest path to balance load. Not modeled. |
| **Containerlab / ns-3** | Higher-fidelity network emulators/simulators. Possible future backends; not used in v0. |
| **gNMI** | A standard interface for reading and changing router state; a future Containerlab backend would use it. |
| **Confidence (`map` / `inferred` / `assumed`)** | How a data value was obtained: read from the map, reasonably deduced from it, or assumed because the map does not show it. |
