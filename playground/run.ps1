# Prompt Lab yerel dev sunucusunu başlatır (Windows PowerShell).
#
# Kullanım (repo kökünden):
#   .\playground\run.ps1
#
# GEMINI_API_KEY'i şu sırayla arar: mevcut ortam değişkeni -> repo kökündeki
# .env dosyası. Anahtar yalnızca sunucu ortamında kalır; tarayıcıya gitmez.

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot

# .env varsa GEMINI_API_KEY'i oku (yalnızca ortamda yoksa).
if (-not $env:GEMINI_API_KEY) {
    $envFile = Join-Path $repoRoot ".env"
    if (Test-Path $envFile) {
        foreach ($line in Get-Content $envFile) {
            if ($line -match '^\s*GEMINI_API_KEY\s*=\s*(.+)\s*$') {
                $env:GEMINI_API_KEY = $matches[1].Trim().Trim('"')
            }
        }
    }
}

if (-not $env:GEMINI_API_KEY) {
    Write-Warning "GEMINI_API_KEY ayarlı degil. Sunucu acilir ama /extract 503 doner."
    Write-Warning "Anahtari .env'e ekleyin ya da: `$env:GEMINI_API_KEY='...'"
}

Push-Location $repoRoot
try {
    python -m uvicorn playground.server:app --reload --port 8900
}
finally {
    Pop-Location
}
