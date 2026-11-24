# Build the report: join parts\*.html, in the order of their names, into handbook.html and print it to PDF with
# Edge or Chrome.
#     powershell -NoProfile -ExecutionPolicy Bypass -File docs\handbook\build.ps1
# Most pictures in shots\ come from scripts/record_demo.sh ("How this document was made", on the report's last page).
param([switch]$Draft)        # -Draft: build even if some pictures are missing
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$utf8 = New-Object Text.UTF8Encoding $false
$parts = Get-ChildItem (Join-Path $here "parts") -Filter *.html | Sort-Object Name |
    ForEach-Object { [IO.File]::ReadAllText($_.FullName, $utf8) }
$html = "<!doctype html>`n<html lang=`"en`"><head><meta charset=`"utf-8`">" +
    "<title>JustInTimeFarm2Home: system design report</title><link rel=`"stylesheet`" href=`"handbook.css`"></head><body>`n" +
    ($parts -join "`n") + "`n</body></html>`n"
$page = Join-Path $here "handbook.html"
[IO.File]::WriteAllText($page, $html, $utf8)

$missing = [regex]::Matches($html, 'src="(shots/[^"]+)"') | ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique |
    Where-Object { -not (Test-Path (Join-Path $here $_)) }
if ($missing -and -not $Draft) { throw "pictures the pages ask for are missing: $($missing -join ', ')" }

$browser = @("C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
             "C:\Program Files\Microsoft\Edge\Application\msedge.exe",
             "C:\Program Files\Google\Chrome\Application\chrome.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $browser) { throw "Edge or Chrome is needed to print the PDF" }
$pdf = Join-Path $here "JustInTimeFarm2Home-handbook.pdf"
if (Test-Path $pdf) { Remove-Item $pdf -Confirm:$false }
$scratch = Join-Path $env:TEMP ("handbook-" + [guid]::NewGuid().ToString("N"))
$url = "file:///" + ($page -replace "\\", "/")
Start-Process -FilePath $browser -Wait -ArgumentList @("--headless=new", "--disable-gpu", "--no-pdf-header-footer",
    "--user-data-dir=`"$scratch`"", "--print-to-pdf=`"$pdf`"", "`"$url`"")
Remove-Item $scratch -Recurse -Force -Confirm:$false -ErrorAction SilentlyContinue
if (-not (Test-Path $pdf)) { throw "the browser did not write $pdf" }
"{0}: {1:N1} MB" -f $pdf, ((Get-Item $pdf).Length / 1MB)
