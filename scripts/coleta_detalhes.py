"""Para cada contrato: busca a contratação de origem (modalidade, amparo legal) e os termos aditivos. Cache local.

Para economizar consultas (o PNCP é lento), os termos aditivos só são buscados quando o contrato
teve atualização posterior à publicação (dataAtualizacaoGlobal > dataAtualizacao), e só de novo
quando essa data muda em relação ao cache. Validação: 40 de 41 contratos com aditivo detectados.
"""
import datetime as dt, json, os, sys, time, pathlib, urllib.request, urllib.error

OUT = pathlib.Path("data/raw/pncp_detalhes"); (OUT/"compras").mkdir(parents=True, exist_ok=True); (OUT/"termos").mkdir(parents=True, exist_ok=True)

def get(url, dest):
    for i in range(6):
        try:
            with urllib.request.urlopen(url, timeout=90) as r:
                body = r.read().decode() if r.status != 204 else "[]"
            dest.write_text(body or "[]"); return True
        except urllib.error.HTTPError as e:
            if e.code == 404: dest.write_text("null"); return True
            time.sleep(30*(i+1) if e.code == 429 else 3*(i+1))
        except Exception:
            time.sleep(3*(i+1))
    print("falhou", url, file=sys.stderr, flush=True); return False

def parse(ctrl):  # "76282656000106-1-000431/2024"
    cnpj, _, rest = ctrl.split("-"); seq, ano = rest.split("/")
    return cnpj, int(ano), int(seq)

def ts(s):
    return dt.datetime.fromisoformat(s).timestamp() if s else 0

pend = {}
for p in sys.argv[1:]:
    for c in json.loads(pathlib.Path(p).read_text()):
        cn, a, s = parse(c["numeroControlePncpCompra"])
        dest = OUT/"compras"/f"{cn}-{a}-{s}.json"
        if not dest.exists():
            pend[dest] = f"https://pncp.gov.br/api/consulta/v1/orgaos/{cn}/compras/{a}/{s}"
        glob_, prop = c.get("dataAtualizacaoGlobal") or "", c.get("dataAtualizacao") or ""
        if glob_[:16] > prop[:16]:  # houve atualização posterior (aditivo, apostilamento...)
            cn, a, s = parse(c["numeroControlePNCP"])
            dest = OUT/"termos"/f"{cn}-{a}-{s}.json"
            if not dest.exists() or dest.stat().st_mtime < ts(glob_):
                pend[dest] = f"https://pncp.gov.br/api/pncp/v1/orgaos/{cn}/contratos/{a}/{s}/termos"

tarefas = sorted(pend.items(), key=lambda t: "termos" in str(t[0]))  # licitações primeiro
n = len(tarefas); ini = time.time()
print(f"{n} consultas pendentes (o resto está em cache)", file=sys.stderr, flush=True)
for i, (dest, url) in enumerate(tarefas, 1):
    get(url, dest); time.sleep(0.6)
    if i % 25 == 0 or i == n:
        seg = (time.time() - ini) / i * (n - i)
        print(f"  {i}/{n} — faltam ~{seg/60:.0f} min", file=sys.stderr, flush=True)
print("ok", file=sys.stderr)
