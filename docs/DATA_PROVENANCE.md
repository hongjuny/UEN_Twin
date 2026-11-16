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
| richfield-dc--suu-cedar | backbone_400g | inferred | Southern merge point unclear; 대안: richfield-dc to tdc-stgeorge (not created) |
| tdc-stgeorge--utahtech-stgeorge | backbone_400g | inferred |  |
| uvu-orem--uvu-wasatch | backbone_40g | inferred | 지도상 등급 불명. 대안: 20G(원래 가정, 평상시 피크 140%로 비현실적) / 400G. 하류 20G 링 2가닥을 공급하는 상류 링크이므로 40G 이상으로 추정. UETN 확인 1순위 |
| uvu-wasatch--usu-eastern | backbone_20g | inferred | Map ambiguous whether the Price branch hangs off uvu-wasatch; 대안: attaches via uvu-orem |
| usu-eastern--moab | backbone_20g | inferred | Purple line from Price to Moab; map ambiguous between uvu-wasatch and usu-eastern |
| slc-uofu--park-city | ethernet_10g | inferred | 대안: backbone_20g |
| ubtc-vernal--usu-vernal | ethernet_10g | inferred | Same city; no line printed |
| suu-cedar--swtc-cedar | ethernet_10g | inferred | Same city; no line printed |
| tdc-stgeorge--dixie-tc | ethernet_10g | inferred | Same city; no line printed |
| wsu-ogden--davis-tc | ethernet_10g | inferred | Not in work order table; attached to nearest PoP so the node is not isolated. 대안: attaches at Salt Lake |
| wsu-ogden--ogden-weber-tc | ethernet_10g | inferred | Not in work order table; same city as wsu-ogden |
| uvu-orem--mountainland-tc | ethernet_10g | inferred | Not in work order table; nearest PoP. 대안: attaches at Salt Lake |
| richfield-dc--snow-richfield | ethernet_10g | inferred | Not in work order table; same city as richfield-dc |
| cache-sd--usu-logan | ethernet_10g | inferred | Parent PoP inferred from where the line ends |
| logan-sd--usu-logan | ethernet_10g | inferred | Parent PoP inferred from where the line ends |
| boxelder-sd--usu-logan | ethernet_10g | inferred | Parent PoP inferred from where the line ends |
| btc-brigham--usu-logan | ethernet_10g | inferred | Parent PoP inferred from where the line ends |
| rich-sd--usu-logan | ethernet_10g | inferred | Parent PoP inferred from where the line ends |
| ogden-sd--wsu-ogden | ethernet_10g | inferred | Parent PoP inferred from where the line ends |
| weber-sd--wsu-ogden | ethernet_10g | inferred | Parent PoP inferred from where the line ends |
| morgan-sd--wsu-ogden | ethernet_10g | inferred | Parent PoP inferred from where the line ends |
| davis-sd--wsu-ogden | ethernet_10g | inferred | wsu-ogden chosen; 대안: slc (Salt Lake side) |
| nsummit-sd--park-city | ethernet_10g | inferred | Parent PoP inferred from where the line ends |
| ssummit-sd--park-city | ethernet_10g | inferred | Parent PoP inferred from where the line ends |
| wasatch-sd--uvu-wasatch | ethernet_10g | inferred | Parent PoP inferred from where the line ends |
| alpine-sd--uvu-orem | ethernet_10g | inferred | Parent PoP inferred from where the line ends |
| provo-sd--uvu-orem | ethernet_10g | inferred | Parent PoP inferred from where the line ends |
| nebo-sd--uvu-orem | ethernet_10g | inferred | Parent PoP inferred from where the line ends |
| juab-sd--uvu-orem | ethernet_10g | inferred | Parent PoP inferred from where the line ends |
| tintic-sd--uvu-orem | ethernet_10g | inferred | Parent PoP inferred from where the line ends |
| nsanpete-sd--snow-ephraim | ethernet_10g | inferred | snow-ephraim chosen; 대안: uvu-orem |
| snow-ephraim--richfield-dc | ethernet_10g | inferred | Parent PoP inferred from where the line ends |
| ssanpete-sd--snow-ephraim | ethernet_10g | inferred | Parent PoP inferred from where the line ends |
| sevier-sd--richfield-dc | ethernet_10g | inferred | Parent PoP inferred from where the line ends |
| piute-sd--richfield-dc | ethernet_10g | inferred | Parent PoP inferred from where the line ends |
| wayne-sd--richfield-dc | ethernet_10g | inferred | Parent PoP inferred from where the line ends |
| garfield-sd--richfield-dc | ethernet_10g | inferred | richfield-dc chosen; 대안: suu-cedar |
| beaver-sd--suu-cedar | ethernet_10g | inferred | suu-cedar chosen; 대안: richfield-dc |
| millard-sd--slc-slcc | ethernet_10g | inferred | slc-slcc chosen (via western 400G trunk; latency left as the distance-derived value); 대안: other attach point on the southbound trunk |
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
| usu-logan--wsu-ogden | 지도상 병렬 2회선 가능성; modeled as one link, capacity not doubled |
| slc-ddc--uvu-orem | 지도상 병렬 2회선 가능성; modeled as one link, capacity not doubled. Salt Lake end assumed slc-ddc |
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

## Changes to assumptions

- **v1-platform (2026-11-16): healthcare unit demand 200 -> 100 Mbps per site.** With the v1 traffic classes, healthcare demand had been classified entirely as telehealth video and came out as the largest class (70.5 Gbps), which an operator would find implausible. Most hospital and clinic traffic is electronic health records, cloud and web; many sites are small clinics. Healthcare demand is now split 30% telehealth / 70% general_internet (data/traffic/classes.yaml) and the unit demand was halved. Total v0 peak demand assumption: 258.6 -> 223.3 Gbps. The concurrency factor (0.5) is unchanged.
- **v1-platform: higher_ed_general renamed general_internet** and also used by K-12 (10%) and healthcare (70%).

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
