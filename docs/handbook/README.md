# Handbook

`JustInTimeFarm2Home-handbook.pdf` is the document: what is built, how a hub works, what was measured, how to demo
it, and what is left. `farm2home-demo.mp4` is the recording it refers to (3 min 29 s, no sound).

| File | What it is |
| --- | --- |
| `parts/*.html`, `handbook.css` | The pages. Edit these. |
| `shots/*.png` | Screenshots taken by `scripts/record_demo.sh` |
| `build.ps1` | Joins the parts and prints the PDF with Edge or Chrome |

To remake the pictures and the video, run `scripts/record_demo.sh` on a machine with Docker, Node and Playwright
(the project's dev server is set up for it), copy `shots/` and the video here, then:

```powershell
powershell -ExecutionPolicy Bypass -File docs\handbook\build.ps1
```

The numbers in section 7 are typed in by hand from the runs named beside them; rerun those and update the page.
