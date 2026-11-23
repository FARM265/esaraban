# ตั้งค่าให้เครื่องนี้เป็นเครื่องหลักของระบบ E-Saraban สำหรับใช้ในเครือข่ายสำนักงาน (LAN) ครั้งเดียวจบ
# วิธีรัน: คลิกขวา PowerShell เลือก "Run as administrator" แล้ว
#   cd C:\Projects\esaraban
#   powershell -ExecutionPolicy Bypass -File scripts\setup-office.ps1
#
# สิ่งที่ทำ (ถามก่อนทุกข้อที่เปลี่ยนการตั้งค่าเครื่อง)
#   1) หา IP และชื่อเครื่อง แล้วแก้ SERVER_NAME / ALLOWED_HOSTS / CSRF_TRUSTED_ORIGINS ใน .env.docker
#      (สำรองไฟล์เดิมไว้ก่อน ไม่แสดงและไม่แตะค่าลับอื่นในไฟล์)
#   2) เปิด Firewall พอร์ต 80/443 เฉพาะเครือข่ายสำนักงาน (Private/Domain)
#   3) ตั้งไม่ให้เครื่องหลับเมื่อเสียบสายไฟ
#   4) ตั้งสำรองข้อมูลอัตโนมัติทุกวัน (Task Scheduler)
#   5) เริ่มระบบใหม่ด้วยค่าใหม่ แล้วแสดงที่อยู่สำหรับแจ้งเพื่อนร่วมงาน
param([string]$BackupTime = "12:15")

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Ask([string]$question) {
    $answer = Read-Host "$question (y/n)"
    return $answer -match '^(y|Y|yes|ใช่)$'
}

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "กรุณาเปิด PowerShell ด้วย 'Run as administrator' แล้วรันใหม่" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path ".env.docker")) {
    Write-Host "ไม่พบไฟล์ .env.docker ในโฟลเดอร์นี้ ($root)" -ForegroundColor Red
    exit 1
}

# ---------------------------------------------------------------- 1) IP และชื่อเครื่อง
$configs = @(Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq "Up" })
if ($configs.Count -eq 0) {
    Write-Host "ไม่พบการเชื่อมต่อเครือข่ายที่มี gateway กรุณาต่อสาย LAN หรือ Wi-Fi ของสำนักงานก่อน" -ForegroundColor Red
    exit 1
}
if ($configs.Count -gt 1) {
    Write-Host "พบการเชื่อมต่อมากกว่า 1 ช่องทาง:"
    for ($i = 0; $i -lt $configs.Count; $i++) {
        Write-Host ("  [{0}] {1}  {2}" -f ($i + 1), $configs[$i].InterfaceAlias, $configs[$i].IPv4Address[0].IPAddress)
    }
    $pick = [int](Read-Host "เลือกช่องทางที่ต่อเครือข่ายสำนักงาน (ใส่หมายเลข)") - 1
    $config = $configs[$pick]
} else {
    $config = $configs[0]
}
$ip = $config.IPv4Address[0].IPAddress
$hostName = $env:COMPUTERNAME.ToLower()
Write-Host ""
Write-Host "IP ของเครื่องนี้: $ip   ชื่อเครื่อง: $hostName" -ForegroundColor Cyan
if ($config.IPv4Address[0].PrefixOrigin -eq "Dhcp") {
    Write-Host "หมายเหตุ: IP นี้ได้จาก DHCP อาจเปลี่ยนหลังรีสตาร์ท ขอ IP คงที่จากผู้ดูแลเครือข่าย หรือรันสคริปต์นี้ใหม่เมื่อ IP เปลี่ยน" -ForegroundColor Yellow
}

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
Copy-Item ".env.docker" ".env.docker.bak-$stamp"
$text = [IO.File]::ReadAllText((Resolve-Path ".env.docker"))
$newline = if ($text.Contains("`r`n")) { "`r`n" } else { "`n" }
$values = [ordered]@{
    "SERVER_NAME"          = $ip
    "ALLOWED_HOSTS"        = "$ip,$hostName,localhost,127.0.0.1"
    "CSRF_TRUSTED_ORIGINS" = "https://$ip,https://$hostName,https://localhost"
}
foreach ($key in $values.Keys) {
    $line = "$key=$($values[$key])"
    $pattern = "(?m)^$key=[^\r\n]*"
    if ([regex]::IsMatch($text, $pattern)) {
        $text = [regex]::Replace($text, $pattern, $line)
    } else {
        if (-not $text.EndsWith("`n")) { $text += $newline }
        $text += $line + $newline
    }
}
# เขียนแบบ UTF-8 ไม่มี BOM เพราะ docker compose อ่านไฟล์ที่มี BOM ผิด
[IO.File]::WriteAllText((Join-Path $root ".env.docker"), $text, (New-Object System.Text.UTF8Encoding($false)))
Write-Host "[1/5] แก้ .env.docker แล้ว (สำรองไฟล์เดิมเป็น .env.docker.bak-$stamp)"

