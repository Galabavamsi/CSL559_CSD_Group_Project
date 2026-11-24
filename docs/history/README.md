# History: the group project

These documents are from the university group project (CSL559) this repository began as: a dark-store prototype
of the micro-warehousing part of a quick-commerce app, built by four students, each owning one area. They are kept
as the record of that work. **They are not current:** the project has since been rebuilt into JustInTimeFarm2Home,
and the current documents are [`../HANDOVER.md`](../HANDOVER.md), [`../DESIGN.md`](../DESIGN.md) and
[`../ARCHITECTURE.md`](../ARCHITECTURE.md).

The code as the group left it is the git tag `darkstore-final`; the tags `v1.0` to `v1.6` are its releases.

| File | What it was |
| --- | --- |
| [`TEAM_PLAN.md`](TEAM_PLAN.md) | Who owned what, the milestones, and how the four parts fitted together |
| [`guide-member-1-inventory.md`](guide-member-1-inventory.md) | Member 1: inventory and stock integrity |
| [`guide-member-2-fulfilment.md`](guide-member-2-fulfilment.md) | Member 2: order fulfilment (pick, pack, hand-off) |
| [`guide-member-3-supply.md`](guide-member-3-supply.md) | Member 3: supply (forecasting, replenishment, inbound, slotting) |
| [`guide-member-4-platform.md`](guide-member-4-platform.md) | Member 4: platform, store network and screens |
| [`report/`](report/) | Each member's section of the group's report, in LaTeX |
| [`DEPLOY_AWS.md`](DEPLOY_AWS.md) | The first way of running it on AWS: one EC2 machine with Docker. Replaced by [`../../infra/`](../../infra/README.md) |

Many of the guides' task numbers (for example "task 1.6") still appear in the code's comments and in the scripts'
descriptions; these files are where those numbers are explained.
