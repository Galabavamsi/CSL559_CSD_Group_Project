# Handbook

`JustInTimeFarm2Home-handbook.pdf` is the report on the system's design, as of 24 November 2026: where the project
stands, the design and the reason for each decision, the system in pictures by role, what was measured, what is
not built, and how to try the app on a phone.

`farm2home-demo.mp4` (3 min 31 s, no sound) is the recording made on 23 November. It predates delivery, orders on
the server and the rescue price, and has not been recorded again. The report says so where it mentions it.

| File | What it is |
| --- | --- |
| `parts/*.html`, `handbook.css` | The pages. Edit these. They are joined in the order of their names. |
| `shots/*.png` | The pictures. Most are saved by `scripts/record_demo.sh`; the report's last page says which are not. |
| `build.ps1` | Joins the parts and prints the PDF with Edge or Chrome |

| Part | Section of the report |
| --- | --- |
| `1-intro.html` | Cover; 1, where it stands |
| `2-flow.html` | 2, system design: the flow from farm to door, and inside a hub |
| `3-architecture.html` | 2, system design: the software, and what runs on AWS |
| `4-decisions.html` | 2, system design: the decisions with their reasons, and three rules that were wrong |
| `5-pictures.html` | 3, the system in pictures: customer, farmer, hub, hub manager, delivery agent |
| `6-metrics.html` | 4, metrics, each with its date and method |
| `7-next.html` | 5, what is not built or not checked, and what comes next |
| `8-try.html` | 6, how to try the app on a phone |
| `9-sources.html` | Sources and credits |

To remake the pictures, run `scripts/record_demo.sh` on a machine with Docker, Node and Playwright (the project's
dev server is set up for it), copy `shots/` here, then:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File docs\handbook\build.ps1
```

Then read every page of the PDF: a paragraph that grows by a line can push a block onto the next page.

The numbers in section 4 are typed in by hand from the runs named beside them; rerun those and update the page.
The design decisions in section 2 are a short version of `docs/DESIGN.md`; change that first.
