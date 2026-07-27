# UE5 Greybox Build Specification

## Level

Map: `L_WangSheng_FrontHall_VS`

Required actors and stable IDs:

- `location.front_hall` — 8m × 6m playable hall;
- `object.front_door` — closed, collision-enabled, never mutated by the model;
- `actor.qingyan` — Character + AIController;
- `actor.xiaoman` — scripted voice/text source outside the reachable area;
- `object.paper_crane` — interactable evidence object;
- `point.qingyan_idle`;
- `point.front_door_listen`;
- `point.player_report`;
- `ui.liuming_notebook`.

## Required interactions

- player movement and interaction trace;
- listen at door;
- inspect paper crane;
- ask Qingyan;
- open notebook and confirm one Night-1 record;
- review Day-2 manifestation;
- inspect archive;
- inspect body continuity marker;
- ask Xiaoman for consent;
- confirm one Day-3 outcome;
- save and load.

## NPC movement

The first slice does not require autonomous long-horizon planning. Qingyan may execute deterministic StateTree/Blueprint tasks:

- move to listen point;
- face door;
- wait for timer;
- return to report point;
- display structured report.

Every task returns one of `SUCCESS`, `NO_PATH`, `TIMEOUT`, `INTERRUPTED` with `action_id`.

## Visual consequence minimum

Each Night-1 branch must change at least two player-visible signals among:

- paper crane persistence;
- a name strip/mark near the door;
- Qingyan's explicit dialogue state;
- an empty temporary place in the front hall;
- lighting or prop arrangement indicating increased/decreased presence.

The signals must come from `day2_manifestation`; they may not be random set dressing.
