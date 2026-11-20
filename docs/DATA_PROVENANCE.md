# Data provenance

How each value in `data/topology/` was obtained. Source: UEN|UTN Infrastructure Map (2026-06-04), transcribed by hand into `docs/WORKORDER_v0.md` section 5. **Most values are estimates.** Generated from the YAML files; regenerate rather than hand-edit the tables.

## Global assumptions

- All coordinates are city centers (assumed), for every node.
- All link latencies are derived from distance using `data/physics.yaml` (5 us/km, detour 1.4, floor 0.05 ms), all assumed.
- All site counts and demand values in `sites.yaml` are assumed (K-12 100 Mbps/school, healthcare 100 Mbps/site, higher-ed campus 2-10 Gbps).
- Core-node site rows (esp. the Salt Lake PoPs, wsu-ogden, uvu-orem) stand for Wasatch Front districts, charters and clinics that the map does not print individually. The work order's 8-40 K-12 sites per distribution node alone sums to ~580, far below the ~2,100 locations the map reports, so the remainder was placed on core nodes.
- Parallel double lines on the map (usu-logan--wsu-ogden, slc--uvu-orem) are modeled as one link; capacity not doubled.
- Link-level `confidence` describes where the link was read from; it is `inferred` or `assumed` for anything not drawn explicitly.
- No external nodes (Idaho/Wyoming telehealth) are in the data yet; the grey circles on the map were not counted.

## Nodes with confidence != map

| id | confidence | note |
|---|---|---|
| slc-level3 | inferred | Assumed to be the commercial-carrier / internet exit (workorder section 6) |
| uvu-wasatch | inferred | Location approximated as Heber City; western end of the eastern 20G ring |
| tdc-stgeorge | inferred | Printed 'near St. George'; placed at St. George city center |
| sanjuan-media | inferred | Printed near Blanding/Monticello; placed at Monticello |
| mountainland-tc | inferred | Printed near Lehi/Orem; placed at Lehi |
| park-city | inferred | Assumed entry point of the eastern Summit County area |

## Links with confidence != map

