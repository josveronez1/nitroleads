# Relatório: Leads repetidos na mesma pesquisa e leads com DDD de outros estados

**Data:** 2026-03-04  
**Contexto:** Pesquisa "Petshop em Santa Maria - RS" retornou leads repetidos (mesmo nome, CNPJs diferentes) e leads com telefones de outros estados (Goiás, Alagoas, São Paulo, Minas Gerais).

---

## 1. Problema 1: Leads repetidos na mesma pesquisa

### 1.1 Descrição

Usuário relatou ter recebido leads repetidos em uma pesquisa. Nas imagens, aparecem dois registros "Tosa Show Pet Shop" com CNPJs diferentes (25074510000134 e 54474695000172) e sócios diferentes — ou seja, são empresas distintas com o mesmo nome, não o mesmo lead duas vezes.

### 1.2 Diagnóstico (código)

A deduplicação **na mesma pesquisa** está implementada assim:

- **`process_search_async` (services.py):**
  - `existing_cnpjs` é inicializado com `get_cnpjs_from_user_last_3_searches(exclude_search_id=search_id)` (CNPJs das últimas 3 buscas do usuário, exceto a atual).
  - Ao retornar leads da base: cada CNPJ é adicionado a `existing_cnpjs`.
  - Ao buscar no cache: `get_leads_from_cache(..., extra_exclude_cnpjs=existing_cnpjs)` — assim, o cache não devolve CNPJs já entregues nesta corrida.
  - Ao processar resultados do Serper: `processed_cnpjs_in_search` contém os CNPJs já adicionados aos `results`; antes de aceitar um lead verifica-se `if cnpj in processed_cnpjs_in_search` e `if cnpj in existing_cnpjs` e o lead é ignorado nesses casos.

- **`get_leads_from_cache`:**
  - Monta `exclude_cnpjs` = CNPJs das últimas 3 buscas + `extra_exclude_cnpjs`.
  - Faz `.exclude(cnpj__in=exclude_cnpjs)` e usa `cnpjs_processed` para não incluir o mesmo CNPJ duas vezes na lista retornada.

- **`get_existing_leads_from_db`:**
  - Usa `cnpjs_processed` para não duplicar CNPJ na lista.

Conclusão: **o mesmo CNPJ não pode aparecer duas vezes na mesma pesquisa**. As alterações recentes (modal, QSA por pesquisa, SocioCpfEnrichment) não mexem nesse fluxo.

### 1.3 Interpretação do “repetido”

- Se “repetido” = **mesmo CNPJ duas vezes**: seria bug; pelo código, isso não deveria ocorrer.
- Se “repetido” = **mesmo nome de empresa, CNPJs diferentes** (ex.: dois "Tosa Show Pet Shop"): são empresas diferentes; a “repetição” é de **nome**, não de lead. Isso se relaciona ao problema de localização (Serper/CNPJ devolverem empresas de outras cidades com o mesmo nome).

### 1.4 Recomendações

1. **Confirmar com o usuário:** A repetição é o mesmo CNPJ duas vezes ou apenas o mesmo nome com CNPJs diferentes?
2. **Se for mesmo CNPJ:** Incluir log em `process_search_async` (por exemplo ao adicionar a `results`) para checar que nenhum CNPJ é adicionado duas vezes; e opcionalmente validação em desenvolvimento que falhe se houver duplicata.
3. **Se for mesmo nome:** Tratar como parte do Problema 2 (localização/desambiguação).

---

## 2. Problema 2: Leads com DDD de outros estados

### 2.1 Descrição

Pesquisa em **Santa Maria - RS** retornou leads com telefones de outros estados:

- DDD 64 (Goiás)
- DDD 82 (Alagoas)
- DDD 16 (São Paulo)
- DDD 38 (Minas Gerais)

Ex.: "Maia Petcenter | Pet Shop em Santa Maria" com DDD 82 (Alagoas) — o nome sugere Santa Maria, mas o contato é de outro estado.

### 2.2 Onde a localização é usada hoje

