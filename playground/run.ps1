# Prompt Lab yerel dev sunucusunu başlatır (Windows PowerShell).
#
# Kullanım (repo kökünden):
#   .\playground\run.ps1
#
# GEMINI_API_KEY'i mevcut ortam değişkeninden ya da repo kökündeki .env /
# .env.local dosyasından bulur — asıl yükleme `playground/__init__.py` içinde
# olur (paket import edilir edilmez çalışır), bu yüzden `uvicorn
# playground.server:app` DOĞRUDAN çalıştırılsa bile anahtar bulunur. Bu script
# yalnızca kolaylık + erken uyarı sağlar. Anahtar yalnızca sunucu ortamında
# kalır; tarayıcıya gitmez.

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot

$hasKey = [bool]$env:GEMINI_API_KEY
if (-not $hasKey) {
    foreach ($name in @(".env", ".env.local")) {
        $envFile = Join-Path $repoRoot $name
        if ((Test-Path $envFile) -and (Select-String -Path $envFile -Pattern '^\s*GEMINI_API_KEY\s*=' -Quiet)) {
            $hasKey = $true
        }
    }
}

if (-not $hasKey) {
    Write-Warning "GEMINI_API_KEY hicbir yerde bulunamadi (ortam degiskeni, .env, .env.local)."
    Write-Warning "Repo KOKUNDE (web/ ALTINDA DEGIL) .env ya da .env.local dosyasina ekleyin:"
    Write-Warning '  GEMINI_API_KEY="..."'
    Write-Warning "Sunucu yine de acilir ama /playground/extract 503 doner."
}

Push-Location $repoRoot
try {
    python -m uvicorn playground.server:app --reload --port 8900
}
finally {
    Pop-Location
}
