"""Triagem por IA dos sinais automáticos (etapa intermediária entre a regra e o veredito humano).

Para cada sinal em data/privado/sinais.csv, o Claude produz: prioridade, resumo em linguagem simples,
explicações legítimas possíveis, o que verificar (com fontes) e uma sugestão
("merece_revisao" ou "provavel_falso_positivo"). A IA NUNCA muda o status público:
o veredito é sempre de um voluntário, registrado na planilha.

Saídas:
  data/privado/triagem/<caso_id>.json  cache por caso (reprocessa só se o sinal mudar)
  data/privado/triagem.json            todos os resultados (lido pela sincronização da planilha)
  site/src/data/triagem.json           só contagens (público)

Credencial: ANTHROPIC_API_KEY (no Mac, lida do Chaves pelo rodada_local.sh). Sem ela, não faz nada.
Uso: python scripts/triagem_ia.py [--max 300]
"""
import argparse, csv, hashlib, json, os, pathlib, sys
from typing import List, Literal

from pydantic import BaseModel, ConfigDict, Field

ROOT = pathlib.Path(__file__).resolve().parent.parent
PRIV = ROOT / "data/privado"
CACHE = PRIV / "triagem"
MODELO = "claude-opus-5-5"


class Triagem(BaseModel):
    model_config = ConfigDict(extra="forbid")  # schema com additionalProperties: false
    prioridade: Literal["alta", "media", "baixa"]
    resumo: str = Field(description="2 a 4 frases, linguagem simples, só fatos verificáveis")
    explicacoes_legitimas: List[str] = Field(description="Explicações lícitas plausíveis para o sinal")
    o_que_verificar: List[str] = Field(description="Passos concretos de verificação, citando a fonte/onde olhar")
    sugestao: Literal["merece_revisao", "provavel_falso_positivo"]
    confianca: Literal["alta", "media", "baixa"]
    justificativa_prioridade: str


SISTEMA = """Você faz a triagem de sinais de um monitor cidadão, independente e apartidário, dos contratos públicos de Maringá-PR.

Cada sinal foi gerado por uma regra automática a partir de dados oficiais (PNCP, Receita Federal, TSE). Seu papel é preparar o caso para um voluntário humano, que dará o veredito. Você não decide nada e nada do que você escrever é publicado.

Princípios:
- Um sinal é um indício estatístico, não uma acusação. Nunca afirme crime, fraude, favorecimento ou má-fé.
- Use só os fatos fornecidos. Não invente números, nomes, datas, normas ou documentos. Se algo depende de informação que você não tem, diga o que falta e onde buscar.
- Considere ativamente explicações legítimas: credenciamentos (valor é teto compartilhado), consórcios públicos, entidades filantrópicas e hospitais, empresas públicas, contratos emergenciais justificados, atas de registro de preço, doações de pequeno valor, homônimos.
- Fontes úteis para verificação: página do contrato no PNCP (link fornecido; editais e anexos ficam lá), Portal da Transparência de Maringá, consulta de CNPJ na Receita, DivulgaCandContas do TSE, diário oficial do município, TCE-PR.

Prioridade:
- alta: valor relevante E fato difícil de explicar por razões comuns, ou combinação de sinais (ex.: empresa nova + doadora + dispensa).
- media: fato relevante, mas com explicações legítimas plausíveis que precisam ser checadas.
- baixa: valor pequeno ou explicação legítima muito provável.

Sugestão "provavel_falso_positivo" só quando a explicação legítima é quase certa com base nos próprios fatos (ex.: fornecedor é consórcio público ou entidade pública). Escreva em português do Brasil."""


def tem_credencial():
    k = os.environ.get("ANTHROPIC_API_KEY", "")
    if k and not k.startswith("sk-ant-"):
        print("Aviso: o valor em ANTHROPIC_API_KEY não parece uma chave da Anthropic (deveria começar com sk-ant-).")
        return False
    return bool(k)


