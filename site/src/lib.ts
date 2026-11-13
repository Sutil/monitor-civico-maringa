export const brl = (v: number) =>
  v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL', maximumFractionDigits: 0 });
export const mi = (v: number) =>
  v >= 1e9 ? `R$ ${(v / 1e9).toLocaleString('pt-BR', { maximumFractionDigits: 2 })} bi`
  : `R$ ${(v / 1e6).toLocaleString('pt-BR', { maximumFractionDigits: 1 })} mi`;
export const num = (v: number) => v.toLocaleString('pt-BR');
export const data = (iso: string) => new Date(iso + (iso.length === 10 ? 'T12:00:00' : '')).toLocaleDateString('pt-BR');
export const url = (p: string) => `${import.meta.env.BASE_URL.replace(/\/$/, '')}/${p.replace(/^\//, '')}`;

export const STATUS = {
  sem_apontamentos: { nome: 'Sem apontamentos', desc: 'Passou nas verificações automáticas realizadas.', cor: 'ok' },
  em_analise: { nome: 'Em análise', desc: 'Sinal automático aguardando a revisão de um voluntário. Detalhes não são publicados antes da revisão humana.', cor: 'neutro' },
  ponto_de_atencao: { nome: 'Ponto de atenção', desc: 'Revisado por voluntário: fato objetivo que merece explicação do órgão.', cor: 'atencao' },
  esclarecimento_solicitado: { nome: 'Esclarecimento solicitado', desc: 'Pedido formal feito ao órgão (LAI ou ofício), aguardando resposta.', cor: 'atencao' },
  encaminhado: { nome: 'Encaminhado a órgão de controle', desc: 'Representação protocolada no TCE-PR, MP ou CGU.', cor: 'alerta' },
  apuracao_oficial: { nome: 'Apuração oficial em andamento', desc: 'Existe processo público aberto por órgão competente.', cor: 'alerta' },
  esclarecido: { nome: 'Esclarecido / Arquivado', desc: 'O órgão respondeu de forma satisfatória ou o caso foi arquivado.', cor: 'ok' },
} as const;
export type StatusId = keyof typeof STATUS;
