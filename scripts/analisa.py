"""Motor de regras do Monitor Cívico Maringá.

Lê os dados coletados, aplica as regras de sinalização e gera:
  - data/privado/sinais.csv      -> TODOS os sinais com detalhes (NÃO publicar; vai para a planilha de revisão)
  - site/src/data/*.json         -> apenas agregados e casos já revisados (público)

Princípios (ver /metodologia no site):
  * Sinais automáticos são indícios estatísticos, não acusações.
  * Nada sai de "em_analise" sem revisão humana registrada na planilha.
  * CPFs nunca são publicados por inteiro.
"""
import csv, datetime as dt, glob, hashlib, json, pathlib, re, unicodedata
import duckdb

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW, PROC, PRIV = ROOT / "data/raw", ROOT / "data/processed", ROOT / "data/privado"
SITE_DATA = ROOT / "site/src/data"
for p in (PROC, PRIV, SITE_DATA):
    p.mkdir(parents=True, exist_ok=True)
HOJE = dt.date.today()

ORGAOS = {
    "76282656000106": {"nome": "Prefeitura de Maringá", "arquivo": "contratos_prefeitura.json"},
    "77926509000194": {"nome": "Câmara Municipal de Maringá", "arquivo": "contratos_camara.json"},
}

# Limites de dispensa por valor (Lei 14.133/2021, art. 75, I e II), atualizados por decreto anual.
# Valores vigentes em 2025 (Decreto 12.343/2024). CONFERIR e atualizar a cada ano.
LIMITE_DISPENSA = {"obras": 125_451.15, "outros": 62_725.59}

REGRAS = {
    "empresa_recente": {
        "nome": "Empresa recém-aberta",
        "desc": "Fornecedor com CNPJ aberto há menos de 180 dias na data de assinatura do contrato.",
        "por_que": "Empresas criadas pouco antes de contratar com o poder público podem indicar empresa de fachada ou direcionamento — mas também podem ser negócios legítimos novos.",
        "fontes": ["PNCP", "Receita Federal"],
    },
    "capital_incompativel": {
        "nome": "Capital social baixo para o contrato",
        "desc": "Empresa com capital social inferior a 10% do valor do contrato, em contratos acima de R$ 200 mil.",
        "por_que": "Pode indicar baixa capacidade econômica para executar o contrato. Capital social é declaratório e nem sempre reflete a capacidade real.",
        "fontes": ["PNCP", "Receita Federal"],
    },
    "situacao_irregular": {
        "nome": "CNPJ não ativo",
        "desc": "Fornecedor com situação cadastral diferente de 'Ativa' na Receita Federal na data da verificação.",
        "por_que": "Empresas baixadas, inaptas ou suspensas não deveriam manter contratos ativos.",
        "fontes": ["Receita Federal"],
    },
    "doador_fornecedor": {
        "nome": "Doador de campanha contratado",
        "desc": "A empresa, ou um de seus sócios, doou para campanha de candidato em Maringá em 2024.",
        "por_que": "Doação não é ilegal, mas a relação entre financiamento de campanha e contratos públicos merece acompanhamento.",
        "fontes": ["PNCP", "Receita Federal", "TSE"],
    },
    "candidato_socio": {
        "nome": "Candidato é sócio ou fornecedor",
        "desc": "Candidato das eleições municipais de 2024 em Maringá aparece como sócio da empresa contratada, ou é o próprio fornecedor pessoa física.",
        "por_que": "Agentes eleitos têm restrições para contratar com o município (CF art. 54 e Lei Orgânica). Para candidatos não eleitos, não há impedimento.",
        "fontes": ["PNCP", "Receita Federal", "TSE"],
    },
    "fornecedor_campanha": {
        "nome": "Fornecedor de campanha contratado",
        "desc": "Empresa que prestou serviços a campanhas em Maringá em 2024 e depois foi contratada pelo órgão.",
        "por_que": "Relação comercial prévia com campanhas pode merecer atenção, especialmente em contratações sem licitação.",
        "fontes": ["PNCP", "TSE"],
    },
    "dispensa_fracionada": {
        "nome": "Possível fracionamento de dispensa",
        "desc": "Mesmo fornecedor com várias contratações por dispensa no mesmo ano e categoria, cuja soma passa do limite legal de dispensa por valor.",
        "por_que": "Dividir uma compra em partes menores para evitar licitação é vedado (Lei 14.133, art. 75, §1º). Pode haver justificativa legítima.",
        "fontes": ["PNCP"],
    },
    "aditivo_acima_limite": {
        "nome": "Aditivos acima de 25%",
        "desc": "Soma dos acréscimos por termo aditivo supera 25% do valor inicial (50% para obras/engenharia).",
        "por_que": "A Lei 14.133 (art. 125) limita acréscimos a 25% (50% em reforma). Acima disso, só com justificativa específica.",
        "fontes": ["PNCP"],
    },
}


