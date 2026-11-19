# uetn-twin (한국어)

UETN(유타 교육·원격의료 네트워크) 백본의 **플로우 수준 디지털 트윈**과 지도 기반 모니터링 대시보드입니다.
최종 목표는 이 네트워크 위에서 비정상 상황(링크 절단, PoP 정전, 수요 폭증, 오설정, DDoS 등)을 일으키고,
네트워크 관리 방법과 agentic AI를 평가하는 *in silico* 벤치마크를 만드는 것입니다. **v0은 백본 그래프, 평상시 트래픽,
모니터링 화면까지만 다룹니다.** 범위: `docs/WORKORDER_v0.md`. 영어 README는 [README.md](README.md)입니다.

정밀도는 의도적으로 낮습니다. 패킷이 아니라 노드 사이의 집계 트래픽(flow-level)으로 모델링합니다. 토폴로지는
UEN|UTN Infrastructure Map(2026-06-04)에서 읽었고 상당 부분이 **추정**입니다. 모든 노드·링크에
`confidence: map | inferred | assumed`가 붙어 있으며, 무엇이 추정이고 UETN에 무엇을 물어야 하는지는
[docs/DATA_PROVENANCE.md](docs/DATA_PROVENANCE.md), 용어는 [docs/GLOSSARY.md](docs/GLOSSARY.md)에 있습니다.

## 실행

```bash
# OneDrive 같은 동기화 폴더에 두었다면 가상환경을 밖에 두세요:
export UV_PROJECT_ENVIRONMENT=~/.venvs/uetn-twin

uv sync
uv run uetn-twin validate                 # 데이터 검증
uv run uetn-twin simulate --hours 24      # 평상시 하루 계산, outputs/run_*/snapshots.parquet
uv run uetn-twin run baseline_weekday    # 시나리오 배치 실행 (v1)
uv run uetn-twin live <시나리오> --speed 60   # 라이브 실행 (시뮬레이션 1분 = 실제 1초)
uv run streamlit run dashboard/app.py     # 대시보드 (사이드바에서 Replay / Live)
uv run uetn-twin report --spof            # 단일 장애점 보고서
uv run python scripts/screenshot.py       # 스크린샷 재현 (최초 1회 uv run playwright install chromium)
```

실행 결과는 `outputs/`에 저장됩니다. 다른 곳에 두려면 `UETN_TWIN_OUTPUTS=/경로`를 설정하세요(클라우드 동기화 폴더는 피하세요. 특히 라이브 모드).

## 전체 피크 수요 가정

**전체 피크 수요 가정: 223.3 Gbps (UETN 확인 필요).** (v1-platform 이전에는 의료 사이트를 200 Mbps로 가정해 258.6 Gbps였음, docs/DATA_PROVENANCE.md 참고)
노드 피크 수요 = 사이트 수 × 유형별 단위 수요 × 동시사용 계수(K-12 0.4, 의료 0.5, 고등교육 1.0)이며
`data/traffic_profile.yaml`에 있습니다. 계수는 결과에 맞춰 조정하지 않았습니다. UETN 실측이 오면 계수부터
보정합니다(민감도 표는 `docs/DATA_PROVENANCE.md`). 인터넷 출구(`slc-level3`)와 `internet_share`(0.7)도 같은 파일에서
바꿀 수 있고 결과에 큰 영향을 줍니다.

## 모델링 가정

- **병렬 회선은 링크 하나.** 지도의 이중선 가능 구간(usu-logan--wsu-ogden, slc--uvu-orem)은 링크 하나로 두고 용량을
  두 배로 잡지 않았습니다. 같은 도관의 병렬 회선은 함께 끊기므로, 복원력 분석에서는 하나로 보는 것이 보수적이고 타당합니다.
- **북부 단일 사슬.** 따라서 Logan–Ogden–Salt Lake에는 모델상 우회로가 없습니다(예: 와이오밍 경유 우회 존재 여부는
  UETN 질문 목록에 있음).
- **방향.** 링크 부하는 양방향 합산입니다. 인터넷 트래픽은 하향이 대부분이라 합산값은 하향 이용률에 가깝고 상향은
  과대 계상됩니다. 방향별 모델링은 `docs/BACKLOG.md`의 v1 항목입니다.
