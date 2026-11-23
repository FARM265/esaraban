# Download Bootstrap 5 and the Sarabun font into static/vendor.
# The system never loads these from a CDN at runtime, so it works on an internal network.
# (This file is ASCII-only on purpose: Windows PowerShell 5.1 misreads UTF-8 without BOM.)
#
# Run from the project folder in the VS Code terminal:
#   powershell -ExecutionPolicy Bypass -File scripts\download_vendor.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$vendor = Join-Path $root "static\vendor"

$bootstrapVersion = "5.3.3"
$pdfjsVersion = "4.10.38"
$files = @(
    @{ Url = "https://cdn.jsdelivr.net/npm/bootstrap@$bootstrapVersion/dist/css/bootstrap.min.css"; Out = "bootstrap\bootstrap.min.css" },
    @{ Url = "https://cdn.jsdelivr.net/npm/bootstrap@$bootstrapVersion/dist/js/bootstrap.bundle.min.js"; Out = "bootstrap\bootstrap.bundle.min.js" },
    @{ Url = "https://cdn.jsdelivr.net/npm/pdfjs-dist@$pdfjsVersion/build/pdf.min.mjs"; Out = "pdfjs\pdf.min.js" },
    @{ Url = "https://cdn.jsdelivr.net/npm/pdfjs-dist@$pdfjsVersion/build/pdf.worker.min.mjs"; Out = "pdfjs\pdf.worker.min.js" },
    @{ Url = "https://cdn.jsdelivr.net/gh/google/fonts@2796410152d4f9524b68ed46e69c1b60f8e0f7c3/ofl/sarabun/Sarabun-Regular.ttf"; Out = "sarabun\Sarabun-Regular.ttf" },
    @{ Url = "https://cdn.jsdelivr.net/gh/google/fonts@2796410152d4f9524b68ed46e69c1b60f8e0f7c3/ofl/sarabun/Sarabun-Bold.ttf"; Out = "sarabun\Sarabun-Bold.ttf" }
)
foreach ($weight in 400, 500, 600, 700) {
    foreach ($subset in "thai", "latin") {
        $name = "sarabun-$subset-$weight-normal.woff2"
        $files += @{ Url = "https://cdn.jsdelivr.net/npm/@fontsource/sarabun@5/files/$name"; Out = "sarabun\$name" }
    }
}

$failed = 0
foreach ($f in $files) {
    $dest = Join-Path $vendor $f.Out
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dest) | Out-Null
    try {
        Invoke-WebRequest -Uri $f.Url -OutFile $dest -UseBasicParsing
        Write-Host "OK   $($f.Out)"
    } catch {
        Write-Host "FAIL $($f.Out) : $($_.Exception.Message)" -ForegroundColor Red
        $failed++
    }
}

if ($failed -gt 0) {
    Write-Host "`n$failed file(s) failed. The site still runs but may look unstyled." -ForegroundColor Yellow
    exit 1
}
Write-Host "`nAll files downloaded." -ForegroundColor Green