| link | class | confidence | note |
|---|---|---|---|
| wsu-ogden--slc-ddc | backbone_400g | inferred | Map does not show which Salt Lake PoP it reaches; slc-ddc assumed |
| slc-level3--slc-slcc | backbone_400g | assumed | Full mesh among the four Salt Lake PoPs is an assumption |
| slc-level3--slc-ddc | backbone_400g | assumed | Full mesh among the four Salt Lake PoPs is an assumption |
| slc-level3--slc-uofu | backbone_400g | assumed | Full mesh among the four Salt Lake PoPs is an assumption |
| slc-slcc--slc-ddc | backbone_400g | assumed | Full mesh among the four Salt Lake PoPs is an assumption |
| slc-slcc--slc-uofu | backbone_400g | assumed | Full mesh among the four Salt Lake PoPs is an assumption |
| slc-ddc--slc-uofu | backbone_400g | assumed | Full mesh among the four Salt Lake PoPs is an assumption |
| uvu-orem--richfield-dc | backbone_400g | inferred | Southbound trunk 1 |
| slc-slcc--suu-cedar | backbone_400g | inferred | Southbound trunk 2 (western route, probably via Millard/Beaver) |
| richfield-dc--suu-cedar | backbone_400g | inferred | Southern merge point unclear; alternative: richfield-dc to tdc-stgeorge (not created) |
| tdc-stgeorge--utahtech-stgeorge | backbone_400g | inferred |  |
| uvu-orem--uvu-wasatch | backbone_40g | inferred | Map grade unclear. Alternatives: 20G (original assumption; unrealistic at 140% of normal peak) / 400G. Upstream link feeding two downstream 20G rings, so estimated at 40G or more. Top priority to confirm with UETN |
| uvu-wasatch--usu-eastern | backbone_20g | inferred | Map ambiguous whether the Price branch hangs off uvu-wasatch; alternative: attaches via uvu-orem |
| usu-eastern--moab | backbone_20g | inferred | Purple line from Price to Moab; map ambiguous between uvu-wasatch and usu-eastern |
| slc-uofu--park-city | ethernet_10g | inferred | alternative: backbone_20g |
| ubtc-vernal--usu-vernal | ethernet_10g | inferred | Same city; no line printed |
| suu-cedar--swtc-cedar | ethernet_10g | inferred | Same city; no line printed |
| tdc-stgeorge--dixie-tc | ethernet_10g | inferred | Same city; no line printed |
| wsu-ogden--davis-tc | ethernet_10g | inferred | Not in work order table; attached to nearest PoP so the node is not isolated. alternative: attaches at Salt Lake |
| wsu-ogden--ogden-weber-tc | ethernet_10g | inferred | Not in work order table; same city as wsu-ogden |
| uvu-orem--mountainland-tc | ethernet_10g | inferred | Not in work order table; nearest PoP. alternative: attaches at Salt Lake |
| richfield-dc--snow-richfield | ethernet_10g | inferred | Not in work order table; same city as richfield-dc |
| cache-sd--usu-logan | ethernet_10g | inferred | Parent PoP inferred from where the line ends |
| logan-sd--usu-logan | ethernet_10g | inferred | Parent PoP inferred from where the line ends |
| boxelder-sd--usu-logan | ethernet_10g | inferred | Parent PoP inferred from where the line ends |
| btc-brigham--usu-logan | ethernet_10g | inferred | Parent PoP inferred from where the line ends |
| rich-sd--usu-logan | ethernet_10g | inferred | Parent PoP inferred from where the line ends |
| ogden-sd--wsu-ogden | ethernet_10g | inferred | Parent PoP inferred from where the line ends |
| weber-sd--wsu-ogden | ethernet_10g | inferred | Parent PoP inferred from where the line ends |
| morgan-sd--wsu-ogden | ethernet_10g | inferred | Parent PoP inferred from where the line ends |
| davis-sd--wsu-ogden | ethernet_10g | inferred | wsu-ogden chosen; alternative: slc (Salt Lake side) |
| nsummit-sd--park-city | ethernet_10g | inferred | Parent PoP inferred from where the line ends |
| ssummit-sd--park-city | ethernet_10g | inferred | Parent PoP inferred from where the line ends |
| wasatch-sd--uvu-wasatch | ethernet_10g | inferred | Parent PoP inferred from where the line ends |
| alpine-sd--uvu-orem | ethernet_10g | inferred | Parent PoP inferred from where the line ends |
| provo-sd--uvu-orem | ethernet_10g | inferred | Parent PoP inferred from where the line ends |
| nebo-sd--uvu-orem | ethernet_10g | inferred | Parent PoP inferred from where the line ends |
| juab-sd--uvu-orem | ethernet_10g | inferred | Parent PoP inferred from where the line ends |
| tintic-sd--uvu-orem | ethernet_10g | inferred | Parent PoP inferred from where the line ends |
| nsanpete-sd--snow-ephraim | ethernet_10g | inferred | snow-ephraim chosen; alternative: uvu-orem |
| snow-ephraim--richfield-dc | ethernet_10g | inferred | Parent PoP inferred from where the line ends |
| ssanpete-sd--snow-ephraim | ethernet_10g | inferred | Parent PoP inferred from where the line ends |
| sevier-sd--richfield-dc | ethernet_10g | inferred | Parent PoP inferred from where the line ends |
| piute-sd--richfield-dc | ethernet_10g | inferred | Parent PoP inferred from where the line ends |
| wayne-sd--richfield-dc | ethernet_10g | inferred | Parent PoP inferred from where the line ends |
| garfield-sd--richfield-dc | ethernet_10g | inferred | richfield-dc chosen; alternative: suu-cedar |
| beaver-sd--suu-cedar | ethernet_10g | inferred | suu-cedar chosen; alternative: richfield-dc |
| millard-sd--slc-slcc | ethernet_10g | inferred | slc-slcc chosen (via western 400G trunk; latency left as the distance-derived value); alternative: other attach point on the southbound trunk |
| iron-sd--suu-cedar | ethernet_10g | inferred | Parent PoP inferred from where the line ends |
| washington-sd--tdc-stgeorge | ethernet_10g | inferred | Parent PoP inferred from where the line ends |
| kane-sd--tdc-stgeorge | ethernet_1g | inferred | 1G, single path |
| duchesne-sd--ubtc-roosevelt | ethernet_10g | inferred | Parent PoP inferred from where the line ends |
| uintah-sd--ubtc-vernal | ethernet_10g | inferred | Parent PoP inferred from where the line ends |
| daggett-sd--ubtc-vernal | ethernet_10g | inferred | Parent PoP inferred from where the line ends |
| carbon-sd--usu-eastern | ethernet_10g | inferred | Parent PoP inferred from where the line ends |
| emery-sd--usu-eastern | ethernet_10g | inferred | Parent PoP inferred from where the line ends |
| grand-sd--moab | ethernet_10g | inferred | Parent PoP inferred from where the line ends |
| sanjuan-sd--sanjuan-media | ethernet_10g | inferred | Parent PoP inferred from where the line ends |

