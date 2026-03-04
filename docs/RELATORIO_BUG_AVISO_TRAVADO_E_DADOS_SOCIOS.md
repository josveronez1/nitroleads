# Relatório: Página travada ao fechar aviso + dados de sócios exibidos indevidamente

**Data:** 2026-03-05  
**Contexto:** Após o botão "Buscar Quadro Societário" passar a aparecer, dois novos problemas: (1) ao fechar o aviso de sucesso/erro a página continua travada; (2) leads vindos do banco exibem dados completos dos sócios (telefones, e-mails) sem o usuário ter feito a busca por CPF.

---

## 1. Resumo dos problemas

| # | Problema | Sintoma |
|---|----------|---------|
| 1 | Página travada após fechar o aviso | Ao fechar o modal de sucesso/erro (OK), o fundo continua escuro ou a página não rola/clica; parece que o aviso ainda está ativo. |
| 2 | Dados completos dos sócios sem busca por CPF | Na coluna SÓCIOS aparecem nomes, CPF e **telefones/e-mails** dos sócios para leads que vêm do banco, mesmo sem o usuário ter clicado em "Buscar informações dos sócios" (busca por CPF). |

---

## 2. Diagnóstico

### 2.1 Problema 1: Página travada ao fechar o aviso

**Causa provável:** Bootstrap adiciona ao `<body>` as classes `modal-open` e `overflow-hidden` (e às vezes um backdrop) quando um modal é aberto, e remove ao fechar. Se o modal de aviso (sucesso/erro/alert) for aberto **por cima** de outro modal (ex.: fullscreen de resultados), ou se houver mais de um backdrop/estado no body, ao fechar só o modal de aviso o Bootstrap pode não limpar o body (por exemplo por conta de ordem de fechamento ou de múltiplas instâncias).

**Onde verificar:** Em `search_history.html`, as funções `showSuccess`, `showError` e `showAlert` abrem o modal com `new bootstrap.Modal(...).show()` mas **não** registram listener em `hidden.bs.modal` para garantir limpeza do `body`. Além disso, em outro trecho (por volta da linha 709) há **fallback manual** que faz `document.body.classList.add('modal-open')` e cria um backdrop; se esse caminho for usado e o fechamento for feito só pelo Bootstrap, o estado manual pode ficar órfão (backdrop e classe no body permanecem).

**Conclusão:** Ao fechar o aviso, o `body` pode continuar com `modal-open`/`overflow-hidden` ou com um backdrop extra, deixando a página “travada”.

---

### 2.2 Problema 2: Dados completos dos sócios sem busca por CPF

Há **duas** regras de acesso:

- **Quadro societário (QSA):** nomes e CPF dos sócios — o usuário só deve ver depois de pagar por “Buscar Quadro Societário” **nesta pesquisa**.
- **Dados por CPF:** telefones e e-mails de cada sócio — o usuário só deve ver depois de usar “Buscar informações dos sócios” (busca por CPF) **para aquele sócio**.

**Onde está o erro:**

**A) Quadro societário (nomes/CPF) aparecendo em pesquisa que não foi paga**

- `LeadAccess` é único por `(user, lead)` e tem um único `search` e um único `enriched_at`.
- Se o usuário já pagou “Buscar Quadro Societário” para aquele lead em **outra** pesquisa (Search A), esse mesmo `LeadAccess` tem `enriched_at` preenchido e `search = Search A`.
- Numa **nova** pesquisa (Search B) que reutiliza o mesmo lead (ex.: veio do banco/cache), `get_leads_for_display` continua devolvendo esse mesmo `LeadAccess` (por user + lead).
- No template, a condição para mostrar a lista de sócios (nomes/CPF) é só:
  - `lead_access and lead_access.enriched_at and lead.viper_data.socios_qsa and lead.viper_data.socios_qsa.socios`
- **Não** se exige que o enriquecimento tenha sido feito **nesta** pesquisa. Assim, em Search B o sistema mostra o QSA porque o usuário já tinha `enriched_at` em Search A.

**B) Telefones/e-mails dos sócios (cpf_data) aparecendo sem busca por CPF**

