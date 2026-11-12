"""Sincroniza sinais com a planilha Google de revisão (privada).

  pull: baixa a aba 'revisao' para data/privado/revisao.csv (lida pelo analisa.py)
  push: acrescenta à planilha os sinais novos de data/privado/sinais.csv (nunca altera linhas existentes)

Requer:
  PLANILHA_ID  ID da planilha (compartilhada com a conta de serviço como Editor)
  e uma credencial: GOOGLE_APPLICATION_CREDENTIALS (sem chave, via Workload Identity Federation
  no GitHub Actions) ou GOOGLE_SERVICE_ACCOUNT_JSON (chave JSON; alternativa menos segura).
Sem essas variáveis, o script não faz nada (útil para rodar localmente).
"""
import csv, json, os, sys, pathlib
PRIV = pathlib.Path(__file__).resolve().parent.parent / "data/privado"
COLS = ["caso_id", "status", "justificativa", "revisor", "data_revisao", "protocolo", "processo_link", "resposta_orgao",
        "regra_nome", "orgao", "fornecedor", "fornecedor_doc", "valor_global", "data_assinatura", "fato", "link_pncp",
        "contrato", "objeto", "evidencias", "detectado_em"]

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

def cliente():
    """Autenticação sem chave (Workload Identity Federation, via google-github-actions/auth)
    ou, como alternativa, chave JSON em GOOGLE_SERVICE_ACCOUNT_JSON."""
    import gspread
    if os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON"):
        return gspread.service_account_from_dict(json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]), scopes=SCOPES)
    # Credenciais padrão do Google: no GitHub Actions vêm do Workload Identity Federation;
    # no Mac, de `gcloud auth application-default login --impersonate-service-account=...`.
    import google.auth
    try:
        creds, _ = google.auth.default(scopes=SCOPES)
    except google.auth.exceptions.DefaultCredentialsError:
        return None
    return gspread.authorize(creds)

def sheet():
    sid = os.environ.get("PLANILHA_ID")
    gc = cliente() if sid else None
    if not gc:
        print("Planilha não configurada; pulando."); sys.exit(0)
    import gspread
    sh = gc.open_by_key(sid)
    try:
        return sh.worksheet("revisao")
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet("revisao", rows=1000, cols=len(COLS))
        ws.append_row(COLS)
        prepara(sh, ws)
        return ws

STATUS = ["em_analise", "sem_apontamentos", "ponto_de_atencao", "esclarecimento_solicitado",
          "encaminhado", "apuracao_oficial", "esclarecido"]

def prepara(sh, ws):
    """Cabeçalho fixo em negrito e lista suspensa de status (coluna B)."""
    sid = ws.id
    sh.batch_update({"requests": [
        {"updateSheetProperties": {"properties": {"sheetId": sid, "gridProperties": {"frozenRowCount": 1, "frozenColumnCount": 1}},
                                   "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount"}},
        {"repeatCell": {"range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1},
                        "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}}, "fields": "userEnteredFormat.textFormat.bold"}},
        {"setDataValidation": {"range": {"sheetId": sid, "startRowIndex": 1, "startColumnIndex": 1, "endColumnIndex": 2},
                               "rule": {"condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": s} for s in STATUS]},
                                        "strict": True, "showCustomUi": True}}},
    ]})

def pull():
    rows = sheet().get_all_records()
    PRIV.mkdir(parents=True, exist_ok=True)
    with (PRIV / "revisao.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore"); w.writeheader(); w.writerows(rows)
    print(f"{len(rows)} linhas de revisão baixadas")

def push():
    ws = sheet()
    existentes = set(ws.col_values(1)[1:])
    novos = [r for r in csv.DictReader((PRIV / "sinais.csv").open(encoding="utf-8")) if r["caso_id"] not in existentes]
    if novos:
        ws.append_rows([[r.get(c, "") for c in COLS] for r in novos], value_input_option="RAW")
    print(f"{len(novos)} sinais novos enviados à planilha")

{"pull": pull, "push": push}[sys.argv[1]]()