## Links read from the map but with an assumed endpoint or caveat

| link | note |
|---|---|
| usu-logan--wsu-ogden | map suggests a possible parallel double circuit; modeled as one link, capacity not doubled |
| slc-ddc--uvu-orem | map suggests a possible parallel double circuit; modeled as one link, capacity not doubled. Salt Lake end assumed slc-ddc |
| suu-cedar--tdc-stgeorge | Red line |
| iron-sd--tdc-stgeorge | Red line; iron-sd is also attached to suu-cedar |
| uvu-wasatch--ubtc-roosevelt | Purple line via Duchesne |
| ubtc-vernal--moab | Eastern edge, southbound |
| slc-slcc--wendover | Single path; Salt Lake end assumed slc-slcc |
| slc-slcc--tooele-sd | Salt Lake end assumed slc-slcc |
| slc-slcc--tooele-tc | Salt Lake end assumed slc-slcc |

## Site totals (all assumed)

K-12 1502, higher-ed 37, healthcare 705, total 2244.


## Concurrency-factor sensitivity

Peak utilization of the eastern gateway (uvu-orem--uvu-wasatch) over a weekday, by concurrency factors and gateway class. This is a starting point for calibrating against UETN measurements. Defaults (K-12 0.4, healthcare 0.5, higher-ed 1.0) are NOT tuned to results.

| concurrency (k12 / healthcare / higher-ed) | gateway 20G | gateway 40G (current) | gateway 400G | links over 100% at 40G |
|---|---|---|---|---|
| 0.4 / 0.5 / 1.0 (default) | 116% | 58% | 6% | 0 |
| 0.4 / 0.5 / 0.8 | 101% | 51% | 5% | 0 |
| 0.4 / 0.5 / 0.6 | 87% | 43% | 4% | 0 |
| 0.4 / 0.5 / 0.5 | 80% | 40% | 4% | 0 |
| 0.4 / 0.5 / 0.4 | 73% | 36% | 4% | 0 |
| all x0.7 (0.28 / 0.35 / 0.7) | 81% | 41% | 4% | 0 |
| all x0.5 (0.2 / 0.25 / 0.5) | 58% | 29% | 3% | 0 |

With the gateway at 20G the default factors gave 140%. Under the defaults every other link peaks at 54% or less.

## v1-platform traffic model (all assumed)