def norm(s):
    s = unicodedata.normalize("NFKD", (s or "").upper())
    return re.sub(r"[^A-Z ]", "", "".join(c for c in s if not unicodedata.combining(c))).strip()


def mascara_cpf(cpf):
    d = re.sub(r"\D", "", cpf or "")
    return f"***.{d[3:6]}.{d[6:9]}-**" if len(d) == 11 else "***"


def doc_publico(doc, tipo):
    return mascara_cpf(doc) if tipo == "PF" else doc


def link_contrato(ctrl):  # 76282656000106-2-000538/2024
    cnpj, _, rest = ctrl.split("-")
    seq, ano = rest.split("/")
    return f"https://pncp.gov.br/app/contratos/{cnpj}/{ano}/{int(seq)}"


def caso_id(regra, ctrl):
    return regra[:3].upper() + "-" + hashlib.sha1(f"{regra}|{ctrl}".encode()).hexdigest()[:8]


def load_json(p, default=None):
    try:
        return json.loads(pathlib.Path(p).read_text())
    except Exception:
        return default


# ---------------------------------------------------------------- carga
contratos = []
for cnpj_org, org in ORGAOS.items():
    for c in load_json(RAW / org["arquivo"], []):
        c["_orgao"] = org["nome"]
        contratos.append(c)

cnpj_info = {pathlib.Path(f).stem: load_json(f, {}) or {} for f in glob.glob(str(RAW / "cnpj/*.json"))}


def detalhe(tipo, ctrl):
    cnpj, _, rest = ctrl.split("-")
    seq, ano = rest.split("/")
    return load_json(RAW / f"pncp_detalhes/{tipo}/{cnpj}-{int(ano)}-{int(seq)}.json")


con = duckdb.connect()
doacoes = con.sql(f"select * from '{PROC}/tse_doacoes_2024.parquet'").fetchall()
cols_d = [d[0] for d in con.sql(f"select * from '{PROC}/tse_doacoes_2024.parquet' limit 0").description]
doacoes = [dict(zip(cols_d, r)) for r in doacoes]
candidatos = [dict(zip(["sq", "nome", "cargo", "partido", "cpf"], r)) for r in
              con.sql(f"select SQ_CANDIDATO, NM_CANDIDATO, DS_CARGO, SG_PARTIDO, cpf from '{PROC}/tse_candidatos_2024.parquet'").fetchall()]
desp = con.sql(f"select forn_doc, count(*) n, sum(valor) v, string_agg(distinct NM_CANDIDATO, '; ') cands from '{PROC}/tse_despesas_2024.parquet' group by 1").fetchall()
forn_campanha = {r[0]: {"n": r[1], "valor": r[2], "cands": r[3]} for r in desp}

# Índices de doadores: por documento completo e por (nome normalizado, 6 dígitos centrais do CPF)
doador_por_doc, doador_por_nome_cpf = {}, {}
for d in doacoes:
    if d["origem"] in ("Recursos de partido político", "Recursos de outros candidatos", "Recursos próprios"):
        continue  # interessa o doador privado externo à campanha
    doc = re.sub(r"\D", "", d["doador_doc"] or "")
    doador_por_doc.setdefault(doc, []).append(d)
    if len(doc) == 11:
        doador_por_nome_cpf.setdefault((norm(d["doador_nome"]), doc[3:9]), []).append(d)
