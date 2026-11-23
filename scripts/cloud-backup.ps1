# สำรองข้อมูลระบบที่อยู่บนคลาวด์ (ฐานข้อมูล Supabase + ไฟล์เอกสารใน Supabase Storage) ลงเครื่องนี้
# ต้องมี Docker Desktop บนเครื่องที่รัน (ใช้ image postgres และ aws-cli ไม่ต้องติดตั้งโปรแกรมอื่น)
#
# ครั้งแรก: สร้างไฟล์ .env.cloud ในโฟลเดอร์โปรเจกต์ ใส่ค่าเดียวกับที่ตั้งใน Render (ดู docs\cloud-render-supabase.md)
#   DATABASE_URL=postgresql://...
#   S3_ENDPOINT_URL=https://xxxx.supabase.co/storage/v1/s3
#   S3_REGION=ap-southeast-1
#   S3_BUCKET=esaraban-files
#   S3_ACCESS_KEY_ID=...
#   S3_SECRET_ACCESS_KEY=...
# วิธีรัน: powershell -ExecutionPolicy Bypass -File scripts\cloud-backup.ps1
#
# สำคัญ: ไฟล์เอกสารที่สำรองถูกเข้ารหัสด้วยกุญแจจาก SECRET_KEY ที่ตั้งใน Render ต้องเก็บ SECRET_KEY แยกไว้ด้วย
param([int]$KeepDays = 30)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path ".env.cloud")) {
    Write-Host "ไม่พบไฟล์ .env.cloud กรุณาสร้างตามคำอธิบายด้านบนของสคริปต์นี้" -ForegroundColor Red
    exit 1
}

function Run {
    param([string[]]$Arguments)
    & docker @Arguments
    if ($LASTEXITCODE -ne 0) { throw "คำสั่งล้มเหลว: docker $($Arguments[0..2] -join ' ') ..." }
}

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$out = Join-Path "backups" "cloud-$stamp"
New-Item -ItemType Directory -Force -Path $out | Out-Null
$outAbs = (Resolve-Path $out).Path
$envFile = (Resolve-Path ".env.cloud").Path

Write-Host "[1/3] สำรองฐานข้อมูลจาก Supabase"
Run @("run", "--rm", "--env-file", $envFile, "-v", "${outAbs}:/backup", "postgres:17-alpine",
      "sh", "-c", 'pg_dump -d $DATABASE_URL -Fc --no-owner --no-privileges -f /backup/db.dump && pg_restore --list /backup/db.dump > /dev/null')

Write-Host "[2/3] สำรองไฟล์เอกสารจาก Supabase Storage (เข้ารหัสอยู่แล้ว)"
Run @("run", "--rm", "--env-file", $envFile, "-v", "${outAbs}:/backup", "--entrypoint", "sh", "amazon/aws-cli",
      "-c", 'AWS_ACCESS_KEY_ID=$S3_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY=$S3_SECRET_ACCESS_KEY aws s3 sync s3://$S3_BUCKET/documents /backup/files/documents --endpoint-url $S3_ENDPOINT_URL --region $S3_REGION --only-show-errors')

Write-Host "[3/3] สร้าง checksum และลบชุดเก่ากว่า $KeepDays วัน"
$sums = Get-ChildItem -Path $out -Recurse -File | ForEach-Object {
    $hash = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower()
    "$hash  $($_.FullName.Substring($outAbs.Length + 1).Replace('\', '/'))"
}
[IO.File]::WriteAllLines((Join-Path $outAbs "SHA256SUMS"), [string[]]$sums)
Get-ChildItem "backups" -Directory | Where-Object { $_.Name -like "cloud-20*" -and $_.CreationTime -lt (Get-Date).AddDays(-$KeepDays) } |
    Remove-Item -Recurse -Force

$count = @(Get-ChildItem (Join-Path $out "files") -Recurse -File -ErrorAction SilentlyContinue).Count
Write-Host ""
Write-Host "สำรองเสร็จ: $out (ไฟล์เอกสาร $count ไฟล์)" -ForegroundColor Green
Write-Host "คัดลอกโฟลเดอร์นี้ไปเก็บอีกที่หนึ่ง และเก็บ SECRET_KEY จาก Render ไว้แยกในที่ปลอดภัย"