Parameters live in data/traffic/classes.yaml, data/regions.yaml and data/scenarios/*.yaml.

- **Six traffic classes** (k12_instruction, general_internet, streaming, telehealth, research_bulk, transactional) split each site type's v0 peak demand: K-12 80/10/10 (instruction/general/streaming); higher-ed 50/30/15/5 (general/streaming/research/transactional); healthcare 30/70 (telehealth/general). Each class has its own hourly curve.
- **Endpoints:** internet exit slc-level3; research (Internet2) exit also slc-level3; CDN cache slc-ddc serving 60% of streaming; telehealth hub slc-uofu; half of transactional clients come from outside the network via the exit.
- **Direction:** share of each class flowing toward the node that owns the demand (K-12 0.9, general 0.8, streaming 0.95, telehealth and research 0.5, transactional requests 0.3). Link capacity is the same in both directions (full duplex).
- **Server sessions** count only the server side of transactional traffic (sessions_per_gbps 50,000); telehealth sessions are recorded separately without a capacity check. Session capacity by node kind: university 200,000; technical college 25,000; datacenter 50,000; school district 100,000; PoP 2,000,000.
- **Stochastic layers:** Ornstein-Uhlenbeck regional wander (time constant 30-120 min, sigma 10-15%, regional correlation 0.6; a region is a core PoP with the distribution nodes nearest to it); Poisson bursts (lognormal size relative to the node's class peak, 1-10 min); fast AR(1) noise (coefficient 0.7) with sigma = 2% x sqrt(10 Gbps / volume) clipped to 1-15% (for transactional the reference is 10,000 sessions).
- **Transactional schedule:** half of transactional bursts fall in class-change windows (:50 to :05 around each hour, 08:00-17:00); the transactional hourly level never drops below 5% of its peak (servers are never empty at night).
- **Drop and latency:** traffic above capacity is dropped at each flow's bottleneck link; utilization is offered load; latency uses a rough M/M/1-like factor and is indicative only.
- **Scenario sizes** (registration peak_x 25, research transfers 15-60 Gbps, streaming x1.8, K-12 testing x1.6) are demonstration assumptions.

## Changes to assumptions

- **v1-platform (2026-11-16): healthcare unit demand 200 -> 100 Mbps per site.** With the v1 traffic classes, healthcare demand had been classified entirely as telehealth video and came out as the largest class (70.5 Gbps), which an operator would find implausible. Most hospital and clinic traffic is electronic health records, cloud and web; many sites are small clinics. Healthcare demand is now split 30% telehealth / 70% general_internet (data/traffic/classes.yaml) and the unit demand was halved. Total v0 peak demand assumption: 258.6 -> 223.3 Gbps. The concurrency factor (0.5) is unchanged.
- **v1-platform: higher_ed_general renamed general_internet** and also used by K-12 (10%) and healthcare (70%).
- **v1-platform stage 2 review: technical-college session capacity 20,000 -> 25,000.** With bursts and noise the 99th percentile of 30 s server-session averages in a 24 h baseline_weekday run reached 44% at tooele-tc; the target for a normal day is <= 40% everywhere. After the change the highest p99 is 37% (slc-uofu, university) and 35% (tooele-tc). University and datacenter capacities were already within the target and are unchanged.

## Questions for UETN

1. Class of the uvu-orem--uvu-wasatch link (map unreadable; 40G inferred, 20G or 400G possible). It feeds both 20G ring branches, so this is the first thing to confirm.
2. Interconnection of the four Salt Lake PoPs (Level 3, SLCC, DDC, U of U) and the location of the internet exit.
3. Exact path of the two southbound 400G trunks and where they merge at Richfield, SUU and TDC (is there a Richfield-TDC link?).
4. Exact structure of the eastern 20G ring (UVU Wasatch - Roosevelt - Vernal - Moab - San Juan) and the Price (USU Eastern) connection.
5. Is there an alternate path for the northern chain (Logan - Ogden - Salt Lake), e.g. via Wyoming? Are usu-logan--wsu-ogden and slc--uvu-orem really parallel circuits, in the same conduit, and what is the aggregate capacity?
6. Equipment count and redundancy per PoP (one router or two).
7. Routing design: IGP (OSPF/IS-IS), BGP scope, MPLS/Segment Routing, traffic-engineering policy.
8. Anonymized link utilization time series (5-minute, 1-2 weeks) and number of sites behind each PoP.
9. Abnormal events seen in the last 2-3 years: type, scope, recovery time.
10. Parent PoP for ambiguous districts: davis-sd, nsanpete-sd, garfield-sd, beaver-sd, millard-sd (see notes above).
11. Attach points of davis-tc, ogden-weber-tc, mountainland-tc, snow-richfield (not in the work order's link table; added to avoid isolated nodes).
12. Where do iron-sd's two connections (suu-cedar 10G, tdc 100G) actually terminate?
13. How many Idaho/Wyoming telehealth sites does UETN serve, and where do they connect?
14. What is the real share of telehealth (video and records) in UETN traffic? The model has 5.6% at a weekday 10:00.
15. Where are CDN cache servers (Netflix, Google, Akamai, ...) inside the network, and what share of streaming do they serve? The model assumes one cache at DDC serving 60%.
16. Does residence-hall (dorm) traffic cross UETN, or do campuses use a separate commercial provider for it?
17. Where does research traffic leave for Internet2, and is it the same point as the commodity internet exit?
18. What concurrent-session capacity do campus registration/login systems and firewalls have (per campus)?