# ---------------------------------------------------------------- 2) Firewall
$profiles = @(Get-NetConnectionProfile -InterfaceIndex $config.InterfaceIndex)
if ($profiles | Where-Object { $_.NetworkCategory -eq "Public" }) {
    Write-Host "Windows ตั้งเครือข่ายนี้เป็น Public เครื่องอื่นจะเข้าไม่ได้" -ForegroundColor Yellow
    if (Ask "เปลี่ยนเครือข่ายนี้เป็น Private (เครือข่ายที่ไว้ใจได้ของสำนักงาน)") {
        Set-NetConnectionProfile -InterfaceIndex $config.InterfaceIndex -NetworkCategory Private
    }
}
$ruleName = "E-Saraban (HTTP/HTTPS)"
if (-not (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Protocol TCP -LocalPort 80,443 `
        -Action Allow -Profile Private,Domain | Out-Null
}
Write-Host "[2/5] เปิด Firewall พอร์ต 80/443 สำหรับเครือข่าย Private/Domain แล้ว"

# ---------------------------------------------------------------- 3) ไม่ให้เครื่องหลับ
if (Ask "ตั้งไม่ให้เครื่องหลับเมื่อเสียบสายไฟ (แนะนำ ถ้าเครื่องหลับ ระบบจะใช้ไม่ได้ทั้งสำนักงาน)") {
    powercfg /change standby-timeout-ac 0
    powercfg /change hibernate-timeout-ac 0
    Write-Host "[3/5] ตั้งไม่ให้หลับเมื่อเสียบสายไฟแล้ว (จอยังดับได้ตามปกติ)"
} else {
    Write-Host "[3/5] ข้าม"
}

# ---------------------------------------------------------------- 4) สำรองข้อมูลทุกวัน
if (Ask "ตั้งให้สำรองข้อมูลอัตโนมัติทุกวันเวลา $BackupTime") {
    $taskName = "E-Saraban daily backup"
    $action = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$root\scripts\backup.ps1`"" -WorkingDirectory $root
    $trigger = New-ScheduledTaskTrigger -Daily -At $BackupTime
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2)
    $user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings `
        -Principal $principal -Force | Out-Null
    Write-Host "[4/5] ตั้งสำรองข้อมูลทุกวันเวลา $BackupTime แล้ว (ต้องเข้าสู่ระบบ Windows ค้างไว้ ถ้าเครื่องปิดอยู่จะสำรองทันทีเมื่อเปิด)"
} else {
    Write-Host "[4/5] ข้าม"
}

# ---------------------------------------------------------------- 5) เริ่มระบบใหม่
Write-Host "[5/5] เริ่มระบบใหม่ด้วยค่าใหม่..."
& docker compose --env-file .env.docker up -d
if ($LASTEXITCODE -ne 0) {
    Write-Host "เริ่มระบบไม่สำเร็จ ตรวจว่า Docker Desktop เปิดอยู่ แล้วรันคำสั่ง: docker compose --env-file .env.docker up -d" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "เสร็จแล้ว แจ้งเพื่อนร่วมงานให้เปิด:" -ForegroundColor Green
Write-Host "    https://$ip" -ForegroundColor Green
Write-Host "    หรือ https://$hostName (ถ้าเครือข่ายสำนักงานรู้จักชื่อเครื่อง)" -ForegroundColor Green
Write-Host "เบราว์เซอร์จะเตือนเรื่องใบรับรองครั้งแรก ให้กด 'ขั้นสูง' แล้ว 'ดำเนินการต่อ'"
Write-Host "อย่าลืม: Docker Desktop > Settings > General > ติ๊ก 'Start Docker Desktop when you sign in'"
Write-Host "และคัดลอกโฟลเดอร์ backups ไปเก็บที่อื่นเป็นประจำ (เช่น แฟลชไดรฟ์หรือ NAS ของสำนักงาน)"
