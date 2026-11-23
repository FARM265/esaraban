# กู้คืนจากชุดสำรอง บน Windows (เขียนทับข้อมูลปัจจุบันทั้งหมด)
# รันที่โฟลเดอร์โปรเจกต์:  powershell -ExecutionPolicy Bypass -File scripts\restore.ps1 backups\20261120-230000
#
# ก่อนกู้คืน: .env.docker ต้องเป็นไฟล์เดิม (SECRET_KEY เดิม) มิฉะนั้นจะเปิดไฟล์เอกสารที่กู้คืนไม่ได้
param([Parameter(Mandatory = $true)][string]$BackupDir)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Run {
    param([string[]]$Arguments)
    & docker @("compose", "--env-file", ".env.docker") @Arguments
    if ($LASTEXITCODE -ne 0) { throw "คำสั่งล้มเหลว: docker compose $($Arguments -join ' ')" }
}

$dir = (Resolve-Path $BackupDir).Path
foreach ($name in "db.dump", "private_storage.tar.gz", "SHA256SUMS") {
    if (-not (Test-Path (Join-Path $dir $name))) { throw "ไม่พบ $name ใน $dir" }
}

Write-Host "[1/5] ตรวจ checksum"
foreach ($line in Get-Content (Join-Path $dir "SHA256SUMS")) {
    if (-not $line.Trim()) { continue }
    $expected, $name = $line -split "\s+", 2
    $actual = (Get-FileHash -Algorithm SHA256 (Join-Path $dir $name)).Hash.ToLower()
    if ($actual -ne $expected) { throw "checksum ของ $name ไม่ตรง ไฟล์สำรองอาจเสียหาย" }
    Write-Host "  $name OK"
}

Write-Host "ข้อมูลปัจจุบันทั้งหมดจะถูกแทนที่ด้วยชุดสำรอง $dir" -ForegroundColor Yellow
$answer = Read-Host "พิมพ์ RESTORE เพื่อยืนยัน"
if ($answer -cne "RESTORE") { Write-Host "ยกเลิก"; exit 1 }

Write-Host "[2/5] หยุดระบบ (ฐานข้อมูลยังทำงาน)"
Run @("stop", "nginx", "web")
Run @("up", "-d", "db")

Write-Host "[3/5] กู้คืนฐานข้อมูล"
Run @("cp", (Join-Path $dir "db.dump"), "db:/tmp/restore.dump")
Run @("exec", "-T", "db", "sh", "-c", 'pg_restore -U $POSTGRES_USER -d $POSTGRES_DB --clean --if-exists --no-owner --no-privileges --single-transaction --exit-on-error /tmp/restore.dump; status=$?; rm -f /tmp/restore.dump; exit $status')

Write-Host "[4/5] กู้คืนไฟล์เอกสาร"
Run @("run", "--rm", "--no-deps", "-v", "${dir}:/restore:ro", "--entrypoint", "sh", "web",
      "-c", 'find /app/private_storage -mindepth 1 -delete && tar -C /app -xzf /restore/private_storage.tar.gz')

Write-Host "[5/5] เปิดระบบ (entrypoint จะ migrate และตั้งสิทธิ์ผู้ใช้ฐานข้อมูลให้)"
Run @("up", "-d")
Write-Host "กู้คืนเสร็จ ให้ผู้ดูแลระบบเข้าเมนู Audit Log กด 'ตรวจความครบถ้วน' และลองเปิดเอกสารสักฉบับ" -ForegroundColor Green