- **동부 링 관문.** `uvu-orem--uvu-wasatch`의 등급은 지도에서 읽히지 않아 40G로 추정했습니다(v0.1.1 수요 기준으로 20G면 피크 140%).
  UETN 확인 1순위입니다.
- **제공 부하(offered load).** v1-platform부터 링크 이용률은 그 링크를 지나려는 트래픽(제공 부하) ÷ 용량입니다. 100%를 넘으면 초과분을 각 흐름의 병목 링크에서 버리며, 하류 링크는 줄이지 않습니다.
- **사이트.** 지도에는 대표 지점만 있으므로, 지도에 안 나온 학군·차터·병원은 Salt Lake·Ogden·Orem PoP에 귀속해
  합계를 약 2,100개 부근(현재 2,244개)으로 맞췄습니다.

## 단일 장애점 보고서

`uetn-twin report --spof`는 링크 하나가 끊겼을 때 (1) 인터넷 출구에서 끊기는 노드 수, (2) 영향받는 학교·병원 수,
(3) 우회 후 이용률 1.0을 넘는 다른 링크 수(평일 피크 기준)를 보여줍니다. 출력 예시는 [README.md](README.md)에 있고,
세 번째 열이 0이 아닌 링크는 v1 시나리오의 1순위 후보입니다.

## 시나리오

시나리오는 평상시 하루(기본 프로파일) 위에 "상황"을 겹쳐 얹은 것입니다. 오버레이(특정 노드의 한 트래픽 클래스를 바꿈)와
이벤트(링크 끊김/복구)로 구성됩니다. 모든 값은 시뮬레이션이며 크기는 가정입니다.
`uetn-twin run <시나리오>`는 끝까지 빠르게 돌려 `outputs/`에 텔레메트리(Parquet)와 `run_meta.json`을 저장합니다.

| id | 상황 |
|---|---|
| `baseline_weekday` | 학기 중 평범한 평일. 지역별 흔들림과 짧은 버스트가 보임 |
| `semester_registration_monday` | 07:00 UVU·U of U 수강신청 오픈(U of U 세션 초과), 08:30부터 USU→DDC AI 학습 전송 30 Gbps |
| `weekend_dorm_streaming` | 토요일 저녁 기숙사 스트리밍. SLC(출구·캐시)에서 캠퍼스 방향으로 흐름 |
| `ai_training_campaign` | 평일 여러 대학의 대형 학습 전송. 400G 코어는 흡수하고 위험은 가장자리에 있음 |
| `statewide_k12_testing` | 수요일 오전 주 전체 온라인 평가. 모든 학군 노드가 함께 상승 |

## 라이브 모드

> 출력 폴더는 **OneDrive/Dropbox 밖**에 두세요(`export UETN_TWIN_OUTPUTS=~/uetn_outputs`). 클라우드 동기화 폴더에서는
> SQLite WAL이 `disk I/O error`로 실패합니다. 지도 윤곽은 `dashboard/static/`에서 제공하므로 인터넷 없이도 그려집니다.

```bash
uv run uetn-twin live semester_registration_monday --speed 60    # 시뮬레이션 1분 = 실제 1초
uv run streamlit run dashboard/app.py                            # 사이드바에서 "Live" 선택
```

시뮬레이터가 `telemetry.sqlite`(WAL)에 쓰는 동안 대시보드가 2.5초마다 읽어 갱신합니다. Ctrl-C로 멈추면 그때까지의
기록이 저장됩니다. 상단의 `SIMULATED` 배지는 항상 표시됩니다. 링크 색은 두 방향 중 큰 이용률, 노드 테두리 색은
서버 세션 부하입니다. `?run=<시나리오>&t=HH:MM&node=<id>`로 특정 화면을 바로 열 수 있습니다.

## 범위

v0에 없는 것: 장애 시나리오, 이상탐지, 에이전트, MCP 도구, 평가 지표, Containerlab/ns-3 백엔드, 외부(아이다호·와이오밍) 거점.
`docs/BACKLOG.md` 참고.