cand_por_cpf = {re.sub(r"\D", "", c["cpf"] or ""): c for c in candidatos}
cand_por_nome_cpf = {(norm(c["nome"]), k[3:9]): c for k, c in cand_por_cpf.items() if len(k) == 11}

# ---------------------------------------------------------------- regras
sinais = []
verificados = {}  # ctrl -> conjunto de regras que puderam ser avaliadas


def sinal(regra, c, fato, evid):
    sinais.append({
        "caso_id": caso_id(regra, c["numeroControlePNCP"]),
        "regra": regra,
        "regra_nome": REGRAS[regra]["nome"],
        "orgao": c["_orgao"],
        "contrato": c["numeroControlePNCP"],
        "link_pncp": link_contrato(c["numeroControlePNCP"]),
        "fornecedor": c["nomeRazaoSocialFornecedor"],
        "fornecedor_doc": doc_publico(c["niFornecedor"], c["tipoPessoa"]),
        "objeto": (c.get("objetoContrato") or "")[:300],
        "valor_global": c.get("valorGlobal") or 0,
        "data_assinatura": c.get("dataAssinatura"),
        "fato": fato,
        "evidencias": json.dumps(evid, ensure_ascii=False, default=str),
        "detectado_em": HOJE.isoformat(),
        "status": "em_analise",
    })


# agrupamento p/ fracionamento
dispensas = {}

