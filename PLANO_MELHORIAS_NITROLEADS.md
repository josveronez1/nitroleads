# Plano de Melhorias - NitroLeads (Relatório 06.02.26)

Plano consolidado com todas as decisões tomadas para corrigir bugs e melhorar a robustez do produto.

---

## 1. Discrepância: 40 Resultados vs 32 Créditos/Leads

**Problema:** O sistema mostra "40 resultados" mas cobra 32 créditos e exibe menos leads na tabela.

**Causa:** `LeadAccess` tem `unique_together = [['user', 'lead']]`. Quando leads vêm do cache e o usuário já tinha acesso, o registro antigo não é vinculado à busca atual, então não aparece em `search.lead_accesses`.

**Solução (Opção A - aprovada):** Criar modelo `SearchLead(search, lead)` como tabela de junção.

### Implementação

- Criar modelo `SearchLead(search, lead)` – tabela de junção
- Ao processar a busca, criar `SearchLead` para cada lead retornado
- Listagem usa `SearchLead` em vez de `LeadAccess` para exibir resultados
- `results_count` = contagem de `SearchLead` para a busca
- `LeadAccess` continua para débito de créditos (primeira vez que o usuário acessa o lead)

### Regras de deduplicação (definidas)

1. **Exclusão nas últimas 3 buscas:** O usuário NÃO deve receber o mesmo Lead se ele estiver em qualquer uma de suas **últimas 3 pesquisas** (exceto a atual). Se o lead NÃO estiver nas últimas 3, pode ser retornado novamente.

2. **Fonte dos dados irrelevante:** Se o lead vem do banco interno (cache) ou de pesquisa em tempo real, isso é estratégia interna. O usuário sempre recebe o lead desde que não esteja nas últimas 3 buscas.

3. **Sempre tentar atingir a quantidade solicitada:** Se o sistema identificar que faltaram leads após aplicar os filtros, deve continuar buscando (Serper, cache incremental, etc.) até atingir o número solicitado ou esgotar as opções.

### Implementação técnica

- Consultar `SearchLead` das últimas 3 buscas do usuário (exceto a atual) para obter CNPJs a excluir
- Ao buscar leads (cache ou Serper), filtrar os que já estão nessas 3 buscas
- Se `len(results) < quantity`, continuar buscando até preencher ou esgotar
- Criar `SearchLead` para cada lead retornado

---

## 2. Quadro Societário – Exposição indevida de contatos

**Problema:** Ao buscar quadro societário de empresas do banco interno, a plataforma exibe nomes + contatos. O correto é exibir apenas nomes e CPFs; contatos só após "Buscar informações dos sócios" (CPF enrichment).

**Causa:** A API Viper ou dados em cache podem trazer socios com telefones/emails. Esses campos são persistidos sem filtro.

**Solução**

1. **Função central** – Criar `sanitize_socios_for_storage(data)` em `services.py`:
   - Aceita a estrutura retornada pela API
   - Retorna socios apenas com NOME, CARGO, DOCUMENTO (e variantes: CPF, qualificacao)
   - Remove: telefones, emails, TELEFONE, cpf_data, telefones_fixos, telefones_moveis, whatsapps e similares

2. **Onde aplicar:**
   - `process_viper_queue.py` – após normalizar resultado, antes de salvar em `lead.viper_data['socios_qsa']`
   - `views.py` (search_partners) – ao montar `partners` no JSON de resposta

---

## 3. Nichos e localizações – Nem todas as opções carregam

**Problema:** O sistema não carrega todas as opções de nicho e localização, só algumas inicialmente.

**Situação atual:** API retorna até 200 registros quando `q` vazio; dashboard chama a API só no focus do input.

**Solução**

1. Aumentar limite (ex.: 500–1000) ou implementar paginação
2. Carregar nichos e localizações no `DOMContentLoaded` (não só no focus)
3. Garantir que search_history e demais páginas usem o mesmo mecanismo

---

## 4. Base de Dados – Atualização em tempo real durante a busca

**Problema:** Enquanto a pesquisa está sendo feita, a página fica estática. O usuário precisa recarregar para ver os leads.

**Situação atual:** Polling só chama `api_search_leads` quando `status === 'completed'`. Backend só salva `results_count` e `credits_used` no final.

**Solução**

1. **Backend:** Em `process_search_async`, atualizar `search_obj.results_count` e `search_obj.credits_used` incrementalmente (a cada lote de leads processados)
2. **Frontend:** Durante `status === 'processing'`, chamar `api_search_leads` periodicamente (ex.: a cada 3–5 s) para atualizar a tabela
3. Só atualizar tabela quando o collapse estiver expandido ou modal fullscreen aberto
4. Atualizar badges `results_count` e `credits_used` durante o processamento

---

## 5. Regras de negócio – Resumo

| Regra | Comportamento esperado |
|-------|------------------------|
| Resultados vs créditos | `results_count` = leads exibidos. `credits_used` = créditos debitados. Consistentes com a tabela. |
| Quadro societário | Primeiro: nomes e CPFs. Contatos só após "Buscar informações dos sócios". |
| Fonte dos dados | API ou cache: transparente para o usuário. Contatos só após enriquecimento pago. |
| Deduplicação | Excluir leads que estão nas últimas 3 buscas do usuário. |
| Quantidade | Sempre tentar atingir o número solicitado; continuar buscando se faltar. |
| Autocomplete | Todas as opções de nicho e localização carregáveis. |
| Busca em andamento | Tabela e badges atualizando em tempo real. |

---

## Ordem de implementação

1. **Quadro societário** – Sanitização de socios (impacto em privacidade e cobrança)
2. **Discrepância resultados/créditos** – Modelo SearchLead + regras de deduplicação
3. **Autocomplete** – Aumentar limite e carregar no load
4. **Tempo real** – Atualização incremental + polling durante processamento

---

## Pendências

- **API Viper (consultaCNPJSocios):** Confirmar se retorna socios com telefones/emails embutidos. Se tiver exemplo de JSON (sem dados reais), a sanitização pode ser mais precisa.
