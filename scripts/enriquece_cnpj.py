"""Busca dados cadastrais (Receita Federal) de cada fornecedor PJ, com cache local."""
import json, sys, time, pathlib, urllib.request

CACHE = pathlib.Path("data/raw/cnpj"); CACHE.mkdir(parents=True, exist_ok=True)

def fetch(cnpj):
    f = CACHE / f"{cnpj}.json"
    if f.exists():
        return
    for i in range(4):
        try:
            req = urllib.request.Request(f"https://minhareceita.org/{cnpj}", headers={"User-Agent": "monitor-civico/0.1"})
            with urllib.request.urlopen(req, timeout=60) as r:
                f.write_text(r.read().decode()); return
        except urllib.error.HTTPError as e:
            if e.code == 404:
                f.write_text("{}"); return
            time.sleep(3 * (i + 1))
        except Exception:
            time.sleep(3 * (i + 1))
    print("falhou", cnpj, file=sys.stderr)

cnpjs = set()
for p in sys.argv[1:]:
    for c in json.loads(pathlib.Path(p).read_text()):
        if c.get("tipoPessoa") == "PJ" and c.get("niFornecedor"):
            cnpjs.add(c["niFornecedor"])
print(len(cnpjs), "fornecedores PJ", file=sys.stderr)
for i, c in enumerate(sorted(cnpjs)):
    fetch(c); time.sleep(0.4)
    if i % 50 == 0: print(i, file=sys.stderr)
