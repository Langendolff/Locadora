# Locadora: instalador para Windows (WSL2 + Docker Desktop)
#
# Copia a Locadora para dentro do Linux do WSL (~/Locadora), onde o disco é rápido e os
# hardlinks funcionam, e roda o setup.sh de lá. Pode ser executado de novo para atualizar.
#
# Uso: clique duas vezes em Instalar.bat (ou: powershell -File instalar.ps1 [caminho\vpn.conf])

$ErrorActionPreference = 'Stop'
function Fail([string]$msg) {
    Write-Host ""
    Write-Host "ERRO: $msg" -ForegroundColor Red
    exit 1
}
function Step([string]$msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

# Caminho do Windows -> caminho dentro do WSL (C:\Users\x -> /mnt/c/Users/x)
function ConvertTo-WslPath([string]$path) {
    $full = (Resolve-Path -LiteralPath $path).Path
    if ($full -notmatch '^[A-Za-z]:\\') { Fail "caminho não suportado: $full" }
    if ($full.Contains("'")) { Fail "o caminho não pode conter aspas simples ('): $full" }
    $drive = $full.Substring(0, 1).ToLower()
    return "/mnt/$drive" + ($full.Substring(2) -replace '\\', '/')
}

Write-Host ""
Write-Host "  Locadora" -ForegroundColor Red
Write-Host "  Seu serviço de streaming, no seu servidor." -ForegroundColor Gray
Write-Host ""

# 1. WSL
Step "Verificando o WSL..."
if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    Fail "WSL não encontrado. Abra o PowerShell como administrador, rode 'wsl --install' e reinicie o PC."
}
$distros = (& wsl.exe --list --quiet 2>$null) -replace "`0", "" | Where-Object { $_.Trim() -ne "" }
if (-not $distros) {
    Fail "nenhuma distribuição Linux instalada no WSL. Rode 'wsl --install -d Ubuntu', crie o usuário e tente de novo."
}

# 2. Docker Desktop com integração no WSL
Step "Verificando o Docker Desktop..."
& wsl.exe -e sh -c "docker info >/dev/null 2>&1"
if ($LASTEXITCODE -ne 0) {
    Fail ("o Docker não responde dentro do WSL. Abra o Docker Desktop e ative " +
          "Settings > Resources > WSL integration para a sua distribuição Linux.")
}

# 3. Arquivo da VPN
$conf = if ($args.Count -ge 1) { $args[0] } else { $null }
$hasConf = (& wsl.exe -e sh -c "test -f ~/Locadora/vpn/wg0.conf && echo sim") -eq "sim"
if (-not $conf -and -not $hasConf) {
    Step "Escolha o arquivo WireGuard (.conf) da sua VPN..."
    Add-Type -AssemblyName System.Windows.Forms
    $dialog = New-Object System.Windows.Forms.OpenFileDialog
    $dialog.Title = "Locadora: escolha o arquivo WireGuard (.conf) da sua VPN"
    $dialog.Filter = "Configuração WireGuard (*.conf)|*.conf|Todos os arquivos (*.*)|*.*"
    $dialog.InitialDirectory = [Environment]::GetFolderPath("UserProfile") + "\Downloads"
    if ($dialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { Fail "nenhum arquivo escolhido." }
    $conf = $dialog.FileName
}

# 4. Copia para o Linux do WSL e instala
Step "Copiando a Locadora para o WSL (~/Locadora)..."
$src = ConvertTo-WslPath $PSScriptRoot
$cmd = "set -e; mkdir -p ~/Locadora && cp -r '$src/.' ~/Locadora/ && cd ~/Locadora && " +
       "find . -name '*.sh' -exec chmod +x {} + && chmod +x setup.sh change-password.sh diagnostico.sh && "
if ($conf) {
    $wconf = ConvertTo-WslPath $conf
    $cmd += "./setup.sh '$wconf'"
} else {
    $cmd += "./setup.sh"
}

Step "Instalando (a primeira vez demora alguns minutos)..."
& wsl.exe -e bash -lc $cmd
if ($LASTEXITCODE -ne 0) { Fail "a instalação não terminou. Veja as mensagens acima." }

Write-Host ""
Write-Host "Tudo pronto! Abra no navegador:" -ForegroundColor Green
Write-Host "  Pedir filmes e séries:  http://localhost:5055"
Write-Host "  Assistir:               http://localhost:8096"
Write-Host ""
Write-Host "Os arquivos ficam no WSL em ~/Locadora (no Explorer: \\wsl$\<distribuição>\home\<usuário>\Locadora)."
