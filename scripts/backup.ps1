# สำรองฐานข้อมูลและไฟล์เอกสาร บน Windows ที่ใช้ Docker Desktop
# รันที่โฟลเดอร์โปรเจกต์:  powershell -ExecutionPolicy Bypass -File scripts\backup.ps1
# ตั้งให้รันทุกวันด้วย Task Scheduler และคัดลอกโฟลเดอร์ backups ไปเก็บนอกเครื่อง (ดู docs\backup-restore.md)
#
# สำคัญ: ไฟล์เอกสารที่สำรองถูกเข้ารหัสด้วยกุญแจจาก SECRET_KEY ถ้าไฟล์ .env.docker หาย จะกู้คืนเอกสารไม่ได้
param([int]$KeepDays = 30)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Run {
    # PowerShell ไม่หยุดเองเมื่อคำสั่งภายนอกล้มเหลว จึงตรวจ exit code ทุกครั้ง
    param([string[]]$Arguments)
    & docker @("compose", "--env-file", ".env.docker") @Arguments
    if ($LASTEXITCODE -ne 0) { throw "คำสั่งล้มเหลว: docker compose $($Arguments -join ' ')" }
}

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$out = Join-Path "backups" $stamp
New-Item -ItemType Directory -Force -Path $out | Out-Null

Write-Host "[1/4] สำรองฐานข้อมูล"
Run @("exec", "-T", "db", "sh", "-c", 'pg_dump -U $POSTGRES_USER -d $POSTGRES_DB -Fc -f /tmp/esaraban.dump && pg_restore --list /tmp/esaraban.dump > /dev/null')
Run @("cp", "db:/tmp/esaraban.dump", (Join-Path $out "db.dump"))
Run @("exec", "-T", "db", "rm", "-f", "/tmp/esaraban.dump")

Write-Host "[2/4] สำรองไฟล์เอกสาร (เข้ารหัสอยู่แล้ว)"
Run @("exec", "-T", "web", "sh", "-c", 'tar -C /app -czf /tmp/private_storage.tar.gz private_storage && tar -tzf /tmp/private_storage.tar.gz > /dev/null')
Run @("cp", "web:/tmp/private_storage.tar.gz", (Join-Path $out "private_storage.tar.gz"))
Run @("exec", "-T", "web", "rm", "-f", "/tmp/private_storage.tar.gz")

Write-Host "[3/4] บันทึก checksum"
$lines = foreach ($name in "db.dump", "private_storage.tar.gz") {
    $file = Join-Path $out $name
    if ((Get-Item $file).Length -eq 0) { throw "ไฟล์ $name ว่างเปล่า" }
    "{0}  {1}" -f (Get-FileHash -Algorithm SHA256 $file).Hash.ToLower(), $name
}
[IO.File]::WriteAllText((Join-Path (Resolve-Path $out) "SHA256SUMS"), (($lines -join "`n") + "`n"))

Write-Host "[4/4] ลบชุดสำรองที่เก่ากว่า $KeepDays วัน"
Get-ChildItem "backups" -Directory | Where-Object { $_.Name -like "20*" -and $_.LastWriteTime -lt (Get-Date).AddDays(-$KeepDays) } |
    Remove-Item -Recurse -Force

Write-Host "สำรองเสร็จ: $out" -ForegroundColor Green
Write-Host "เตือน: ตรวจว่าเก็บสำเนา .env.docker ไว้แยกในที่ปลอดภัยแล้ว (ไม่มีไฟล์นี้จะเปิดเอกสารที่สำรองไว้ไม่ได้)" -ForegroundColor Yellow
