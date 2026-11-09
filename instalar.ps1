# Instalador do AfroCreator Planner para Windows 10/11.
#
#   instalar-windows.bat                 (duplo clique) instala com perguntas
#   instalar.ps1 -Reconfigurar           refaz as perguntas e reinicia o Planner
#   instalar.ps1 -Padrao                 instala sem perguntas (setup AfroCreator Tech)
#   instalar.ps1 -Desinstalar            remove as tarefas agendadas (seus dados ficam em data\)
#
# Não precisa de administrador. Pode rodar quantas vezes quiser.
param([switch]$Reconfigurar, [switch]$Padrao, [switch]$Desinstalar)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$Dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Tarefa = "AfroCreator Planner"

function Ok($t)    { Write-Host "  [ok] $t" -ForegroundColor Green }
function Aviso($t) { Write-Host "  [!] $t" -ForegroundColor Yellow }
function Erro($t)  { Write-Host "  [x] $t" -ForegroundColor Red; Read-Host "Tecle Enter para fechar"; exit 1 }
function Passo($t) { Write-Host ""; Write-Host "== $t ==" -ForegroundColor Cyan }

if ($Desinstalar) {
  Passo "Removendo as tarefas do Planner"
  foreach ($t in @($Tarefa, "$Tarefa - metricas", "$Tarefa - agentes")) {
    Stop-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $t -Confirm:$false -ErrorAction SilentlyContinue
  }
  Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*$Dir*server.py*" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
  Ok "Pronto. Seus dados continuam em $Dir\data (apague a pasta se não quiser mais)."
  exit 0
}

Write-Host ""
Write-Host "  AfroCreator Planner - instalador Windows" -ForegroundColor Cyan
Write-Host "  (No Linux o Planner roda como serviço e é o caminho recomendado; no Windows ele funciona igual.)" -ForegroundColor DarkGray

Passo "1/5 Conferindo o Python"
function Achar-Python {
  $teste = "import sys; print(sys.executable if sys.version_info >= (3, 9) else '')"
  $exe = $null
  if (Get-Command py -ErrorAction SilentlyContinue) {
    try { $exe = & py -3 -c $teste 2>$null } catch { $exe = $null }
  }
  if (-not $exe -and (Get-Command python -ErrorAction SilentlyContinue)) {
    # o "python" falso da Microsoft Store não imprime nada; aí seguimos sem ele
    try { $exe = & python -c $teste 2>$null } catch { $exe = $null }
  }
  if ($exe) { $exe = "$exe".Trim() }
  if ($exe -and (Test-Path $exe)) { return $exe }
  return $null
}
$Py = Achar-Python
if (-not $Py) {
  Aviso "Python 3.9+ não encontrado."
  if (Get-Command winget -ErrorAction SilentlyContinue) {
    $r = Read-Host "  Instalar o Python 3.12 agora pelo winget? (S/n)"
    if ($r -notmatch '^[nN]') {
      winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
      $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
      $Py = Achar-Python
    }
  }
  if (-not $Py) { Erro "Instale o Python em https://www.python.org/downloads/ (marque 'Add python.exe to PATH') e rode de novo." }
}
$PyW = Join-Path (Split-Path $Py) "pythonw.exe"
if (-not (Test-Path $PyW)) { $PyW = $Py }
Ok "Python: $Py"

Passo "2/5 Personalização"
$Cfg = Join-Path $Dir "config.json"
if ($Padrao) { & $Py "$Dir\configurar.py" --padrao }
elseif ($Reconfigurar -or -not (Test-Path $Cfg)) { & $Py "$Dir\configurar.py" }
else { Ok "config.json já existe (para mudar as respostas: instalar.ps1 -Reconfigurar)" }
if ($LASTEXITCODE -ne 0) { Erro "Personalização cancelada ou com erro." }
$Info = & $Py -c "import sys; sys.path.insert(0, r'$Dir'); import configuracao as c, json; x = c.carregar(); print(json.dumps({'host': x['servidor']['host'], 'porta': x['servidor']['porta'], 'metricas': x['metricas']['ativo'] and any(r in x['metricas']['redes'] for r in ('instagram','youtube')), 'agentes': x['agentes']['ativo']}))"
if ($LASTEXITCODE -ne 0) { Erro "config.json com problema. Rode: instalar.ps1 -Reconfigurar" }
$Info = $Info | ConvertFrom-Json
New-Item -ItemType Directory -Force -Path (Join-Path $Dir "data") | Out-Null
Ok "Configuração pronta"

