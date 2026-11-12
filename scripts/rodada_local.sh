#!/bin/zsh
# Rodada semanal completa, executada no Mac (o PNCP é lento a partir dos servidores do GitHub).
# Publica no GitHub apenas dados públicos; o site é publicado pelo workflow "Publicar site".
set -euo pipefail
cd "${0:A:h}/.."
mkdir -p data/logs
LOG="data/logs/rodada-$(date +%F).log"
exec > >(tee -a "$LOG") 2>&1
PY=.venv/bin/python
HOJE=$(date +%F)
aviso() { osascript -e "display notification \"$1\" with title \"Monitor Cívico Maringá\"" 2>/dev/null || true; }
trap 'aviso "Rodada falhou — veja $LOG"' ERR

echo "== Rodada $HOJE $(date +%T)"
[ -f .env.local ] && source .env.local   # PLANILHA_ID (não versionado)

# caches antigos expiram para captar aditivos e mudanças cadastrais
mkdir -p data/raw/cnpj data/raw/pncp_detalhes/termos
find data/raw/pncp_detalhes/termos -name '*.json' -mtime +21 -delete
find data/raw/cnpj -name '*.json' -mtime +60 -delete

$PY -I scripts/coleta_pncp.py 76282656000106 2025-01-01 $HOJE data/raw/contratos_prefeitura.json
$PY -I scripts/coleta_pncp.py 77926509000194 2025-01-01 $HOJE data/raw/contratos_camara.json
N=$($PY -I -c "import json;print(len(json.load(open('data/raw/contratos_prefeitura.json'))))")
if [ "$N" -lt 500 ]; then echo "Só $N contratos — PNCP possivelmente fora do ar. Abortando."; false; fi

$PY -I scripts/enriquece_cnpj.py data/raw/contratos_prefeitura.json data/raw/contratos_camara.json
$PY -I scripts/coleta_detalhes.py data/raw/contratos_prefeitura.json data/raw/contratos_camara.json
[ -f data/processed/tse_doacoes_2024.parquet ] || { echo "Falta o TSE processado (ver README)"; false; }

$PY -I scripts/sincroniza_planilha.py pull
$PY -I scripts/analisa.py
$PY -I scripts/sincroniza_planilha.py push

git add data/processed/historico site/src/data
git commit -q -m "Rodada $HOJE" || echo "sem mudanças"
git pull -q --rebase && git push -q
echo "== Fim $(date +%T)"
aviso "Rodada concluída — site será atualizado em instantes"
