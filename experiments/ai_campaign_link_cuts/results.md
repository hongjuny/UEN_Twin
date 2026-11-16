# Experiment: link cuts during the AI training campaign (SIMULATED)

Not a demo scenario. Background traffic and seed are those of `ai_training_campaign`; one link is down
from 09:00 to 11:00. Utilization is offered load (30 s averages); dropped traffic is the total over
the run in gigabits; unreachable sites is the largest number of schools/clinics cut off at once.

| variant | most utilized direction | directions above 100% (peak, time above) | dropped (Gb) | unreachable sites |
|---|---|---|---|---|
| no cut (ai_training_campaign) | tdc-stgeorge->kane-sd 46% at 10:43 | none | 0 | 0 |
| uvu-orem--richfield-dc down 09:00-11:00 | tdc-stgeorge->kane-sd 46% at 10:43 | none | 0 | 0 |
| slc-slcc--suu-cedar down 09:00-11:00 | tdc-stgeorge->kane-sd 46% at 10:43 | none | 0 | 0 |
| suu-cedar--tdc-stgeorge down 09:00-11:00 | suu-cedar->iron-sd 121% at 09:54 | suu-cedar->iron-sd peak 121%, 120 min | 7,089 | 0 |
| uvu-wasatch--usu-eastern down 09:00-11:00 | uvu-wasatch->ubtc-roosevelt 69% at 09:00 | none | 0 | 0 |
