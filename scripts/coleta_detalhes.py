"""Para cada contrato: busca a contratação de origem (modalidade, amparo legal) e os termos aditivos. Cache local."""
import json, sys, time, pathlib, urllib.request, urllib.error

API = "https://pncp.gov.br/api/pncp/v1/orgaos"
OUT = pathlib.Path("data/raw/pncp_detalhes"); (OUT/"compras").mkdir(parents=True, exist_ok=True); (OUT/"termos").mkdir(parents=True, exist_ok=True)

def get(url, dest):
    if dest.exists(): return
    for i in range(6):
        try:
            with urllib.request.urlopen(url, timeout=90) as r:
                body = r.read().decode() if r.status != 204 else "[]"
            dest.write_text(body or "[]"); return
        except urllib.error.HTTPError as e:
            if e.code == 404: dest.write_text("null"); return
            time.sleep(30*(i+1) if e.code == 429 else 3*(i+1))
        except Exception:
            time.sleep(3*(i+1))
    print("falhou", url, file=sys.stderr)

def parse(ctrl):  # "76282656000106-1-000431/2024"
    cnpj, _, rest = ctrl.split("-"); seq, ano = rest.split("/")
    return cnpj, int(ano), int(seq)

tasks = []
for p in sys.argv[1:]:
    for c in json.loads(pathlib.Path(p).read_text()):
        cn, a, s = parse(c["numeroControlePncpCompra"])
        tasks.append((f"https://pncp.gov.br/api/consulta/v1/orgaos/{cn}/compras/{a}/{s}", OUT/"compras"/f"{cn}-{a}-{s}.json"))
        cn, a, s = parse(c["numeroControlePNCP"])
        tasks.append((f"{API}/{cn}/contratos/{a}/{s}/termos", OUT/"termos"/f"{cn}-{a}-{s}.json"))
tasks = sorted(dict(tasks).items(), key=lambda t: "termos" in t[0])  # licitações primeiro
print(len(tasks), "requisições", file=sys.stderr)
# O PNCP limita a taxa de requisições (HTTP 429): uma por vez, com pausa.
for i, t in enumerate(tasks):
    if not t[1].exists():
        get(*t); time.sleep(0.6)
    if i % 200 == 0: print(i, file=sys.stderr)
print("ok", file=sys.stderr)
