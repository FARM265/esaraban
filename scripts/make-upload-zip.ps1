# สร้างไฟล์ zip ของโค้ดสำหรับอัปโหลดขึ้น server (เช่น VM ของ Google Cloud)
# ไม่รวมค่าลับ (.env*), ชุดสำรอง, ใบรับรอง, ไฟล์เอกสาร และไฟล์ที่สร้างระหว่างใช้งาน
# วิธีรัน: powershell -ExecutionPolicy Bypass -File scripts\make-upload-zip.ps1
# ได้ไฟล์ esaraban-upload.zip ที่หน้า Desktop
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$zipPath = Join-Path ([Environment]::GetFolderPath("Desktop")) "esaraban-upload.zip"

$skipDirs = @(".git", ".venv", "venv", ".vscode", "__pycache__", "backups", "private_storage", "staticfiles",
              "htmlcov", "certs", "vendor", "node_modules")
$skipFile = '^(\.env(\..*)?|test-result\.txt.*|web-log\.txt|.*\.pyc|.*\.log|\.coverage)$'

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }

$count = 0
$zip = [System.IO.Compression.ZipFile]::Open($zipPath, [System.IO.Compression.ZipArchiveMode]::Create)
try {
    $files = Get-ChildItem -Path $root -Recurse -File -Force | Where-Object {
        $rel = $_.FullName.Substring($root.Length + 1)
        $parts = $rel.Split([IO.Path]::DirectorySeparatorChar)
        $inSkippedDir = $false
        foreach ($p in $parts[0..([Math]::Max(0, $parts.Length - 2))]) {
            if ($parts.Length -gt 1 -and $skipDirs -contains $p) { $inSkippedDir = $true }
        }
        # .env.docker.example และ .env.example ไม่มีค่าลับ จึงรวมไว้
        $isExample = $_.Name -like "*.example"
        -not $inSkippedDir -and ($isExample -or $_.Name -notmatch $skipFile)
    }
    foreach ($f in $files) {
        # ใช้ / ในชื่อไฟล์ใน zip เพื่อให้แตกบน Linux ได้ถูกต้อง
        $entry = "esaraban/" + $f.FullName.Substring($root.Length + 1).Replace("\", "/")
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $f.FullName, $entry) | Out-Null
        $count++
    }
} finally {
    $zip.Dispose()
}
$sizeMb = [Math]::Round((Get-Item $zipPath).Length / 1MB, 1)
Write-Host "สร้างไฟล์ $zipPath แล้ว ($count ไฟล์, $sizeMb MB)" -ForegroundColor Green
Write-Host "ไม่มีไฟล์ .env.docker หรือข้อมูลเอกสารอยู่ในไฟล์นี้"