for c in contratos:
    ctrl, doc, tipo = c["numeroControlePNCP"], c["niFornecedor"], c["tipoPessoa"]
    valor = c.get("valorGlobal") or 0
    assin = dt.date.fromisoformat(c["dataAssinatura"]) if c.get("dataAssinatura") else None
    feitas = verificados.setdefault(ctrl, set())
    info = cnpj_info.get(doc) if tipo == "PJ" else None
    compra = detalhe("compras", c["numeroControlePncpCompra"])
    credenciamento = bool(compra) and compra.get("modalidadeId") == 12  # valor é teto compartilhado, não por fornecedor

    if info:
        feitas |= {"empresa_recente", "capital_incompativel", "situacao_irregular"}
        ini = info.get("data_inicio_atividade")
        if ini and assin:
            dias = (assin - dt.date.fromisoformat(ini)).days
            if 0 <= dias < 180:
                sinal("empresa_recente", c, f"CNPJ aberto em {ini}, {dias} dias antes da assinatura do contrato ({assin}).",
                      {"data_abertura": ini, "dias": dias})
        nat = str(info.get("codigo_natureza_juridica") or "")
        cap = info.get("capital_social") or 0
        if nat.startswith("2") and not credenciamento and valor >= 200_000 and cap < 0.10 * valor:
            sinal("capital_incompativel", c,
                  f"Capital social declarado de R$ {cap:,.2f} para contrato de R$ {valor:,.2f} ({cap / valor:.1%}).",
                  {"capital_social": cap, "valor": valor})
        sit = info.get("descricao_situacao_cadastral")
        if sit and sit.upper() != "ATIVA":
            sinal("situacao_irregular", c, f"Situação cadastral na Receita: {sit} (desde {info.get('data_situacao_cadastral')}).",
                  {"situacao": sit, "data": info.get("data_situacao_cadastral")})

    # doações e candidatos
    feitas |= {"doador_fornecedor", "candidato_socio", "fornecedor_campanha"}
    achados_doacao = list(doador_por_doc.get(doc, []))
    socios_cand = []
    if tipo == "PF" and doc in cand_por_cpf:
        socios_cand.append({"candidato": cand_por_cpf[doc]["nome"], "cargo": cand_por_cpf[doc]["cargo"], "papel": "fornecedor pessoa física"})
    for s in (info or {}).get("qsa") or []:
        k = (norm(s.get("nome_socio")), re.sub(r"\D", "", s.get("cnpj_cpf_do_socio") or "")[:6])
        if k in doador_por_nome_cpf:
            achados_doacao += [dict(d, via_socio=s.get("nome_socio")) for d in doador_por_nome_cpf[k]]
        if k in cand_por_nome_cpf:
            cd = cand_por_nome_cpf[k]
            socios_cand.append({"candidato": cd["nome"], "cargo": cd["cargo"], "papel": f"sócio ({s.get('qualificacao_socio')})"})
    if achados_doacao:
        tot = sum(d["valor"] or 0 for d in achados_doacao)
        cands = sorted({f"{d['NM_CANDIDATO']} ({d['DS_CARGO']})" for d in achados_doacao})
        quem = "sócio(s) da empresa" if any("via_socio" in d for d in achados_doacao) else "a empresa"
        sinal("doador_fornecedor", c, f"Em 2024, {quem} doou R$ {tot:,.2f} para: {', '.join(cands)}.",
              [{"candidato": d["NM_CANDIDATO"], "cargo": d["DS_CARGO"], "valor": d["valor"], "data": d["data"],
                "via_socio": d.get("via_socio")} for d in achados_doacao])
    if socios_cand:
        sinal("candidato_socio", c, "; ".join(f"{x['candidato']} ({x['cargo']}, 2024) — {x['papel']}" for x in socios_cand) + ".", socios_cand)
    if doc in forn_campanha:
        f = forn_campanha[doc]
        sinal("fornecedor_campanha", c, f"Prestou {f['n']} serviço(s) a campanhas em 2024 (R$ {f['valor']:,.2f}): {f['cands']}.", f)

    # contratação de origem
    if compra:
        c["_modalidade"] = compra.get("modalidadeNome")
        if compra.get("modalidadeId") == 8 and assin:  # Dispensa
            cat = "obras" if (c.get("categoriaProcesso") or {}).get("nome", "") in ("Obras", "Serviços de Engenharia") else "outros"
            dispensas.setdefault((doc, assin.year, cat), []).append(c)
    termos = detalhe("termos", ctrl)
    if termos is not None:
        feitas.add("aditivo_acima_limite")
        acresc = sum((t.get("valorAcrescido") or 0) for t in termos if t.get("qualificacaoAcrescimoSupressao"))
        ini_v = c.get("valorInicial") or 0
        lim = 0.50 if (c.get("categoriaProcesso") or {}).get("nome") in ("Obras", "Serviços de Engenharia") else 0.25
        if ini_v > 0 and acresc > lim * ini_v:
            sinal("aditivo_acima_limite", c,
                  f"Acréscimos por aditivo somam R$ {acresc:,.2f} ({acresc / ini_v:.0%} do valor inicial de R$ {ini_v:,.2f}); referência legal: {lim:.0%}.",
                  {"acrescimos": acresc, "valor_inicial": ini_v, "n_termos": len(termos)})

for (doc, ano, cat), cs in dispensas.items():
    for c in cs:
        verificados[c["numeroControlePNCP"]].add("dispensa_fracionada")
    tot = sum(c.get("valorGlobal") or 0 for c in cs)
    if len(cs) >= 2 and tot > LIMITE_DISPENSA[cat]:
        for c in cs:
            sinal("dispensa_fracionada", c,
                  f"{len(cs)} contratações por dispensa com o mesmo fornecedor em {ano} ({cat}), somando R$ {tot:,.2f}; limite de referência R$ {LIMITE_DISPENSA[cat]:,.2f}.",
                  {"n": len(cs), "total": tot, "contratos": [x["numeroControlePNCP"] for x in cs]})

# ---------------------------------------------------------------- revisão humana (planilha exportada em CSV)
REVISAO = PRIV / "revisao.csv"
STATUS_VALIDOS = {"em_analise", "sem_apontamentos", "ponto_de_atencao", "esclarecimento_solicitado",
                  "encaminhado", "apuracao_oficial", "esclarecido"}