def impressao(s):
    chave = {k: s.get(k) for k in ("regra", "fato", "evidencias", "valor_global", "objeto", "fornecedor")}
    return hashlib.sha1(json.dumps(chave, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def prompt_caso(s, regra, outros):
    linhas = [
        f"Verificação: {s['regra_nome']}",
        f"O que a regra mede: {regra.get('desc', '')}",
        f"Por que importa: {regra.get('por_que', '')}",
        "",
        f"Órgão: {s['orgao']}",
        f"Fornecedor: {s['fornecedor']} ({s['fornecedor_doc']})",
        f"Objeto: {s['objeto']}",
        f"Valor global: R$ {float(s['valor_global'] or 0):,.2f}",
        f"Assinatura: {s['data_assinatura']}",
        f"Contrato no PNCP: {s['link_pncp']}",
        "",
        f"Fato detectado: {s['fato']}",
        f"Evidências (JSON): {s['evidencias']}",
    ]
    if outros:
        linhas += ["", "Outros sinais no MESMO contrato: " + "; ".join(outros)]
    return "\n".join(linhas)


def triar(client, s, regra, outros):
    resp = client.beta.messages.create(
        model=MODELO,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",  # se o modelo recusar, a API refaz com outro modelo automaticamente
        cache_control={"type": "ephemeral"},
        system=SISTEMA,
        output_config={"effort": "medium",
                       "format": {"type": "json_schema", "schema": Triagem.model_json_schema()}},
        messages=[{"role": "user", "content": prompt_caso(s, regra, outros)}],
    )
    if resp.stop_reason == "refusal":
        return None
    texto = next(b.text for b in resp.content if b.type == "text")
    return Triagem.model_validate_json(texto).model_dump()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=300, help="limite de casos novos/alterados por rodada (custo)")
    ap.add_argument("--ids", nargs="*", help="triar só estes caso_id (amostra para avaliação)")
    args = ap.parse_args()

    sinais_f = PRIV / "sinais.csv"
    if not sinais_f.exists():
        print("Sem sinais.csv; rode analisa.py antes."); return
    sinais = list(csv.DictReader(sinais_f.open(encoding="utf-8")))
    regras = json.loads((ROOT / "site/src/data/regras.json").read_text())
    por_contrato = {}
    for s in sinais:
        por_contrato.setdefault(s["contrato"], []).append(s["regra_nome"])

    CACHE.mkdir(parents=True, exist_ok=True)
    pendentes = []
    for s in sinais:
        f = CACHE / f"{s['caso_id']}.json"
        atual = json.loads(f.read_text()) if f.exists() else None
        if not atual or atual.get("_impressao") != impressao(s):
            pendentes.append(s)

    if pendentes and not tem_credencial():
        print(f"{len(pendentes)} sinais aguardam triagem, mas não há credencial da Anthropic; pulando.")
    elif pendentes:
        import anthropic
        # endereço fixo: ignora ANTHROPIC_BASE_URL/AUTH_TOKEN herdados de outras ferramentas
        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"), base_url="https://api.anthropic.com", auth_token=None)
        lote = [s for s in pendentes if s["caso_id"] in set(args.ids)] if args.ids else pendentes[: args.max]
        print(f"Triagem por IA: {len(lote)} de {len(pendentes)} pendentes", flush=True)
        for i, s in enumerate(lote, 1):
            outros = [r for r in por_contrato[s["contrato"]] if r != s["regra_nome"]]
            try:
                r = triar(client, s, regras.get(s["regra"], {}), outros)
            except anthropic.RateLimitError:
                print("  limite de requisições; o restante fica para a próxima rodada", flush=True); break
            except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as e:
                print(f"  credencial recusada ({e.status_code}); triagem interrompida", flush=True); break
            except anthropic.BadRequestError as e:
                if "credit balance" in str(e):
                    print("  sem créditos na conta da Anthropic; triagem interrompida", flush=True); break
                print(f"  {s['caso_id']}: erro {e}; tenta na próxima rodada", flush=True); continue
            except (anthropic.APIConnectionError, anthropic.APIStatusError) as e:
                print(f"  {s['caso_id']}: erro {e}; tenta na próxima rodada", flush=True); continue
            if r is None:
                r = {"prioridade": "media", "resumo": "A IA não conseguiu analisar este caso.", "explicacoes_legitimas": [],
                     "o_que_verificar": [], "sugestao": "merece_revisao", "confianca": "baixa",
                     "justificativa_prioridade": "Triagem indisponível; revisão humana necessária."}
            r |= {"_impressao": impressao(s), "_modelo": MODELO}
            (CACHE / f"{s['caso_id']}.json").write_text(json.dumps(r, ensure_ascii=False, indent=1))
            if i % 10 == 0 or i == len(lote):
                print(f"  {i}/{len(lote)}", flush=True)

    # consolida (só sinais atuais) + contagens públicas
    todos = {}
    for s in sinais:
        f = CACHE / f"{s['caso_id']}.json"
        if f.exists():
            todos[s["caso_id"]] = json.loads(f.read_text())
    (PRIV / "triagem.json").write_text(json.dumps(todos, ensure_ascii=False))
    cont = lambda campo, v: sum(1 for t in todos.values() if t.get(campo) == v)
    publico = {
        "triados": len(todos),
        "aguardando_triagem": len(sinais) - len(todos),
        "prioridade": {p: cont("prioridade", p) for p in ("alta", "media", "baixa")},
        "sugestao": {s: cont("sugestao", s) for s in ("merece_revisao", "provavel_falso_positivo")},
        "modelo": MODELO,
    }
    (ROOT / "site/src/data/triagem.json").write_text(json.dumps(publico, ensure_ascii=False, indent=1))
    print(f"triados={publico['triados']} aguardando={publico['aguardando_triagem']} prioridade={publico['prioridade']}")


if __name__ == "__main__":
    sys.exit(main())
