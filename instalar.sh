#!/usr/bin/env bash
# Instalador do AfroCreator Planner para Linux (recomendado: Ubuntu 22.04 ou mais novo).
#
#   ./instalar.sh                 instala e faz as perguntas de personalização
#   ./instalar.sh --reconfigurar  refaz as perguntas e reinicia o Planner
#   ./instalar.sh --padrao        instala sem perguntas (setup AfroCreator Tech)
#   ./instalar.sh --desinstalar   para e remove os serviços (seus dados ficam em data/)
#
# Pode rodar quantas vezes quiser: nada é duplicado e seus roteiros não são apagados.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
UNID="$HOME/.config/systemd/user"
NOME="afrocreator-planner"
ok(){ printf '  \033[92m✔\033[0m %s\n' "$*"; }
aviso(){ printf '  \033[33m!\033[0m %s\n' "$*"; }
erro(){ printf '  \033[31m✖ %s\033[0m\n' "$*"; exit 1; }
passo(){ printf '\n\033[96m== %s ==\033[0m\n' "$*"; }

MODO="instalar"
case "${1:-}" in
  --reconfigurar) MODO="reconfigurar" ;;
  --padrao) MODO="padrao" ;;
  --desinstalar) MODO="desinstalar" ;;
  "") ;;
  -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
  *) erro "Opção desconhecida: $1 (use --help)" ;;
esac

if [ "$MODO" = "desinstalar" ]; then
  passo "Removendo os serviços do Planner"
  systemctl --user disable --now "$NOME.service" "$NOME-metricas.timer" "$NOME-agentes.timer" >/dev/null 2>&1 || true
  rm -f "$UNID/$NOME".service "$UNID/$NOME"-*.service "$UNID/$NOME"-*.timer
  systemctl --user daemon-reload
  ok "Serviços removidos. Seus dados continuam em $DIR/data (apague a pasta se não quiser mais)."
  exit 0
fi

printf '\n\033[96m  AfroCreator Planner · instalador Linux\033[0m\n'

passo "1/5 Conferindo o computador"
[ "$(uname -s)" = "Linux" ] || erro "Este instalador é para Linux. No Windows, use instalar-windows.bat."
command -v python3 >/dev/null || erro "Python 3 não encontrado. No Ubuntu: sudo apt install python3"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' \
  || erro "Precisa do Python 3.9 ou mais novo (você tem $(python3 --version 2>&1))."
ok "$(python3 --version)"
if command -v systemctl >/dev/null && systemctl --user show-environment >/dev/null 2>&1; then
  SYSTEMD=1; ok "systemd disponível (o Planner vai iniciar sozinho)"
else
  SYSTEMD=0; aviso "systemd de usuário indisponível: no fim eu mostro como iniciar o Planner à mão."
fi
if grep -qi microsoft /proc/version 2>/dev/null; then
  aviso "Você está no WSL. Funciona, mas o Planner só fica ligado enquanto o Ubuntu estiver aberto."
fi

passo "2/5 Personalização"
case "$MODO" in
  padrao) python3 "$DIR/configurar.py" --padrao ;;
  instalar)
    if [ -f "$DIR/config.json" ]; then
      ok "config.json já existe (para mudar as respostas: ./instalar.sh --reconfigurar)"
      python3 "$DIR/configuracao.py" >/dev/null || erro "config.json com problema. Rode: ./instalar.sh --reconfigurar"
    else
      python3 "$DIR/configurar.py" || erro "Personalização cancelada."
    fi ;;
  reconfigurar) python3 "$DIR/configurar.py" || erro "Personalização cancelada." ;;
esac
CFG="$(python3 - "$DIR" <<'PY'
import sys; sys.path.insert(0, sys.argv[1])
import configuracao as c
x = c.carregar()
print(x["servidor"]["host"], x["servidor"]["porta"], int(x["metricas"]["ativo"]), int(x["agentes"]["ativo"]),
      int(any(r in x["metricas"]["redes"] for r in ("instagram", "youtube"))))
PY
)"
read -r HOST PORTA METRICAS AGENTES COLETA <<<"$CFG"
mkdir -p "$DIR/data"
ok "Configuração pronta"

passo "3/5 Testando o Planner"
if command -v ss >/dev/null && ss -ltn "sport = :$PORTA" 2>/dev/null | grep -q LISTEN \
   && ! systemctl --user is-active --quiet "$NOME.service" 2>/dev/null; then
  erro "A porta $PORTA já está em uso por outro programa. Rode ./instalar.sh --reconfigurar e escolha outra."
