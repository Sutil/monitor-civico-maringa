# Monitor Cívico Maringá

Monitoramento cidadão, independente e automatizado dos contratos públicos da Prefeitura e da Câmara de Maringá (PR).

- **Dados:** PNCP (contratos, licitações, aditivos) · Receita Federal (CNPJ, via minhareceita.org) · TSE (contas de campanha 2024)
- **Pipeline:** Python + DuckDB, rodando toda semana no GitHub Actions
- **Site:** Astro (estático) + Observable Plot + Pagefind, publicado no GitHub Pages
- **Revisão humana:** planilha Google privada; nada é detalhado no site sem revisão

## Princípios

1. Sinais automáticos são indícios, **não acusações**.
2. Enquanto um caso está *Em análise*, o público vê apenas contagens.
3. Classificamos atos (contratos), não pessoas. CPFs sempre mascarados.
4. Todo fato tem link para a fonte oficial; toda correção é registrada.

## Estrutura

```
scripts/
  coleta_pncp.py          contratos por órgão (CNPJ), mês a mês
  coleta_detalhes.py      licitação de origem + termos aditivos de cada contrato
  enriquece_cnpj.py       dados cadastrais dos fornecedores
  processa_tse.py         reduz os CSVs do TSE a Maringá
  analisa.py              regras → sinais (privado) + agregados (público)
  sincroniza_planilha.py  pull/push com a planilha de revisão
site/                     Astro; lê site/src/data/*.json
data/processed/historico  contagens e IDs de cada rodada (público)
data/raw, data/privado    NUNCA versionados (.gitignore)
```

## Rodar localmente

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/coleta_pncp.py 76282656000106 2025-01-01 $(date +%F) data/raw/contratos_prefeitura.json
.venv/bin/python scripts/coleta_pncp.py 77926509000194 2025-01-01 $(date +%F) data/raw/contratos_camara.json
.venv/bin/python scripts/enriquece_cnpj.py data/raw/contratos_*.json
.venv/bin/python scripts/coleta_detalhes.py data/raw/contratos_*.json
# TSE: baixe e descompacte receitas/despesas PR 2024 em data/raw/tse (ver workflow) e rode:
.venv/bin/python scripts/processa_tse.py
.venv/bin/python scripts/analisa.py
cd site && npm install && npm run dev
```

## Configurar no GitHub

1. **Pages:** Settings → Pages → Source: *GitHub Actions*.
2. **Planilha de revisão:** crie uma conta de serviço no Google Cloud (API Google Sheets ativada), compartilhe a planilha com o e-mail dela como *Editor* e cadastre os secrets:
   - `GOOGLE_SERVICE_ACCOUNT_JSON` — conteúdo do JSON da chave
   - `PLANILHA_ID` — o ID na URL da planilha
3. **Rodar:** Actions → *Coleta semanal e publicação* → *Run workflow*.
4. Ajuste `site/src/config.ts` (e-mail, formulário de voluntários, repositório).

## Status de revisão (coluna `status` da planilha)

| valor | exige |
|---|---|
| `em_analise` | — |
| `sem_apontamentos` | justificativa, revisor |
| `ponto_de_atencao` | justificativa, revisor |
| `esclarecimento_solicitado` | justificativa, revisor, protocolo |
| `encaminhado` | justificativa, revisor, protocolo |
| `apuracao_oficial` | justificativa, revisor, processo_link |
| `esclarecido` | justificativa, revisor |

Linhas que não cumprem a exigência ficam *Em análise* e geram aviso no log da rodada.
