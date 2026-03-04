# Relatório: Bug "1 resultado" + botão Buscar Quadro Societário ausente

**Data:** 2026-03-05  
**Contexto:** Pesquisa "Advogado em Santa Maria - RS" (e outras) com leads vindos da base/cache: frontend mostra 1 resultado quando os logs indicam 2; botão "Buscar Quadro Societário" e "Buscar informações dos sócios" não aparecem.

---

## 1. Resumo dos problemas

| # | Problema | Evidência |
|---|----------|-----------|
| A | Frontend mostra "1 resultados" quando a busca entregou 2 leads (ex.: busca 84) | Logs: "Busca 84 concluída: 2 leads processados", "Cache usado: 1 leads adicionais do cache (total: 2/2)". Badge na tela: "1 resultados". |
| B | Botão "Buscar Quadro Societário" não aparece quando os leads vêm da base/cache | Pesquisa 85 (Pet Shop Santa Maria): 3 leads da base; botão de buscar sócios não é exibido. |
| C | Botão "Buscar informações dos sócios" (por lead) não aparece nesses casos | Célula de sócios fica só com texto borrado, sem botão para buscar CPF. |

---

## 2. Causa raiz

### 2.1 Problema A: contagem "1" em vez de "2"

**Onde:** `process_search_async` usa `get_existing_leads_from_db` (ex.: 1 lead) e depois `get_leads_from_cache` para completar (ex.: mais 1).

**Causa:**  
`get_leads_from_cache` não recebe os CNPJs **já usados na busca atual**. Ela só exclui CNPJs das “últimas 3 pesquisas” (`get_cnpjs_from_user_last_3_searches` com `exclude_search_id=search_obj.id`), ou seja, exclui outras pesquisas, **não** os leads já escolhidos nesta pesquisa.

Assim, o cache pode devolver o **mesmo lead** (mesmo CNPJ) que já veio de `get_existing_leads_from_db`.  
Nesse caso:

- `results` e `leads_processed` sobem 2 (o mesmo lead é contado duas vezes).
- `SearchLead.objects.get_or_create(search=search_obj, lead=lead)` é chamado duas vezes para o **mesmo** `lead` → continua existindo só **um** registro em `SearchLead` para essa busca.
- `search_obj.results_count = SearchLead.objects.filter(search=search_obj).count()` → **1**.
- O frontend exibe "1 resultados" e só uma linha na tabela.

**Conclusão:** A contagem e a listagem ficam corretas só quando o lead do cache é **diferente** do lead da base. Quando é o mesmo, o sistema conta 2 mas grava 1 e mostra 1.

---

### 2.2 Problemas B e C: botões de sócios não aparecem

**Regra de negócio desejada:**  
- Dados de sócios no `Lead` podem ter vindo de **outro usuário** (ex.: usuário X pagou e os sócios ficaram em `lead.viper_data`).  
- Para o **usuário Y**, isso não conta como “tem sócios”: Y precisa poder clicar em “Buscar Quadro Societário” e, depois, em “Buscar informações dos sócios”.  
- Ou seja: “ter sócios” deve ser **por usuário** (este usuário já pagou e já tem dados de sócios para este lead), não só “o lead tem `socios_qsa` no banco”.

**Onde está o erro:**

1. **`all_leads_have_partners` (história e API de status)**  
   Em `views.py` (história ~908–913 e `api_search_status` ~1259–1265) a lógica é:

   ```python
   for item in display_leads:
       leads_count += 1
       if not has_valid_partners_data(item['lead']):
           all_leads_have_partners = False
   ```

   `has_valid_partners_data(lead)` só olha **Lead.viper_data.socios_qsa** (se o lead tem lista de sócios no banco). **Não** considera se o **usuário atual** “comprou” esse dado (por exemplo, `LeadAccess.enriched_at`).

   Quando os leads vêm da base/cache, o `Lead` pode já ter `socios_qsa` de outro usuário. Aí `has_valid_partners_data(lead)` é `True` para todos → `all_leads_have_partners` fica `True` → o botão **"Buscar Quadro Societário"** deixa de ser exibido (e não é injetado no front quando a busca termina).

2. **Template da célula de sócios**  
   Em `partials/search_leads_table.html` e em `search_history.html`:

   - O bloco que mostra **lista de sócios + botão "Buscar informações dos sócios"** só é renderizado quando:
     - `lead_access and lead_access.enriched_at and lead.viper_data.socios_qsa and lead.viper_data.socios_qsa.socios`
   - Caso contrário cai no `{% else %}` e mostra só **blurred-partners**, **sem** botão.

   Para o usuário Y, nesse cenário:

   - `lead.viper_data.socios_qsa` pode existir (dado do usuário X).
   - Mas `lead_access.enriched_at` é `None` (Y ainda não pagou por “buscar sócios” para esse lead).
   - Então a condição falha → só aparece texto borrado, **sem** o botão "Buscar informações dos sócios".