fi
python3 -m py_compile "$DIR"/*.py || erro "Algum arquivo .py está com erro."
ok "Arquivos conferidos"

passo "4/5 Ligando o Planner"
if [ "$SYSTEMD" = 1 ]; then
  mkdir -p "$UNID"
  PY="$(command -v python3)"
  cat > "$UNID/$NOME.service" <<EOF
[Unit]
Description=AfroCreator Planner (roteiros, posts e métricas)
After=network.target

[Service]
WorkingDirectory=$DIR
ExecStart="$PY" "$DIR/server.py"
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF
  ATIVAR=("$NOME.service")
  if [ "$METRICAS" = 1 ] && [ "$COLETA" = 1 ]; then
    cat > "$UNID/$NOME-metricas.service" <<EOF
[Unit]
Description=AfroCreator Planner - coleta diária de seguidores
[Service]
Type=oneshot
WorkingDirectory=$DIR
ExecStart="$PY" "$DIR/coletar_metricas.py"
EOF
    cat > "$UNID/$NOME-metricas.timer" <<EOF
[Unit]
Description=AfroCreator Planner - coleta diária de seguidores (9h10)
[Timer]
OnCalendar=*-*-* 09:10:00
Persistent=true
[Install]
WantedBy=timers.target
EOF
    ATIVAR+=("$NOME-metricas.timer")
  else
    systemctl --user disable --now "$NOME-metricas.timer" >/dev/null 2>&1 || true
  fi
  if [ "$AGENTES" = 1 ]; then
    cat > "$UNID/$NOME-agentes.service" <<EOF
[Unit]
Description=AfroCreator Planner - aprovações e legendas dos agentes
[Service]
Type=oneshot
WorkingDirectory=$DIR
Environment="PATH=$HOME/.local/bin:$HOME/.npm-global/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart="$PY" "$DIR/sincronizar.py"
TimeoutStartSec=3600
EOF
    cat > "$UNID/$NOME-agentes.timer" <<EOF
[Unit]
Description=AfroCreator Planner - integração com os agentes (a cada 15 min)
[Timer]
OnCalendar=*:0/15
Persistent=true
[Install]
WantedBy=timers.target
EOF
    ATIVAR+=("$NOME-agentes.timer")
  else
    systemctl --user disable --now "$NOME-agentes.timer" >/dev/null 2>&1 || true
  fi
  systemctl --user daemon-reload
  systemctl --user enable "${ATIVAR[@]}" >/dev/null 2>&1
  systemctl --user restart "$NOME.service"
  for t in "${ATIVAR[@]:1}"; do systemctl --user restart "$t"; done
  sleep 2
  systemctl --user is-active --quiet "$NOME.service" \
    || { journalctl --user -u "$NOME" -n 15 --no-pager; erro "O Planner não subiu. Veja as linhas acima."; }
  ok "Planner ligado e configurado para iniciar com o computador"
  [ "${#ATIVAR[@]}" -gt 1 ] && ok "Rotinas: ${ATIVAR[*]:1}"
  if ! loginctl show-user "${USER:-$(id -un)}" -p Linger 2>/dev/null | grep -q yes; then
    echo
    echo "  Quer que o Planner fique ligado mesmo antes de você entrar na sua conta"
    echo "  (útil se o notebook fica ligado como servidor)? Isso pede a sua senha."
    read -rp "  Ligar? (s/N): " R || R=""
    if [[ "$R" =~ ^[sS] ]]; then sudo loginctl enable-linger "${USER:-$(id -un)}" && ok "Ligado"; fi
  fi
else
  aviso "Para iniciar o Planner: cd \"$DIR\" && python3 server.py"
fi

passo "5/5 Conferindo"
responde(){ python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:$PORTA/api/config', timeout=5)" 2>/dev/null; }
if [ "$SYSTEMD" = 1 ]; then
  for _ in 1 2 3 4 5; do responde && break; sleep 1; done
  responde && ok "Respondendo em http://127.0.0.1:$PORTA" || erro "O Planner não respondeu. Veja: journalctl --user -u $NOME -n 30"
else
  aviso "Sem systemd, o Planner não liga sozinho. Para usar agora: cd \"$DIR\" && python3 server.py"
fi

echo
printf '\033[92m  Pronto! Abra no navegador: http://127.0.0.1:%s\033[0m\n' "$PORTA"
if [ "$HOST" = "0.0.0.0" ]; then
  IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
  echo "  No celular ou em outro PC da mesma rede: http://${IP:-IP-DESTE-COMPUTADOR}:$PORTA"
  if command -v ufw >/dev/null && sudo -n ufw status 2>/dev/null | grep -q "Status: active"; then
    echo "  O firewall (ufw) está ativo. Para liberar só na rede de casa: sudo ufw allow from 192.168.0.0/16 to any port $PORTA proto tcp"
  fi
fi
if [ "$METRICAS" = 1 ] && [ "$COLETA" = 1 ]; then
  echo "  Coleta automática de seguidores (Instagram/YouTube): python3 \"$DIR/coletar_metricas.py\" configurar"
fi
echo "  Mudar as respostas: ./instalar.sh --reconfigurar"
echo