- No template, para cada sócio, telefones e e-mails são exibidos quando `socio.cpf_enriched and socio.cpf_data`.
- Esses campos ficam gravados no **Lead** (em `viper_data.socios_qsa.socios[i]`), sem vínculo com **quem** enriqueceu.
- Se outro usuário (ou a mesma pessoa em outra pesquisa) já tiver feito a busca por CPF daquele sócio, o lead fica com `cpf_enriched` e `cpf_data` preenchidos. Qualquer um que veja esse lead (em qualquer pesquisa) passa a ver esses dados, mesmo sem ter feito a busca por CPF.

**Conclusão:**  
(1) O QSA está sendo liberado por “usuário já enriqueceu esse lead em qualquer pesquisa” em vez de “usuário enriqueceu **nesta** pesquisa”.  
(2) Os dados por CPF estão sendo liberados por “existe cpf_data no lead” em vez de “**este usuário** fez a busca por CPF deste sócio”.

---

## 3. Solução proposta

### 3.1 Problema 1: Página travada ao fechar o aviso

**Objetivo:** Garantir que, ao fechar qualquer modal de aviso (sucesso/erro/alert), o `body` volte ao estado normal e não reste backdrop órfão.

**Alterações sugeridas:**

1. **Listeners em `hidden.bs.modal`**  
   Para os modais `#successModal`, `#errorModal` e `#alertModal`, registrar (uma vez, por ex. ao carregar a página) um listener `hidden.bs.modal` que:
   - remova do `body` as classes `modal-open` e `overflow-hidden`;
   - remova do DOM qualquer elemento com classe `modal-backdrop` que ainda exista (ou apenas os que não pertençam a um modal ainda aberto).

2. **Fallback manual do fullscreen**  
   No trecho que faz fallback manual (adiciona `modal-open` e cria `#modalBackdrop`), garantir que, ao fechar esse modal, o mesmo tipo de limpeza seja feita (remover classe do body e remover o backdrop criado manualmente), seja por listener `hidden.bs.modal` nesse modal ou por lógica única de “limpar body quando não houver modal aberto”.

3. **Funções showSuccess / showError / showAlert**  
   Opcionalmente, ao abrir o modal, garantir que há um `once: true` (ou equivalente) em `hidden.bs.modal` que chama a função de limpeza do body, para que todo fechamento de aviso force a verificação/limpeza.

Com isso, ao fechar o aviso, a página deixa de ficar travada.

---

### 3.2 Problema 2: Dados dos sócios só após a busca correta

**Objetivo:**  
- Mostrar **quadro societário** (nomes/CPF) apenas quando o usuário tiver pago por “Buscar Quadro Societário” **nesta pesquisa**.  
- Mostrar **telefones/e-mails** de cada sócio apenas quando **este usuário** tiver feito a busca por CPF daquele sócio.

**Alterações sugeridas:**

**A) Quadro societário por pesquisa**

- **Template (partial e history):**  
  Na condição que decide se mostra a lista de sócios (nomes/CPF), além de  
  `lead_access and lead_access.enriched_at and lead.viper_data.socios_qsa and ...`  
  exigir que **o enriquecimento seja desta pesquisa**:  
  `lead_access.search_id == search.id` (ou `lead_access.search_id == search.pk`).  
  Assim, se o usuário enriqueceu o lead em Search A, em Search B a célula de sócios continua em “blur” até que pague por “Buscar Quadro Societário” em Search B.

- **Views (histórico e `api_search_status`):**  
  No cálculo de `all_leads_have_partners`, considerar “tem sócios” apenas quando, para o item,  
  `lead_access and lead_access.enriched_at and lead_access.search_id == search.id (ou search_obj.id) and has_valid_partners_data(lead)`.  
  Assim o botão “Buscar Quadro Societário” continua aparecendo em pesquisas onde o usuário ainda não pagou por esse lead **nesta** pesquisa, mesmo que já tenha pago em outra.

**B) Dados por CPF por usuário**

- Hoje `cpf_enriched` e `cpf_data` ficam no `Lead.viper_data.socios_qsa.socios[i]` sem identificar o usuário que enriqueceu. Para não mostrar dados de outro usuário (ou de outra pesquisa), é necessário **saber se foi o usuário atual** que enriqueceu aquele CPF.