EXIGE = {
    "ponto_de_atencao": ["justificativa", "revisor"],
    "esclarecimento_solicitado": ["justificativa", "revisor", "protocolo"],
    "encaminhado": ["justificativa", "revisor", "protocolo"],
    "apuracao_oficial": ["justificativa", "revisor", "processo_link"],
    "esclarecido": ["justificativa", "revisor"],
    "sem_apontamentos": ["justificativa", "revisor"],
}
revisoes, avisos = {}, []
if REVISAO.exists():
    for r in csv.DictReader(REVISAO.open(encoding="utf-8")):
        st = (r.get("status") or "").strip()
        if st not in STATUS_VALIDOS:
            avisos.append(f"{r.get('caso_id')}: status inválido '{st}'"); continue
        faltando = [k for k in EXIGE.get(st, []) if not (r.get(k) or "").strip()]
        if faltando:
            avisos.append(f"{r.get('caso_id')}: '{st}' exige {', '.join(faltando)} — mantido em análise"); continue
        revisoes[r["caso_id"]] = r

# planilha completa (privada): sinais + colunas de revisão preservadas
CAMPOS_REV = ["status", "justificativa", "revisor", "data_revisao", "protocolo", "processo_link", "resposta_orgao"]
with (PRIV / "sinais.csv").open("w", newline="", encoding="utf-8") as f:
    campos = list(sinais[0].keys()) + [k for k in CAMPOS_REV if k != "status"] if sinais else ["caso_id"]
    w = csv.DictWriter(f, fieldnames=campos)
    w.writeheader()
    for s in sinais:
        rv = revisoes.get(s["caso_id"], {})
        w.writerow({**s, **{k: rv.get(k, s.get(k, "")) for k in CAMPOS_REV}})

# ---------------------------------------------------------------- saídas públicas
for s in sinais:
    s["status"] = revisoes.get(s["caso_id"], {}).get("status", "em_analise")

publicos = []
for s in sinais:
    if s["status"] == "em_analise":
        continue
    rv = revisoes[s["caso_id"]]
    publicos.append({k: s[k] for k in ("caso_id", "regra", "regra_nome", "orgao", "contrato", "link_pncp", "fornecedor",
                                       "fornecedor_doc", "objeto", "valor_global", "data_assinatura", "fato", "status")}
                    | {k: rv.get(k, "") for k in ("justificativa", "data_revisao", "protocolo", "processo_link", "resposta_orgao")})

contratos_com_sinal = {s["contrato"] for s in sinais}
# "Sem apontamentos": nenhum sinal E todas as verificações aplicáveis puderam ser feitas
# (PJ precisa ter os dados da Receita; PF dispensa as regras de CNPJ).
NUCLEO = {"doador_fornecedor", "candidato_socio", "fornecedor_campanha", "aditivo_acima_limite"}
CNPJ_REGRAS = {"empresa_recente", "capital_incompativel", "situacao_irregular"}
tipo_por_ctrl = {c["numeroControlePNCP"]: c["tipoPessoa"] for c in contratos}
sem_apont = sum(1 for c, r in verificados.items() if c not in contratos_com_sinal and NUCLEO <= r
                and (tipo_por_ctrl[c] != "PJ" or CNPJ_REGRAS <= r))

por_cat, por_mes, por_org, por_mod = {}, {}, {}, {}
for c in contratos:
    v = c.get("valorGlobal") or 0
    cat = (c.get("categoriaProcesso") or {}).get("nome") or "Outros"
    por_cat[cat] = por_cat.get(cat, 0) + v
    m = (c.get("dataAssinatura") or "")[:7]
    if m >= "2025-01":
        por_mes.setdefault(m, {"mes": m, "n": 0, "valor": 0}); por_mes[m]["n"] += 1; por_mes[m]["valor"] += v
    o = por_org.setdefault(c["_orgao"], {"orgao": c["_orgao"], "n": 0, "valor": 0}); o["n"] += 1; o["valor"] += v
    mod = c.get("_modalidade") or "Não informada"
    md = por_mod.setdefault(mod, {"modalidade": mod, "n": 0, "valor": 0}); md["n"] += 1; md["valor"] += v

top_forn = {}
for c in contratos:
    k = c["niFornecedor"]
    t = top_forn.setdefault(k, {"fornecedor": c["nomeRazaoSocialFornecedor"], "doc": doc_publico(k, c["tipoPessoa"]), "n": 0, "valor": 0})
    t["n"] += 1; t["valor"] += c.get("valorGlobal") or 0

