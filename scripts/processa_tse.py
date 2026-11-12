"""Reduz os CSVs do TSE (PR, 2024) a doações e despesas de campanha de candidatos de Maringá."""
import duckdb, sys
uf_dir, ue = "data/raw/tse", "MARINGÁ"
con = duckdb.connect()
opts = "delim=';', header=true, encoding='latin-1', all_varchar=true"
con.execute(f"""
copy (select SQ_CANDIDATO, NM_CANDIDATO, DS_CARGO, SG_PARTIDO, NR_CPF_CNPJ_DOADOR doador_doc, NM_DOADOR_RFB doador_nome,
             DS_ORIGEM_RECEITA origem, DS_FONTE_RECEITA fonte, strptime(DT_RECEITA,'%d/%m/%Y')::date data,
             replace(VR_RECEITA, ',', '.')::double valor
      from read_csv('{uf_dir}/receitas_candidatos_2024_PR.csv', {opts}) where NM_UE = '{ue}')
to 'data/processed/tse_doacoes_2024.parquet'""")
con.execute(f"""
copy (select SQ_CANDIDATO, NM_CANDIDATO, DS_CARGO, SG_PARTIDO, NR_CPF_CNPJ_FORNECEDOR forn_doc, NM_FORNECEDOR_RFB forn_nome,
             DS_ORIGEM_DESPESA origem, replace(VR_DESPESA_CONTRATADA, ',', '.')::double valor
      from read_csv('{uf_dir}/despesas_contratadas_candidatos_2024_PR.csv', {opts}) where NM_UE = '{ue}')
to 'data/processed/tse_despesas_2024.parquet'""")
print(con.sql("select DS_CARGO, count(distinct SQ_CANDIDATO) cand, count(*) doacoes, round(sum(valor)) total from 'data/processed/tse_doacoes_2024.parquet' group by 1"))
print(con.sql("select count(*) despesas, count(distinct forn_doc) fornecedores from 'data/processed/tse_despesas_2024.parquet'"))
con.execute(f"""
copy (select distinct SQ_CANDIDATO, NM_CANDIDATO, DS_CARGO, SG_PARTIDO, NR_CPF_CANDIDATO cpf
      from read_csv('{uf_dir}/receitas_candidatos_2024_PR.csv', {opts}) where NM_UE = '{ue}')
to 'data/processed/tse_candidatos_2024.parquet'""")
print(con.sql("select count(*) candidatos from 'data/processed/tse_candidatos_2024.parquet'"))
