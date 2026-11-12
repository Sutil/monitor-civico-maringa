"""Coleta contratos publicados no PNCP por um órgão (CNPJ), mês a mês."""
import json, sys, time, urllib.request, urllib.error, datetime as dt, pathlib

BASE = "https://pncp.gov.br/api/consulta/v1/contratos"

def get(url, tries=5):
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                if r.status == 204:
                    return None
                return json.load(r)
        except Exception as e:
            print(f"  erro ({e}); tentativa {i+1}", file=sys.stderr)
            time.sleep(5 * (i + 1))
    raise RuntimeError(url)

def months(start, end):
    d = start.replace(day=1)
    while d <= end:
        nxt = (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        yield max(d, start), min(nxt - dt.timedelta(days=1), end)
        d = nxt

def main(cnpj, ini, fim, out):
    ini = dt.date.fromisoformat(ini); fim = dt.date.fromisoformat(fim)
    rows = []
    for a, b in months(ini, fim):
        page = 1
        while True:
            url = f"{BASE}?dataInicial={a:%Y%m%d}&dataFinal={b:%Y%m%d}&cnpjOrgao={cnpj}&pagina={page}&tamanhoPagina=500"
            js = get(url)
            if not js or not js.get("data"):
                break
            rows += js["data"]
            print(f"{a:%Y-%m} p{page}/{js.get('totalPaginas')}: {len(js['data'])}", file=sys.stderr)
            if page >= (js.get("totalPaginas") or 1):
                break
            page += 1
    pathlib.Path(out).write_text(json.dumps(rows, ensure_ascii=False))
    print(f"total {len(rows)} -> {out}", file=sys.stderr)

if __name__ == "__main__":
    main(*sys.argv[1:5])