status_cont = {}
for s in sinais:
    status_cont[s["status"]] = status_cont.get(s["status"], 0) + 1

resumo = {
    "gerado_em": dt.datetime.now().isoformat(timespec="minutes"),
    "periodo": {"inicio": min(c["dataAssinatura"] for c in contratos), "fim": max(c["dataAssinatura"] for c in contratos)},
    "contratos": len(contratos),
    "fornecedores": len({c["niFornecedor"] for c in contratos}),
    "valor_total": sum(c.get("valorGlobal") or 0 for c in contratos),
    "por_orgao": sorted(por_org.values(), key=lambda x: -x["valor"]),
    "por_categoria": sorted([{"categoria": k, "valor": v} for k, v in por_cat.items()], key=lambda x: -x["valor"]),
    "por_mes": sorted(por_mes.values(), key=lambda x: x["mes"]),
    "por_modalidade": sorted(por_mod.values(), key=lambda x: -x["valor"]),
    "top_fornecedores": sorted(top_forn.values(), key=lambda x: -x["valor"])[:15],
    "sinais_total": len(sinais),
    "contratos_com_sinal": len(contratos_com_sinal),
    "sem_apontamentos": sem_apont,
    "status": status_cont,
    "sinais_por_regra": [{"regra": k, "nome": v["nome"], "n": sum(1 for s in sinais if s["regra"] == k)} for k, v in REGRAS.items()],
    "fontes": [
        {"nome": "PNCP — Portal Nacional de Contratações Públicas", "url": "https://pncp.gov.br", "atualizado": HOJE.isoformat(), "uso": "contratos, licitações e aditivos"},
        {"nome": "Receita Federal — CNPJ (via minhareceita.org)", "url": "https://minhareceita.org", "atualizado": HOJE.isoformat(), "uso": "abertura, capital social, sócios e situação"},
        {"nome": "TSE — Prestação de contas eleitorais 2024", "url": "https://dadosabertos.tse.jus.br", "atualizado": "2026-11-11", "uso": "doações e despesas de campanha"},
    ],
}
(SITE_DATA / "resumo.json").write_text(json.dumps(resumo, ensure_ascii=False, indent=1))
(SITE_DATA / "casos.json").write_text(json.dumps(publicos, ensure_ascii=False, indent=1))
(SITE_DATA / "regras.json").write_text(json.dumps(REGRAS | {"_limite_dispensa": LIMITE_DISPENSA}, ensure_ascii=False, indent=1))

# relatório da rodada (público: apenas números)
hist = PROC / "historico"; hist.mkdir(exist_ok=True)
ant_f = sorted(f for f in hist.glob("*.json") if f.stem < HOJE.isoformat())
ant = load_json(ant_f[-1]) if ant_f else None
rel = {
    "data": HOJE.isoformat(),
    "contratos": len(contratos),
    "contratos_novos": len(contratos) - (ant["contratos"] if ant else 0) if ant else len(contratos),
    "sinais_total": len(sinais),
    "sinais_novos": len({s["caso_id"] for s in sinais} - set(ant.get("ids", []))) if ant else len(sinais),
    "sinais_por_regra": resumo["sinais_por_regra"],
    "status": status_cont,
    "revisados_publicados": len(publicos),
    "primeira_rodada": ant is None,
}
(hist / f"{HOJE.isoformat()}.json").write_text(json.dumps(rel | {"ids": [s["caso_id"] for s in sinais]}, ensure_ascii=False))
relatorios = [{k: v for k, v in load_json(f).items() if k != "ids"} for f in sorted(hist.glob("*.json"), reverse=True)]
(SITE_DATA / "relatorios.json").write_text(json.dumps(relatorios, ensure_ascii=False, indent=1))

print(f"contratos={len(contratos)} sinais={len(sinais)} contratos_com_sinal={len(contratos_com_sinal)} publicos={len(publicos)}")
for r in resumo["sinais_por_regra"]:
    print(f"  {r['nome']}: {r['n']}")
for a in avisos:
    print("AVISO revisão:", a)