Passo "3/5 Conferindo os arquivos"
& $Py -m py_compile "$Dir\server.py" "$Dir\configuracao.py" "$Dir\sincronizar.py" "$Dir\coletar_metricas.py"
if ($LASTEXITCODE -ne 0) { Erro "Algum arquivo .py está com erro." }
Ok "Arquivos conferidos"

Passo "4/5 Ligando o Planner (inicia sozinho quando você entra no Windows)"
$Usuario = "$env:USERDOMAIN\$env:USERNAME"
$Principal = New-ScheduledTaskPrincipal -UserId $Usuario -LogonType Interactive -RunLevel Limited
$Config = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
  -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable -MultipleInstances IgnoreNew

# para a versão antiga antes de subir a nova
Stop-ScheduledTask -TaskName $Tarefa -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -like "*$Dir*server.py*" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

$Acao = New-ScheduledTaskAction -Execute $PyW -Argument "`"$Dir\server.py`"" -WorkingDirectory $Dir
Register-ScheduledTask -TaskName $Tarefa -Action $Acao -Trigger (New-ScheduledTaskTrigger -AtLogOn -User $Usuario) `
  -Principal $Principal -Settings $Config -Description "Servidor local do AfroCreator Planner" -Force | Out-Null
Start-ScheduledTask -TaskName $Tarefa
Ok "Tarefa '$Tarefa' criada e iniciada"

if ($Info.metricas) {
  $A = New-ScheduledTaskAction -Execute $PyW -Argument "`"$Dir\coletar_metricas.py`"" -WorkingDirectory $Dir
  Register-ScheduledTask -TaskName "$Tarefa - metricas" -Action $A -Trigger (New-ScheduledTaskTrigger -Daily -At "09:10") `
    -Principal $Principal -Settings $Config -Description "Coleta diária de seguidores" -Force | Out-Null
  Ok "Coleta diária de seguidores às 9h10"
} else { Unregister-ScheduledTask -TaskName "$Tarefa - metricas" -Confirm:$false -ErrorAction SilentlyContinue }

if ($Info.agentes) {
  $A = New-ScheduledTaskAction -Execute $PyW -Argument "`"$Dir\sincronizar.py`"" -WorkingDirectory $Dir
  $T = New-ScheduledTaskTrigger -Once -At (Get-Date).Date -RepetitionInterval (New-TimeSpan -Minutes 15)
  Register-ScheduledTask -TaskName "$Tarefa - agentes" -Action $A -Trigger $T `
    -Principal $Principal -Settings $Config -Description "Aprovações e legendas dos agentes de IA (WSL)" -Force | Out-Null
  Ok "Integração com os agentes a cada 15 min (os agentes rodam no Ubuntu/WSL)"
} else { Unregister-ScheduledTask -TaskName "$Tarefa - agentes" -Confirm:$false -ErrorAction SilentlyContinue }

Passo "5/5 Conferindo"
$Url = "http://127.0.0.1:$($Info.porta)"
$Respondeu = $false
foreach ($i in 1..10) {
  Start-Sleep -Seconds 1
  try { Invoke-WebRequest "$Url/api/config" -UseBasicParsing -TimeoutSec 3 | Out-Null; $Respondeu = $true; break } catch { }
}
if (-not $Respondeu) {
  Aviso "O Planner não respondeu. Rodando direto para mostrar o erro:"
  & $Py "$Dir\server.py"
  Erro "Corrija o erro acima e rode o instalador de novo."
}
Ok "Respondendo em $Url"

Write-Host ""
Write-Host "  Pronto! Abra no navegador: $Url" -ForegroundColor Green
if ($Info.host -eq "0.0.0.0") {
  $Ip = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.PrefixOrigin -in "Dhcp", "Manual" -and $_.IPAddress -notlike "169.*" } | Select-Object -First 1).IPAddress
  Write-Host "  No celular ou em outro PC da mesma rede: http://$($Ip):$($Info.porta)"
  Write-Host "  Se o Windows perguntar sobre o firewall, permita só em 'Redes privadas'." -ForegroundColor Yellow
  Write-Host "  Se não perguntar e o celular não abrir, rode no PowerShell como administrador:" -ForegroundColor DarkGray
  Write-Host "    New-NetFirewallRule -DisplayName 'AfroCreator Planner' -Direction Inbound -Protocol TCP -LocalPort $($Info.porta) -Profile Private -Action Allow" -ForegroundColor DarkGray
}
if ($Info.metricas) { Write-Host "  Coleta automática de seguidores: py -3 `"$Dir\coletar_metricas.py`" configurar" }
Write-Host "  Mudar as respostas: instalar-windows.bat e escolha reconfigurar (ou instalar.ps1 -Reconfigurar)"
Start-Process $Url
Write-Host ""
Read-Host "Tecle Enter para fechar"