- **Opção recomendada (curto prazo):**  
  Ao salvar o resultado da busca por CPF no lead, gravar no próprio socio (ou em estrutura auxiliar em `viper_data`) um indicador de “quem enriqueceu”, por exemplo:
  - `socios_qsa.socios[i].cpf_enriched_by_user_ids = [user_id1, user_id2, ...]`  
  ou
  - `socios_qsa.socios[i].cpf_data_by_user = { str(user_id): cpf_data }`.  

  Na hora de montar a resposta/template, para o **usuário atual**:
  - só preencher (ou exibir) `cpf_data` do sócio se o `user_id` atual estiver em `cpf_enriched_by_user_ids` (ou em `cpf_data_by_user`).  
  Assim, dados de sócio enriquecidos por outro usuário deixam de aparecer.

- **Onde implementar:**  
  - **Backend:** ao processar a busca por CPF e atualizar `lead.viper_data.socios_qsa.socios[i]`, preencher `cpf_enriched_by_user_ids` (ou `cpf_data_by_user`) incluindo o `user_id` do usuário que fez a busca.  
  - **Template (e qualquer API que devolva leads):** ao exibir o bloco `{% if socio.cpf_enriched and socio.cpf_data %}`, trocar para algo como “cpf_data presente **e** usuário atual está em socio.cpf_enriched_by_user_ids” (ou equivalente). Se a exibição for feita via dados já sanitizados no backend, a sanitização deve considerar esse novo campo.

- **Alternativa (médio prazo):**  
  Modelo separado, ex.: `SocioCpfEnrichment(user, lead, socio_cpf ou índice, cpf_data, created_at)`, e na renderização consultar se existe registro para (current_user, lead, este sócio). A regra de negócio é a mesma; só muda onde fica armazenado.

**Resumo B:**  
- Quadro societário: amarrar a “esta pesquisa” com `lead_access.search_id == search.id` no template e nas views que calculam `all_leads_have_partners`.  
- Dados por CPF: amarrar a “este usuário” com `cpf_enriched_by_user_ids` (ou `cpf_data_by_user`) no Lead e na lógica de exibição/sanitização.

---

## 4. Arquivos a alterar (resumo)

| Arquivo | Alteração |
|--------|-----------|
| `lead_extractor/templates/lead_extractor/search_history.html` | (1) Registrar `hidden.bs.modal` em successModal, errorModal, alertModal para limpar `body` (modal-open, overflow-hidden, backdrops). Ajustar fallback do fullscreen para limpar ao fechar. (2) Na célula de sócios, exigir `lead_access.search_id == search.id` para mostrar QSA. (3) Para cpf_data, exigir que o usuário atual esteja em `socio.cpf_enriched_by_user_ids` (ou equivalente) — depende da estrutura escolhida. |
| `lead_extractor/templates/lead_extractor/partials/search_leads_table.html` | Mesma condição de QSA: `lead_access.search_id == search.id`. Mesma condição de cpf_data por usuário. |
| `lead_extractor/views.py` | Em `all_leads_have_partners` (história e `api_search_status`), exigir `lead_access.search_id == search_obj.id` (ou `search.id`). |
| `lead_extractor/services.py` (ou view que processa busca por CPF) | Ao salvar `cpf_data`/`cpf_enriched` no socio, gravar também `cpf_enriched_by_user_ids` (ou `cpf_data_by_user`) com o user_id atual. |

---

## 5. Resumo em uma frase

- **Problema 1:** O fechamento do modal de aviso não garante limpeza de `modal-open`/`overflow-hidden`/backdrop no `body`, deixando a página travada; é preciso limpar o body (e eventualmente backdrops) no evento `hidden.bs.modal` dos modais de aviso e no fechamento do fullscreen quando usado fallback manual.
- **Problema 2:** O sistema trata “ter quadro societário” como “usuário já enriqueceu esse lead em qualquer pesquisa” e “ter dados por CPF” como “existe cpf_data no lead”, em vez de “enriqueceu **nesta** pesquisa” e “**este usuário** enriqueceu este sócio”; a solução é amarrar QSA a `lead_access.search_id == search.id` e cpf_data a um campo por usuário (ex.: `cpf_enriched_by_user_ids`) no socio e na exibição.