- **Termo enviado ao Serper (Places/Search)**  
  Em `process_search_async` (services.py, ~linha 1465):

  ```python
  search_term = f"{niche} em {location}"
  ```

  Ou seja, a localização **já é enviada** no termo de busca (ex.: "Petshop em Santa Maria - RS") para `search_google_maps_paginated` e `search_google_hybrid`. O problema não é “não passar localização” no Places, e sim:

  1. O algoritmo do Google/Serper pode trazer negócios com “Santa Maria” no nome (ou “Petshop”) de outras cidades.
  2. A etapa crítica sem localização é a **resolução do CNPJ**.

### 2.3 Causa raiz: busca de CNPJ sem localização

A função **`find_cnpj_by_name(company_name)`** (services.py, ~linhas 378–411):

- Recebe **apenas** o nome da empresa.
- Monta a query Serper como `"CNPJ {name}"` (ex.: `"CNPJ Maia Petcenter"`).
- **Não inclui cidade nem UF.**

Efeito: para nomes comuns (ex.: "Tosa Show Pet Shop", "Maia Petcenter"), o primeiro resultado do Google pode ser de outro estado. Esse CNPJ é associado ao lead e os dados (telefone, endereço) vêm do Viper para esse CNPJ — daí DDDs de Goiás, Alagoas, etc.

Resumo: **a localização é usada na busca de lugares, mas não na desambiguação do CNPJ por nome**, o que permite vincular o lugar a uma empresa errada (mesmo nome, outra cidade).

### 2.4 Solução proposta

**Incluir a localização na busca de CNPJ**, para priorizar o resultado da cidade/estado desejados:

1. **Alterar `find_cnpj_by_name`** para aceitar um parâmetro opcional de localização (ex.: `location: str | None = None`).
2. Se `location` for informado, montar a query como:
   - `f"CNPJ {company_name} {location}"`  
   ou, com normalização (cidade + UF sem acento, ex.: "Santa Maria RS"):
   - `f"CNPJ {company_name} {location_normalized}"`
3. Em **todos os pontos que chamam `find_cnpj_by_name`** no fluxo de busca (incl. busca incremental e processamento de places), passar a localização da pesquisa atual (ex.: `location` ou `location_normalized` usado em `process_search_async`).

Isso deve reduzir a associação de leads a CNPJs de outros estados e, de quebra, diminuir “repetição” de nome (mesmo nome, empresa certa da cidade).

**Reforço opcional no termo do Places:**  
Manter `"{niche} em {location}"` e, se a API permitir, testar variantes como `"{niche} Santa Maria RS"` para reforçar o peso da localização no ranking. Isso pode ser testado depois da mudança no `find_cnpj_by_name`.

### 2.5 Pontos de chamada de `find_cnpj_by_name`

- `search_incremental` (services.py): recebe `search_term` (já tem nicho + localização); pode-se extrair ou passar `location` separado.
- `process_search_async` (services.py): dois blocos que chamam `find_cnpj_by_name(company_data['name'])` — um no fluxo principal de places paginados, outro na busca incremental. Em ambos, `location` e `location_normalized` estão disponíveis no escopo; basta passar um deles para a função (após ajustar a assinatura e a montagem da query).

---

## 3. Resumo

| Problema | Conclusão | Ação |
|----------|-----------|------|
| **1. Leads repetidos** | Deduplicação por CNPJ na mesma pesquisa está correta; alterações recentes não a afetam. “Repetido” pode ser mesmo nome com CNPJs diferentes. | Esclarecer com o usuário; se for mesmo CNPJ, adicionar log/validação; se for mesmo nome, tratar junto ao item 2. |
| **2. DDD de outros estados** | Localização já vai no termo do Serper Places. O problema é **resolução de CNPJ só por nome**, sem cidade/UF. | Incluir localização na query de `find_cnpj_by_name` e passar `location` em todas as chamadas no fluxo de busca. |

---

## 4. Próximos passos sugeridos

1. Implementar `find_cnpj_by_name(company_name, location=None)` e usar `location` na query Serper quando existir.
2. Em `process_search_async` e `search_incremental`, passar a localização da pesquisa em toda chamada a `find_cnpj_by_name`.
3. (Opcional) Reforçar o termo do Places com formato alternativo incluindo cidade e UF de forma explícita.
4. Após deploy, validar com uma pesquisa “Petshop Santa Maria - RS” e conferir se os DDDs dos leads retornados são predominantemente 55 (RS).