Ou seja: a decisão de mostrar ou não os botões de sócios está baseada em “o lead tem sócios no banco” e não em “**este usuário** já tem acesso a sócios para este lead”.

---

## 3. Solução proposta

### 3.1 Problema A (contagem e duplicata)

- **Objetivo:** Garantir que, ao completar a busca com base + cache, não entrem **dois** registros para o mesmo lead na mesma pesquisa e que `results_count` e a lista reflitam o número real de **leads distintos**.

- **Alteração sugerida:**
  - Em `get_leads_from_cache`, adicionar um parâmetro opcional, por exemplo `extra_exclude_cnpjs`, (set de CNPJs a excluir).
  - Na chamada feita em `process_search_async` (após ter processado `existing_leads`), passar os CNPJs já usados nesta busca (por exemplo o set `existing_cnpjs` que já é mantido nesse fluxo).
  - Dentro de `get_leads_from_cache`, além de `exclude_cnpjs` das últimas 3 pesquisas, excluir também os CNPJs de `extra_exclude_cnpjs` (na query e/ou no loop), para que o cache não devolva o mesmo lead já retornado por `get_existing_leads_from_db`.

Assim, cada lead distinto entra só uma vez na pesquisa, `SearchLead` e `results_count` batem com o número de linhas no frontend e o “1 resultado” indevido deixa de ocorrer nesse cenário.

---

### 3.2 Problemas B e C (botões de sócios)

- **Objetivo:** Tratar “este usuário já tem dados de sócios para este lead” em vez de “o lead tem sócios no banco”.

- **Alterações sugeridas:**

1. **`all_leads_have_partners` (história e API de status)**  
   Considerar que um lead “tem sócios” para a **exibição do botão** somente quando **o usuário atual** já pagou e já tem dados de sócios para esse lead:

   - Trocar a condição de:
     - `if not has_valid_partners_data(item['lead'])`
   - Para algo como:
     - “Para cada item: `lead_access` existe, `lead_access.enriched_at` está preenchido **e** `has_valid_partners_data(lead)`”.
   - Em código:  
     `all_leads_have_partners = all((item.get('lead_access') and getattr(item['lead_access'], 'enriched_at', None) and has_valid_partners_data(item['lead']) for item in display_leads))`  
     (e manter o caso “nenhum lead” como hoje, ex.: `all_leads_have_partners = True` para não mostrar botão à toa).

   Assim, quando os leads vêm da base com `socios_qsa` de outro usuário, para o usuário atual `lead_access.enriched_at` será `None` → `all_leads_have_partners` será `False` → o botão **"Buscar Quadro Societário"** voltará a aparecer.

2. **Template da célula de sócios**  
   A regra atual já está correta do ponto de vista de **não** mostrar dados de sócios nem o botão "Buscar informações dos sócios" quando o usuário não tem `enriched_at`. O que faltava era o botão de **buscar quadro societário** (nível pesquisa), que fica correto com a mudança em `all_leads_have_partners` acima.

   Opcionalmente, na célula de sócios, quando estiver no `{% else %}` (blurred), pode-se garantir que há um CTA ou texto que direcione o usuário a usar o botão "Buscar Quadro Societário" do card (que passará a aparecer). Nada de mudança estrutural na condição do template; apenas `all_leads_have_partners` precisa ser por usuário.

---

## 4. Arquivos a alterar

| Arquivo | Alteração |
|--------|-----------|
| `lead_extractor/services.py` | Em `get_leads_from_cache`, adicionar parâmetro `extra_exclude_cnpjs` e excluir esses CNPJs ao buscar no cache. Em `process_search_async`, na chamada a `get_leads_from_cache`, passar o set de CNPJs já usados nesta busca (ex.: `existing_cnpjs`). |
| `lead_extractor/views.py` | No cálculo de `all_leads_have_partners` (view de histórico e em `api_search_status`), exigir também `item.get('lead_access')` e `lead_access.enriched_at` além de `has_valid_partners_data(item['lead'])`. |

---

## 5. Resumo em uma frase

- **Problema A:** O cache pode devolver o mesmo lead já retornado pela base na mesma busca; como não excluímos os CNPJs já usados nesta busca, criamos apenas um `SearchLead` e o front mostra “1 resultados”.
- **Problemas B e C:** “Ter sócios” está baseado só em `Lead.viper_data`; o correto é considerar “este usuário já pagou e tem sócios” (`LeadAccess.enriched_at` + dados no lead), para que os botões "Buscar Quadro Societário" e "Buscar informações dos sócios" apareçam quando o usuário ainda não comprou esses dados, mesmo que o lead já tenha `socios_qsa` no banco de outro usuário.

Implementando a exclusão de CNPJs já usados na busca ao chamar o cache e tornando `all_leads_have_partners` dependente de `lead_access.enriched_at` (e do lead ter dados), os três problemas ficam corrigidos de forma alinhada à regra de negócio desejada.
