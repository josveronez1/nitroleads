📋 Plano de Robustez: Lead Extraction System (Nitro Leads)

Este documento consolida as auditorias realizadas em Janeiro de 2026 e define o roadmap técnico para transformar o sistema em uma plataforma SaaS escalável, segura e lucrativa. Ele serve como guia de contexto para desenvolvimento e refatoração via IA.

🚀 1. Visão Geral do Roadmap

O projeto deve evoluir de uma arquitetura de "protótipo" para um sistema de nível empresarial. A prioridade segue a hierarquia de sobrevivência do software:

Ordem

Fase

Foco Principal

Impacto

1

Sobrevivência & Integridade

Segurança e Lógica de Créditos

Crítico (Financeiro/Jurídico)

2

Estabilidade Operacional

Infraestrutura e Resiliência

Alto (Disponibilidade)

3

Estrutura & Escalabilidade

Arquitetura e Clean Code

Médio (Manutenção)

4

Velocidade & UX

Performance de Banco e Memória

Médio (Experiência)

🛡️ 2. Fase 1: Sobrevivência e Integridade (Imediato)

Objetivo: Blindar o acesso a dados sensíveis e garantir que cada visualização de dado gere receita.

📝 Itens de Ação:

Padronização de Ownership (Risco Crítico #1): Refatorar todas as views para validar permissão exclusivamente via tabela LeadAccess. Leads "globais" (user=None) não devem ser acessíveis sem um vínculo de compra.

Blindagem de Tokens (Risco Crítico #2): Mover viper_tokens.json para o diretório /secure/ e configurar Nginx para bloquear qualquer acesso externo a arquivos .json ou à pasta /secure/.

Correção da Lógica de Cobrança: Alterar funções de cache e busca assíncrona para debitar créditos sempre que um lead for entregue em uma nova busca, removendo a dependência de if created.

Sistema de Reembolso (Refund): Implementar a função refund_credits() no credit_service.py e aplicá-la em blocos try/except ao redor de chamadas às APIs externas (Viper/Serper).

📑 Relatórios de Referência (Segurança e Créditos)

[Relatório de Auditoria de Segurança - Nitro Leads
Resumo executivo
Foram identificados 12 riscos de segurança, distribuídos em 4 categorias de criticidade. Os principais problemas estão em Broken Access Control e Exposição de Dados Sensíveis.
🔴 CRÍTICO
1. Broken Access Control - Validação insuficiente de ownership em search_cpf_batch
Localização: lead_extractor/views.py:1397-1405
Descrição:
A função search_cpf_batch valida ownership apenas se lead.user existir. Como o modelo Lead permite user=None (campo deprecated), um atacante pode acessar leads globais que não pertencem a nenhum usuário.
views.pyLines 1397-1405
                lead = Lead.objects.filter(id=lead_id).first()                if not lead:                    errors.append(f"Lead {lead_id} não encontrado")                    continue                                # Se o lead tem usuário, validar ownership                if lead.user and lead.user != user_profile:                    errors.append(f"Lead {lead_id} não pertence ao usuário")                    continue
Impacto: Acesso não autorizado a dados de CPFs e sócios de leads globais.
Recomendação: Validar via LeadAccess em vez de lead.user:
# Validar via LeadAccess (modelo correto)lead_access = LeadAccess.objects.filter(lead_id=lead_id, user=user_profile).first()if not lead_access:    errors.append(f"Lead {lead_id} não pertence ao usuário")    continuelead = lead_access.lead
2. Exposição de dados sensíveis - viper_tokens.json acessível via web
Localização: auth_bot.py:25, lead_extractor/services.py:26
Descrição:
O arquivo viper_tokens.json está em secure/viper_tokens.json. Se o servidor web servir arquivos fora de STATIC_ROOT ou se houver configuração incorreta, o arquivo pode ser acessível via HTTP.
Impacto: Exposição de tokens de autenticação do Viper, permitindo acesso não autorizado à API.
Recomendação:
Garantir que secure/ esteja fora de qualquer diretório servido pelo web server
Adicionar .htaccess ou regra nginx para bloquear acesso
Considerar armazenar tokens em variáveis de ambiente ou serviço de secrets
3. Exposição de dados sensíveis - viper_data com CPFs e sócios em banco sem criptografia
Localização: lead_extractor/models.py:152
Descrição:
O campo viper_data (JSONField) armazena CPFs, dados de sócios e informações sensíveis sem criptografia. Se o banco for comprometido, os dados ficam expostos.
Impacto: Violação de LGPD/GDPR, exposição de dados pessoais sensíveis.
Recomendação:
Criptografar campos sensíveis antes de salvar (ex.: usar django-encrypted-model-fields ou criptografia em nível de aplicação)
Considerar mascarar CPFs parcialmente (ex.: ***.***.***-XX)
Implementar rotina de anonimização para dados antigos
🟠 ALTO
4. Broken Access Control - Validação inconsistente de lead_id em múltiplas views
Localização: lead_extractor/views.py:1397, lead_extractor/views.py:1138-1145
Descrição:
Algumas views validam ownership via LeadAccess, outras apenas verificam lead.user. Isso cria inconsistências e possíveis bypasses.
Exemplo correto:
views.pyLines 1138-1142
        lead_accesses_to_enrich = LeadAccess.objects.filter(            lead_id__in=lead_ids,            user=user_profile,            search=search_obj        ).select_related('lead')
Exemplo problemático:
views.pyLines 1397-1405
                lead = Lead.objects.filter(id=lead_id).first()                if not lead:                    errors.append(f"Lead {lead_id} não encontrado")                    continue                                # Se o lead tem usuário, validar ownership                if lead.user and lead.user != user_profile:                    errors.append(f"Lead {lead_id} não pertence ao usuário")                    continue
Recomendação: Padronizar todas as views para usar LeadAccess como única fonte de verdade para ownership.
5. Injeção de comandos - subprocess.Popen com caminho hardcoded no webhook GitHub
Localização: lead_extractor/views.py:1549-1554
Descrição:
O webhook do GitHub executa um script com caminho hardcoded. Embora o caminho seja fixo, não há validação adicional do script antes da execução.
views.pyLines 1549-1554
        subprocess.Popen(            [deploy_script],            stdout=subprocess.PIPE,            stderr=subprocess.PIPE,            cwd='/home/nitroleads/apps/nitroleads'        )
Impacto: Se o script for modificado maliciosamente, pode executar comandos arbitrários.
Recomendação:
Adicionar checksum do script e validar antes de executar
Executar com usuário não privilegiado
Adicionar logging detalhado do que foi executado
Considerar usar sistema de filas (Celery) em vez de subprocess direto
6. Autenticação - Validação de JWT sem verificação de expiração explícita
Localização: lead_extractor/middleware.py:68-73
Descrição:
O middleware valida o JWT, mas não verifica explicitamente a expiração. A biblioteca jose pode fazer isso automaticamente, mas não está claro se audience='authenticated' é suficiente.
middleware.pyLines 68-73
            payload = jwt.decode(                auth_token,                SUPABASE_JWT_SECRET,                algorithms=['HS256'],                audience='authenticated'            )
Recomendação:
Adicionar verificação explícita de expiração: options={"verify_exp": True}
Validar iss (issuer) se aplicável
Implementar refresh token mechanism
7. Exposição de dados sensíveis - sanitize_lead_data pode vazar dados em logs
Localização: lead_extractor/services.py:1260-1289
Descrição:
A função sanitize_lead_data remove dados sensíveis antes de enviar ao frontend, mas se houver logging antes da sanitização, dados sensíveis podem aparecer em logs.
Recomendação:
Garantir que logs nunca contenham viper_data completo
Usar máscaras em logs (ex.: CPF: ***.***.***-XX)
Revisar todos os pontos de logging que tocam em viper_data
🟡 MÉDIO
8. Broken Access Control - Falta validação de ownership em export_leads_csv quando search_id=None
Localização: lead_extractor/views.py:258-301
Descrição:
Quando search_id=None, a função exporta todos os leads do usuário via LeadAccess, o que está correto. Porém, se houver leads com user=None compartilhados, pode haver confusão.
Impacto: Baixo, pois usa LeadAccess.objects.filter(user=user_profile), mas a lógica pode ser mais clara.
Recomendação: Documentar claramente que apenas leads com LeadAccess do usuário são exportados.
9. Injeção de comandos - subprocess.run em run_auth_bot usa variáveis de ambiente do processo pai
Localização: lead_extractor/services.py:131-138
Descrição:
O subprocess.run copia todo o ambiente do processo pai (env = os.environ.copy()). Se variáveis de ambiente maliciosas forem injetadas, podem afetar o auth_bot.py.
services.pyLines 131-138
        result = subprocess.run(            [sys.executable, str(AUTH_BOT_PATH)],            env=env,            cwd=str(BASE_DIR),            timeout=AUTH_BOT_TIMEOUT,            capture_output=True,            text=True        )
Recomendação:
Criar ambiente mínimo com apenas variáveis necessárias
Validar valores de variáveis críticas antes de passar ao subprocess
10. Autenticação - Falta rate limiting no middleware de autenticação
Localização: lead_extractor/middleware.py:32-145
Descrição:
O SupabaseAuthMiddleware não tem rate limiting. Um atacante pode tentar validar tokens em massa, causando carga no banco.
Recomendação:
Adicionar rate limiting por IP no middleware
Cachear validações de JWT válidos por alguns segundos
Monitorar tentativas de autenticação falhadas
🟢 BAIXO
11. Autenticação - Email placeholder temporário pode ser usado indevidamente
Localização: lead_extractor/middleware.py:89-91
Descrição:
Se o email não estiver no JWT, é usado um placeholder user_{user_id[:8]}@temp.com. Isso pode causar confusão em logs e relatórios.
middleware.pyLines 89-91
                email = f"user_{user_id[:8]}@temp.com"                logger.warning(f"Email não encontrado no JWT para user_id {user_id}, usando placeholder")
Recomendação:
Considerar falhar a autenticação se email não estiver presente
Ou buscar email via API do Supabase se não estiver no JWT
12. Exposição de dados sensíveis - Diretório secure/ com permissões 700 pode não ser suficiente
Localização: auth_bot.py:24
Descrição:
O diretório secure/ é criado com permissões 700 (apenas owner). Se o processo web rodar com usuário diferente do que cria o diretório, pode haver problemas.
auth_bot.pyLine 24
SECURE_DIR.mkdir(exist_ok=True, mode=0o700)  # Criar diretório com permissões restritas (700)
Recomendação:
Garantir que o usuário do processo web tenha acesso ao diretório
Considerar usar grupo específico com permissões adequadas
Documentar requisitos de permissões no README
Estatísticas do relatório
Total de riscos: 12
Críticos: 3
Altos: 4
Médios: 3
Baixos: 2
Recomendações prioritárias
Imediato: Corrigir validação de ownership em search_cpf_batch (risco #1)
Imediato: Garantir que viper_tokens.json não seja acessível via web (risco #2)
Curto prazo: Implementar criptografia para viper_data (risco #3)
Curto prazo: Padronizar validação de ownership em todas as views (risco #4)
Médio prazo: Revisar e melhorar segurança do webhook GitHub (risco #5)
Observações positivas
Uso correto de LeadAccess na maioria das views
Uso de subprocess.run com timeout e caminhos absolutos
Validação de JWT com biblioteca confiável (jose)
Uso de transações atômicas em credit_service.py
Função sanitize_lead_data para proteger dados sensíveis no frontend
Uso de select_for_update() para prevenir race conditions em créditos


Relatório de Conformidade: Lógica de Transação de Créditos
1. Integridade Financeira - Prevenção de Double Spending
Status: Conforme com ressalvas
A função debit_credits em credit_service.py implementa proteções contra race conditions:
credit_service.pyLines 9-56
def debit_credits(user_id, amount, description=None):    """    Debita créditos do usuário de forma atômica.    ...    """    try:        with transaction.atomic():            # Se user_id é um objeto, usar diretamente, senão buscar            if isinstance(user_id, UserProfile):                user_profile = user_id                # Buscar novamente com lock para garantir consistência                user_profile = UserProfile.objects.select_for_update().get(id=user_profile.id)            else:                user_profile = UserProfile.objects.select_for_update().get(id=user_id)                        # Verificar e debitar créditos atomicamente usando F() expression            # Isso previne race conditions: a verificação e o débito acontecem em uma única operação SQL            updated_count = UserProfile.objects.filter(                id=user_profile.id,                credits__gte=amount  # Verificação condicional no banco            ).update(credits=F('credits') - amount)                        if updated_count == 0:                # Atualizar objeto para obter saldo atual                user_profile.refresh_from_db()                return False, user_profile.credits, f"Créditos insuficientes. Disponível: {user_profile.credits}, Necessário: {amount}"                        # Atualizar o objeto para obter o valor atualizado            user_profile.refresh_from_db()                        # Criar transação de uso            CreditTransaction.objects.create(                user=user_profile,                transaction_type='usage',                amount=-amount,  # Negativo para débito                description=description or f"Uso de {amount} crédito(s)"            )                        logger.info(f"Créditos debitados: {amount} do usuário {user_profile.email}. Novo saldo: {user_profile.credits}")                        return True, user_profile.credits, None                except UserProfile.DoesNotExist:        return False, 0, f"Usuário não encontrado: {user_id}"    except Exception as e:        logger.error(f"Erro ao debitar créditos: {e}")        return False, 0, str(e)
Proteções implementadas:
transaction.atomic() para atomicidade
select_for_update() para lock de linha
Verificação e débito em uma única operação SQL com F() e filter().update()
Verificação condicional credits__gte=amount no banco
Ressalva:
Se a criação de CreditTransaction falhar após o update(), o crédito já foi debitado, mas não há registro. O rollback do atomic() deveria reverter, mas se houver exceção não capturada, pode haver inconsistência.
2. Regras de Cobrança - "Cobrar para visualizar mesmo se já existir no banco"
Status: Parcialmente conforme — inconsistências identificadas
Análise por cenário:
2.1. Busca por CNPJ (search_by_cnpj)
Conforme: debita crédito mesmo se o lead já existe.
views.pyLines 630-712
        try:            # Verificar se já existe Lead com este CNPJ (pode ser de qualquer usuário ou sem usuário)            existing_lead = Lead.objects.filter(cnpj=cnpj_clean).first()                        if existing_lead and existing_lead.viper_data:                # Já existe - usar dados existentes                logger.info(f"Reutilizando Lead existente {existing_lead.id} para CNPJ {cnpj_clean}")                lead = existing_lead                data = lead.viper_data.copy()                                # Verificar se precisa buscar sócios                if not has_valid_partners_data(lead):                    queue_result = get_partners_internal_queued(cnpj_clean, user_profile, lead=lead)                    queue_id = queue_result.get('queue_id')                    if queue_id:                        partners_data = wait_for_partners_processing(queue_id, user_profile, timeout=60)                        if partners_data:                            data['socios_qsa'] = partners_data                            lead.viper_data = data                            lead.save(update_fields=['viper_data'])                        # Garantir que lead e data estão definidos            if not lead or not data:                logger.error(f"Erro: lead ou data não definidos após processamento (CNPJ: {cnpj_clean})")                messages.error(request, 'Erro ao processar dados do CNPJ')                return redirect('simple_search')                        # Debitar crédito            success, new_balance, error = debit_credits(                user_profile,                1,                description=f"Busca rápida por CNPJ: {cnpj_clean}"            )
2.2. Busca de Sócios (search_partners)
Conforme: debita crédito antes de buscar/exibir, mesmo se dados já existem.
views.pyLines 1278-1289
                # IMPORTANTE: Debitar crédito ANTES de buscar/exibir sócios                success, new_balance, error = debit_credits(                    user_profile,                    1,                    description=f"Sócios (QSA) para {lead.name} (CNPJ: {lead.cnpj})"                )                                if not success:                    errors.append(f"Erro ao debitar crédito para {lead.name}: {error}")                    continue                                credits_debited += 1
2.3. Busca por CPF (search_cpf_batch)
Conforme: debita crédito antes de buscar, mesmo se dados já existem.
views.pyLines 1407-1418
                # IMPORTANTE: Debitar crédito ANTES de buscar/exibir dados                success, new_balance, error = debit_credits(                    user_profile,                    1,                    description=f"Busca por CPF: {cpf} ({socio_name})"                )                                if not success:                    errors.append(f"Erro ao debitar crédito para CPF {cpf}: {error}")                    continue                                credits_debited += 1
2.4. Processamento de Busca Assíncrona (process_search_async)
Não conforme: só debita se LeadAccess for criado (created=True). Se já existir, não debita novamente.
services.pyLines 1490-1512
                    # Criar ou obter LeadAccess e debitar crédito                    lead_access, created = LeadAccess.objects.get_or_create(                        user=user_profile,                        lead=lead_obj,                        defaults={                            'search': search_obj,                            'credits_paid': 1,                        }                    )                                        if created:                        success, new_balance, error = debit_credits(                            user_profile,                            1,                            description=f"Lead: {company_data['name']}"                        )                                                # Se débito falhar, PARAR busca completamente                        if not success:                            logger.error(f"Débito de crédito falhou: {error}. Parando busca.")                            break                                                credits_used += 1
Problema: se o usuário visualizar o mesmo lead em uma nova busca, não será cobrado novamente se o LeadAccess já existir.
2.5. Busca de Leads do Cache (get_leads_from_cache)
Não conforme: mesmo problema — só debita se created=True.
services.pyLines 1083-1103
            # Criar LeadAccess e debitar crédito (é novo acesso)            lead_access, created = LeadAccess.objects.get_or_create(                user=user_profile,                lead=lead,                defaults={                    'search': search_obj,                    'credits_paid': 1,                }            )                        # Se é novo acesso, debitar crédito            if created:                success, new_balance, error = debit_credits(                    user_profile,                    1,                    description=f"Lead (cache): {lead.name}"                )                                if not success:                    logger.warning(f"Erro ao debitar crédito para lead {lead.id}: {error}")                    # Continuar mesmo se débito falhar (já criou LeadAccess)
2.6. Busca de Leads Existentes (get_existing_leads_from_db)
Não conforme: mesmo problema.
services.pyLines 972-992
            # Criar LeadAccess e debitar crédito (é novo acesso)            lead_access, created = LeadAccess.objects.get_or_create(                user=user_profile,                lead=lead,                defaults={                    'search': search_obj,                    'credits_paid': 1,                }            )                        # Se é novo acesso, debitar crédito            if created:                success, new_balance, error = debit_credits(                    user_profile,                    1,                    description=f"Lead (base existente): {lead.name}"                )                                if not success:                    logger.warning(f"Erro ao debitar crédito para lead {lead.id}: {error}")                    # Continuar mesmo se débito falhar (já criou LeadAccess)
Conclusão: inconsistência entre a regra de negócio e a implementação. Em buscas assíncronas, o sistema não cobra novamente se o LeadAccess já existir, mesmo que o lead seja visualizado em uma nova busca.
3. Fluxo de Reembolso - Falhas na API Externa Após Débito
Status: Não conforme — reembolso não implementado
Análise:
3.1. Modelo de Dados
O modelo suporta reembolso, mas não há implementação:
models.pyLines 116-133
class CreditTransaction(models.Model):    TRANSACTION_TYPES = [        ('purchase', 'Compra'),        ('usage', 'Uso'),        ('refund', 'Reembolso'),    ]    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='credit_transactions')    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)    amount = models.IntegerField()  # Positivo para compra, negativo para uso    stripe_payment_intent_id = models.CharField(max_length=255, null=True, blank=True)    description = models.TextField(null=True, blank=True)    created_at = models.DateTimeField(auto_now_add=True)    class Meta:        ordering = ['-created_at']    def __str__(self):        return f"{self.get_transaction_type_display()} - {self.amount} créditos - {self.user.email}"
3.2. Cenários de Falha Sem Reembolso
Cenário 1: Falha na API Viper após débito (busca por CNPJ)
views.pyLines 708-730
            # Debitar crédito            success, new_balance, error = debit_credits(                user_profile,                1,                description=f"Busca rápida por CNPJ: {cnpj_clean}"            )                        if success:                messages.success(request, 'Busca realizada com sucesso!')                # Garantir que data está atualizado no lead                if lead.viper_data != data:                    lead.viper_data = data                    lead.save(update_fields=['viper_data'])                                context = {                    'lead': lead,  # Usar lead real para o template                    'cnpj': cnpj_clean,                    'data': data,  # Usar data diretamente (garantido estar definido)                    'user_profile': user_profile,                    'available_credits': new_balance,                }                return render(request, 'lead_extractor/cnpj_result.html', context)            else:                messages.error(request, f'Erro ao debitar crédito: {error}')
Problema: o débito ocorre antes de validar se os dados da API estão completos. Se a API falhar após o débito, não há reembolso.
Cenário 2: Falha na busca de sócios após débito
views.pyLines 1278-1317
                # IMPORTANTE: Debitar crédito ANTES de buscar/exibir sócios                success, new_balance, error = debit_credits(                    user_profile,                    1,                    description=f"Sócios (QSA) para {lead.name} (CNPJ: {lead.cnpj})"                )                                if not success:                    errors.append(f"Erro ao debitar crédito para {lead.name}: {error}")                    continue                                credits_debited += 1                                # Verificar se já tem sócios salvos no banco (usando função helper robusta)                has_partners = has_valid_partners_data(lead)                                if has_partners:                    # Dados já existem - usar dados salvos (não fazer nova requisição à API)                    logger.info(f"Usando dados de sócios já salvos para Lead {lead.id} (CNPJ: {lead.cnpj}) - não será enfileirado")                else:                    # Dados não existem - buscar via API (mas não aguardar - processar em background)                    if not lead.cnpj:                        errors.append(f"Lead {lead.name} não possui CNPJ")                        continue                                        # Enfileirar busca de sócios (processamento assíncrono)                    queue_result = get_partners_internal_queued(lead.cnpj, user_profile, lead=lead)                    queue_id = queue_result.get('queue_id')                    is_new = queue_result.get('is_new', True)                                        if not queue_id:                        errors.append(f"Erro ao enfileirar busca de sócios para {lead.name}")                        continue
Problema: se a fila falhar ou a API retornar erro, o crédito já foi debitado e não há reembolso.
Cenário 3: Falha na busca de CPF após débito
views.pyLines 1407-1452
                # IMPORTANTE: Debitar crédito ANTES de buscar/exibir dados                success, new_balance, error = debit_credits(                    user_profile,                    1,                    description=f"Busca por CPF: {cpf} ({socio_name})"                )                                if not success:                    errors.append(f"Erro ao debitar crédito para CPF {cpf}: {error}")                    continue                                credits_debited += 1                                # Verificar se já tem dados do CPF salvos no lead                viper_data = lead.viper_data or {}                socios_qsa = viper_data.get('socios_qsa', {})                socios_list = socios_qsa.get('socios', []) if isinstance(socios_qsa, dict) else []                                cpf_clean = cpf.replace('.', '').replace('-', '').strip()                cpf_data = None                found_socio = None                                # Buscar sócio pelo CPF e verificar se já tem dados enriquecidos                # NOTA: API Viper retorna CPF no campo 'DOCUMENTO', não 'CPF' ou 'cpf'                for socio in socios_list:                    socio_cpf = str(socio.get('DOCUMENTO') or socio.get('CPF') or socio.get('cpf') or '').replace('.', '').replace('-', '').strip()                    if socio_cpf == cpf_clean:                        found_socio = socio                        # Verificar se já tem dados do CPF                        if socio.get('cpf_enriched') and socio.get('cpf_data'):                            # Usar dados salvos (não fazer nova requisição à API)                            logger.info(f"Usando dados de CPF já salvos para {cpf}")                            cpf_data = socio.get('cpf_data')                        break                                if not found_socio:                    errors.append(f"Sócio com CPF {cpf} não encontrado no lead {lead_id}")                    continue                                if not cpf_data:                    # Dados não existem - buscar via API                    cpf_data = search_cpf_viper(cpf_clean)                                        if not cpf_data:                        errors.append(f"Não foi possível obter dados para CPF {cpf}")                        continue
Problema: se search_cpf_viper retornar None, o crédito já foi debitado e não há reembolso.
3.3. Função de Reembolso Ausente
Não existe função refund_credits em credit_service.py. O tipo 'refund' existe no modelo, mas não é utilizado.
Resumo Executivo
Aspecto	Status	Severidade	Observações
Integridade Financeira (Double Spending)	Conforme	Baixa	Proteções adequadas com select_for_update() e F() expressions
Regras de Cobrança (Busca CNPJ/CPF/Sócios)	Conforme	-	Implementado corretamente
Regras de Cobrança (Busca Assíncrona)	Não Conforme	Média	Não cobra novamente se LeadAccess já existe
Fluxo de Reembolso	Não Conforme	Alta	Sem reembolso quando APIs falham após débito
Recomendações Prioritárias
Alta prioridade
Implementar função de reembolso: criar refund_credits() em credit_service.py e utilizá-la quando APIs externas falharem após o débito.
Revisar lógica de cobrança em buscas assíncronas: garantir que a visualização de leads em novas buscas sempre cobre crédito, mesmo se LeadAccess já existir (ou ajustar a regra de negócio se a intenção for não cobrar novamente).
Média prioridade
Adicionar rollback de transação: garantir que falhas na criação de CreditTransaction revertam o débito de créditos.
Implementar retry com reembolso: para APIs externas, implementar retry e, se falhar após tentativas, reembolsar.
Baixa prioridade
Adicionar métricas: rastrear débitos sem sucesso correspondente para identificar possíveis perdas de crédito.
Melhorar logging: registrar todos os casos onde créditos são debitados mas a operação falha.
Conclusão
O sistema tem proteções contra double spending, mas há duas lacunas críticas:
Regra de cobrança inconsistente em buscas assíncronas.
Ausência de reembolso quando APIs externas falham após o débito.
Essas lacunas podem resultar em perda de créditos para usuários e inconsistências financeiras. Recomenda-se implementar as correções de alta prioridade antes de escalar o sistema.
]

⚙️ 3. Fase 2: Estabilidade Operacional

Objetivo: Impedir quedas do servidor por falta de recursos e tornar as filas de processamento inquebráveis.

📝 Itens de Ação:

Gestão de Recursos VPS: Ajustar Gunicorn para 3 workers (para 2 cores CPU) e ativar RotatingFileHandler no LOGGING do Django para evitar que o disco encha.

Resiliência da Fila Viper: Implementar Stale Detection no viper_queue_service.py para resetar itens que fiquem em status processing por mais de 30 minutos.

Timeout e Retry: Adicionar timeouts explícitos em todas as chamadas de subprocesso e implementar retry com backoff exponencial na fila.

📑 Relatório de Referência (SRE & Estabilidade)

[Relatório de Estabilidade SRE - Sistema de Extração de Leads
1. Resiliência do Bot de Autenticação (auth_bot.py)
Pontos únicos de falha identificados
1.1 Dependência de cron job único
Problema: Renovação de tokens depende de um único cron job (0 */6 * * *)
Risco: Se o cron falhar silenciosamente, tokens expiram sem renovação automática
Impacto: Alto — sistema fica sem autenticação após 6 horas
1.2 Falta de validação de expiração proativa
auth_bot.pyLines 73-183
def refresh_viper_tokens() -> bool:    """    Faz login no Viper e captura tokens de autenticação.        Returns:        bool: True se capturou tokens com sucesso, False caso contrário    """
Problema: Não há verificação de expiração antes de usar tokens
Risco: Tokens podem expirar entre renovações do cron
Impacto: Médio — requisições falham até detecção de 401
1.3 Execução síncrona do auth_bot durante requisições
services.pyLines 433-500
def get_partners_internal(cnpj, retry=True):    """    Busca o QSA (Quadro de Sócios e Administradores) na API interna do Viper.        Fluxo:    1. Tenta ler tokens do arquivo    2. Se não tem tokens e retry=True, executa auth_bot    3. Faz requisição à API    4. Se receber 401 e retry=True, renova tokens e tenta novamente
Problema: run_auth_bot() roda síncronamente (até 90s) durante requisições
Risco: Timeout de requisições, bloqueio de workers, experiência ruim
Impacto: Alto — degradação de performance
1.4 Race condition no arquivo de tokens
auth_bot.pyLines 32-71
def save_tokens_atomic(data: dict) -> bool:    """    Salva tokens de forma atômica para evitar race conditions.    Escreve em arquivo temporário e depois renomeia.
Status: Implementado corretamente com write-temp-then-rename
Nota: get_auth_headers() usa file locking, mas há risco se múltiplos processos escreverem simultaneamente
Planos de mitigação
Health check de tokens
Adicionar verificação de expiração antes de usar
Renovar proativamente quando próximo do vencimento
Sistema de alertas
Monitorar falhas do cron
Alertar quando tokens não forem renovados em 5 horas
Execução assíncrona
Mover renovação de tokens para fila de background
Evitar execução síncrona durante requisições HTTP
Redundância do cron
Adicionar segundo cron com offset (ex: 3h) como backup
Verificar se tokens foram atualizados nas últimas 6 horas
2. Gerenciamento de Fila (process_viper_queue.py)
Análise de locks e deadlocks
2.1 Uso correto de skip_locked=True
viper_queue_service.pyLines 122-150
def process_next_request():    """    Processa o próximo item da fila (com lock atômico).    Retorna o objeto processado ou None se não houver itens.        Returns:        ViperRequestQueue: Item processado ou None    """    with transaction.atomic():        # Buscar próximo item com lock (skip_locked=True para evitar deadlock)        next_item = ViperRequestQueue.objects.select_for_update(            skip_locked=True        ).filter(            status='pending'        ).order_by(            '-priority',  # Maior prioridade primeiro            'created_at'  # Mais antigo primeiro dentro da mesma prioridade        ).first()
Status: Implementado corretamente — skip_locked=True evita deadlocks
Nota: Múltiplos workers podem rodar sem conflito
2.2 Risco de itens presos em "processing"
Problema: Se o worker morrer durante processamento, item fica em processing indefinidamente
Impacto: Alto — itens ficam presos, fila para de processar
2.3 Falta de timeout de processamento
process_viper_queue.pyLines 98-192
        while True:            try:                # Buscar próximo item da fila (com lock)                queue_item = process_next_request()                                if queue_item:                    self.stdout.write(f'Processando requisição {queue_item.id} (tipo: {queue_item.request_type})...')                                        try:                        # Processar baseado no tipo de requisição                        if queue_item.request_type == 'partners':                            cnpj = queue_item.request_data.get('cnpj')                            if not cnpj:                                raise ValueError('CNPJ não encontrado nos dados da requisição')                                                        # Chamar função original (sem retry aqui, pois já está na fila)                            result = get_partners_internal(cnpj, retry=True)
Problema: Não há timeout máximo por item
Risco: Requisição pode travar indefinidamente
Impacto: Médio — worker fica bloqueado
2.4 Falta de retry automático para falhas
process_viper_queue.pyLines 160-164
                    except Exception as e:                        error_msg = str(e)                        mark_request_failed(queue_item, error_msg)                        self.stdout.write(self.style.ERROR(f'✗ Requisição {queue_item.id} falhou: {error_msg}'))                        logger.error(f"Erro ao processar requisição {queue_item.id}: {error_msg}", exc_info=True)
Problema: Falhas são marcadas como failed sem retry
Risco: Falhas transitórias (rede, timeout) não são recuperadas
Impacto: Médio — perda de requisições válidas
Planos de mitigação
Stale detection
Detectar itens em processing há mais de X minutos (ex: 30)
Resetar para pending automaticamente
Timeout por requisição
Adicionar timeout máximo (ex: 5 minutos)
Marcar como failed se exceder
Retry com backoff
Adicionar campo retry_count ao modelo
Retry automático até N tentativas com backoff exponencial
Heartbeat do worker
Worker atualiza timestamp periodicamente
Detectar workers mortos e resetar seus itens
3. Infraestrutura (Supervisor e Nginx)
3.1 Configuração do Supervisor
Gunicorn (nitroleads.conf)
nitroleads.confLines 9-40
[program:nitroleads]# Comando para executar o Gunicorn# Workers: 2n+1 onde n = número de CPUs. Para 2 cores: 5 workers (otimizado para performance)command=/home/nitroleads/apps/nitroleads/venv/bin/gunicorn lead_extraction.wsgi:application --bind 127.0.0.1:8000 --workers 5 --timeout 120 --threads 2
Problema: 5 workers para 2 cores pode ser excessivo
Risco: Sobrecarga de memória em servidor compartilhado (Hostinger)
Impacto: Médio — possível OOM kill
Processador de fila (nitroleads-queue.conf)
nitroleads-queue.confLines 13-59
[program:nitroleads-queue]# Comando para executar o processador de filacommand=/home/nitroleads/apps/nitroleads/venv/bin/python /home/nitroleads/apps/nitroleads/manage.py process_viper_queue# Diretório de trabalho (IMPORTANTE: auth_bot.py e viper_tokens.json estão aqui)directory=/home/nitroleads/apps/nitroleads# Usuário que executa o processouser=nitroleads# Iniciar automaticamente quando o supervisor iniciarautostart=true# Reiniciar automaticamente se o processo morrerautorestart=true# Arquivos de logstderr_logfile=/home/nitroleads/logs/nitroleads/viper_queue_error.logstdout_logfile=/home/nitroleads/logs/nitroleads/viper_queue.log# Tamanho máximo dos arquivos de log (10MB)stderr_logfile_maxbytes=10MBstdout_logfile_maxbytes=10MB# Manter 5 backups dos logsstderr_logfile_backups=5stdout_logfile_backups=5# Tempo máximo de espera ao parar o processo (10 minutos para processar requisição atual)stopwaitsecs=600# Matar todo o grupo de processos ao pararkillasgroup=true# Prioridade (menor número = inicia primeiro)priority=998
Problema: stopwaitsecs=600 (10 minutos) pode ser longo
Risco: Reinício lento do serviço
Impacto: Baixo — apenas em manutenção
Problema: Falta startretries e startsecs
Risco: Reinício excessivo se houver falha inicial
Impacto: Médio — loop de reinício
3.2 Configuração do Nginx
nginx-security-rules.confLines 1-32
# Regras de Segurança para Nginx - NitroLeads# Adicionar estas regras ao arquivo de configuração do Nginx# Bloquear acesso ao diretório secure/ e arquivos de tokenslocation ~ ^/(secure|viper_tokens\.json) {    deny all;    return 404;}
Status: Regras de segurança adequadas
Nota: Verificar se estão aplicadas no nginx principal
Planos de mitigação
Ajustar workers do Gunicorn
Reduzir para 3 workers (2 cores)
Monitorar uso de memória
Adicionar limites de recursos
stopasgroup=true e killasgroup=true já presentes
Adicionar startretries=3 e startsecs=10
Timeout do Gunicorn
--timeout 120 pode ser curto para requisições longas
Avaliar aumentar para 180s ou adicionar endpoint de health check
4. Logs e Monitoramento
4.1 Configuração atual de logs
Django logging
settings.pyLines 176-217
# Logging ConfigurationLOGGING = {    'version': 1,    'disable_existing_loggers': False,    'formatters': {        'verbose': {            'format': '{levelname} {asctime} {module} {message}',            'style': '{',        },        'simple': {            'format': '{levelname} {message}',            'style': '{',        },    },    'handlers': {        'console': {            'class': 'logging.StreamHandler',            'formatter': 'verbose',        },        'file': {            'class': 'logging.FileHandler',            'filename': BASE_DIR / 'logs' / 'django.log',            'formatter': 'verbose',        },    },    'root': {        'handlers': ['console'],        'level': 'INFO',    },    'loggers': {        'django': {            'handlers': ['console', 'file'],            'level': config('DJANGO_LOG_LEVEL', default='INFO'),            'propagate': False,        },        'lead_extractor': {            'handlers': ['console', 'file'],            'level': 'INFO',            'propagate': False,        },    },}
Problemas identificados
Logs sem rotação automática
django.log pode crescer indefinidamente
Risco: Disco cheio, performance degradada
Impacto: Alto
Falta de logs estruturados
Formato texto dificulta análise
Sem correlação de requisições (request_id)
Impacto: Médio — depuração difícil
Logs do auth_bot separados
Cron redireciona para /home/nitroleads/logs/nitroleads/auth_bot.log
Não integrado com logs do Django
Impacto: Médio — visibilidade fragmentada
Falta de métricas
Sem métricas de fila (tamanho, tempo de processamento)
Sem alertas de falhas
Impacto: Alto — problemas não detectados
Logs do Supervisor limitados
Rotação configurada (10MB, 5 backups)
Sem integração com sistema centralizado
Impacto: Baixo — aceitável para ambiente pequeno
Planos de mitigação
Rotação de logs do Django
Usar RotatingFileHandler ou TimedRotatingFileHandler
Limitar tamanho e manter backups
Logs estruturados
Adicionar request_id em todas as requisições
Considerar JSON logging para análise
Health checks e métricas
Endpoint /health com status de componentes
Métricas básicas: tamanho da fila, taxa de sucesso/falha
Dashboard simples ou integração com ferramentas
Alertas críticos
Falhas consecutivas do auth_bot
Fila com mais de X itens pendentes
Itens presos em processing
Log aggregation
Centralizar logs do Django, Supervisor e cron
Ferramenta simples (ex: multitail) ou serviço externo
5. Cenários de falha previstos
Cenário 1: Token expira durante madrugada
Causa: Cron falha ou token expira antes da renovação
Sintomas: Requisições retornam 401, fila para de processar
Detecção: Logs de erro 401, fila cresce
Mitigação: Health check de tokens, alertas, retry automático
Cenário 2: Worker morre durante processamento
Causa: OOM kill, crash, reinício do servidor
Sintomas: Itens presos em processing, fila para
Detecção: Stale detection, monitoramento de workers
Mitigação: Auto-recovery, reset de itens presos
Cenário 3: Fila cresce além da capacidade
Causa: Pico de requisições ou processamento lento
Sintomas: Tempo de resposta alto, timeouts
Detecção: Métricas de tamanho da fila
Mitigação: Scaling horizontal, priorização, rate limiting
Cenário 4: Disco cheio por logs
Causa: Logs sem rotação crescem indefinidamente
Sintomas: Aplicação para de escrever logs, possível falha
Detecção: Monitoramento de espaço em disco
Mitigação: Rotação automática, limpeza de logs antigos
Cenário 5: Múltiplas execuções do auth_bot simultâneas
Causa: Cron e requisição HTTP executam ao mesmo tempo
Sintomas: Race condition, possível corrupção de tokens
Detecção: Logs de conflito
Mitigação: Lock distribuído ou fila única para renovação
6. Resumo executivo
Prioridade alta
Stale detection para itens presos em processing
Rotação automática de logs do Django
Health check e alertas de tokens
Retry automático com backoff para falhas transitórias
Prioridade média
Reduzir workers do Gunicorn (3 em vez de 5)
Timeout máximo por item da fila
Logs estruturados com request_id
Métricas básicas de fila
Prioridade baixa
Redundância do cron (backup com offset)
Dashboard de monitoramento
Log aggregation centralizado
Ajustes finos de timeouts
7. Recomendações imediatas
Implementar stale detection (1-2 horas)
Adicionar rotação de logs (30 minutos)
Criar health check endpoint (1 hora)
Reduzir workers do Gunicorn (5 minutos)
Adicionar alertas básicos (2-3 horas)
Este relatório identifica os principais riscos de estabilidade. Recomendo começar pelas ações de prioridade alta para melhorar a resiliência do sistema.]

🏗️ 4. Fase 3: Estrutura e Escalabilidade

Objetivo: Organizar o código para permitir a entrada de novas APIs e facilitar a manutenção.

📝 Itens de Ação:

Modularização (Desmembramento): Dividir views.py e services.py (atualmente com +1500 linhas) em pastas e módulos por domínio (Ex: services/lead_service.py, services/search_service.py).

Abstração de Busca (Providers): Implementar a interface SearchProvider (Classe Abstrata) para desacoplar o sistema da API específica do Serper.

Camada de Serviço (Services): Remover regras de negócio, validações de CPF e cálculos de créditos das Views, centralizando-as em métodos de Service testáveis.

📑 Relatório de Referência (Arquitetura)

[Relatório de revisão arquitetural — Lead Extraction SaaS
1. Acoplamento: Views vs Services
Problemas identificados
1.1 Regras de negócio nas views
has_valid_partners_data() em views.py (linhas 28-65): lógica de validação que deveria estar em services.py ou em um método do modelo.
Normalização de dados de CPF em search_by_cpf() (linhas 432-532): lógica de normalização misturada com apresentação.
Lógica de enriquecimento em enrich_leads() (linhas 1108-1223): validações e processamento que deveriam estar em services.
1.2 Views fazendo queries diretas
dashboard() (linha 232): queries diretas no modelo.
export_leads_csv() (linha 288): queries complexas na view.
search_history() (linha 775): queries com prefetch na view.
1.3 Processamento assíncrono na view
dashboard() (linha 217): criação de thread diretamente na view. Deveria estar em um service ou task queue.
Recomendações
Mover has_valid_partners_data() para services.py ou criar método no modelo Lead.
Criar LeadService para centralizar operações de leads.
Extrair lógica de normalização de CPF para services.py.
Usar Celery ou Django-Q para processamento assíncrono.
2. DRY (Don't Repeat Yourself)
Duplicações identificadas
2.1 Busca e enriquecimento de leads
Padrão repetido em múltiplos lugares:
# Padrão repetido em: process_search_async, enrich_leads, search_partnerscnpj = find_cnpj_by_name(company_name)public_data = enrich_company_viper(cnpj)if public_data:    company_data['viper_data'].update(public_data)
Ocorrências:
process_search_async() (linhas 1450-1465)
enrich_leads() (linhas 1173-1195)
search_incremental() (linhas 1235-1242)
2.2 Criação/atualização de Lead
Padrão repetido:
existing_lead = Lead.objects.filter(cnpj=cnpj).first()if existing_lead:    lead_obj = existing_lead    # Atualizar dados...else:    lead_obj = Lead.objects.create(...)
Ocorrências:
process_search_async() (linhas 1468-1488)
search_incremental() (linhas 1657-1677)
2.3 Sanitização de dados
Padrão repetido:
sanitized_viper_data = sanitize_lead_data(    {'viper_data': lead.viper_data or {}},    show_partners=(lead_access.enriched_at is not None)).get('viper_data', {})
Ocorrências:
get_existing_leads_from_db() (linhas 995-998)
get_leads_from_cache() (linhas 1106-1109)
process_search_async() (linhas 1515-1518)
2.4 Validação de créditos
Padrão repetido:
available_credits = check_credits(user_profile)if available_credits < quantity:    return JsonResponse({'error': 'Créditos insuficientes'}, status=402)
Ocorrências:
search_by_cpf() (linha 420)
search_by_cnpj() (linha 625)
enrich_leads() (linha 1131)
search_partners() (linha 1253)
2.5 Formatação de dados de CPF
Lógica de normalização duplicada em search_by_cpf() (linhas 432-532) e possivelmente em outros lugares.
Recomendações
Criar LeadEnrichmentService com métodos:
enrich_lead_by_cnpj(cnpj) → retorna dados enriquecidos
get_or_create_lead(place_data, cnpj) → cria/atualiza lead
format_lead_for_response(lead, user_profile) → sanitiza e formata
Criar CreditValidationService:
validate_credits(user_profile, required_amount) → valida e retorna erro padronizado
Extrair normalização de CPF para services.py:
normalize_cpf_response(cpf_data) → normaliza resposta da API
3. Padronização Django 4.2
Pontos positivos
Uso de JSONField para dados flexíveis
select_related e prefetch_related em alguns lugares
Transações atômicas em credit_service.py
Middleware customizado bem estruturado
Decorators reutilizáveis (require_user_profile, validate_user_ownership)
Problemas identificados
3.1 Falta de Class-Based Views (CBV)
Todas as views são function-based. Django 4.2 recomenda CBVs para:
Reutilização de código
Mixins para funcionalidades comuns
Melhor organização
Exemplo:
# Atual (function-based)def dashboard(request):    ...# Recomendado (CBV)class DashboardView(LoginRequiredMixin, TemplateView):    template_name = 'lead_extractor/dashboard.html'        def post(self, request, *args, **kwargs):        ...
3.2 Falta de Forms
Validação manual em vez de Django Forms:
# Atual (validação manual)niche = request.POST.get('niche', '').strip()if not niche or not location:    messages.error(request, 'Por favor, preencha o nicho e a localização.')
Deveria usar:
class SearchForm(forms.Form):    niche = forms.CharField(max_length=255)    location = forms.CharField(max_length=255)    quantity = forms.IntegerField(min_value=1, max_value=1000)
3.3 Falta de Managers customizados
Queries repetidas que poderiam estar em Managers:
# Em models.pyclass LeadManager(models.Manager):    def with_cnpj(self):        return self.exclude(cnpj__isnull=True).exclude(cnpj='')        def by_cached_search(self, cached_search):        return self.filter(cached_search=cached_search).with_cnpj()
3.4 Falta de Signals
Lógica pós-criação que poderia usar Signals:
# Em models.py ou signals.py@receiver(post_save, sender=Lead)def update_cached_search_count(sender, instance, created, **kwargs):    if created and instance.cached_search:        # Atualizar contador...
3.5 Falta de API Views estruturadas
Endpoints JSON poderiam usar Django REST Framework ou pelo menos views mais estruturadas.
Recomendações
Migrar views principais para CBVs (gradualmente)
Criar Forms para validação de entrada
Adicionar Managers customizados para queries comuns
Usar Signals para lógica pós-criação/atualização
Considerar Django REST Framework para APIs
4. Manutenibilidade: adicionar nova API de busca
Dificuldades atuais
4.1 Lógica espalhada
Para adicionar uma nova API (ex: Bing Places), seria necessário:
Adicionar função em services.py (ex: search_bing_places())
Modificar process_search_async() para incluir nova API
Modificar search_google_hybrid() ou criar função similar
Atualizar normalização em normalize_places_response()
Atualizar múltiplas views que usam busca
4.2 Falta de abstração
Não há interface/classe base para APIs de busca. Cada API tem sua própria implementação.
4.3 Acoplamento forte
process_search_async() está fortemente acoplado ao Serper/Google Maps.
Estrutura recomendada
4.1 Criar interface base para APIs
# lead_extractor/services/search_providers.pyfrom abc import ABC, abstractmethodclass SearchProvider(ABC):    @abstractmethod    def search(self, query: str, num: int = 10, start: int = 0) -> list:        """Busca lugares e retorna lista normalizada"""        pass        @abstractmethod    def normalize_response(self, response_data: dict) -> list:        """Normaliza resposta da API para formato padrão"""        passclass SerperSearchProvider(SearchProvider):    def search(self, query: str, num: int = 10, start: int = 0) -> list:        # Implementação atual de search_google_maps        passclass BingPlacesProvider(SearchProvider):    def search(self, query: str, num: int = 10, start: int = 0) -> list:        # Nova implementação        pass
4.2 Service de busca unificado
# lead_extractor/services/search_service.pyclass SearchService:    def __init__(self, providers: list[SearchProvider]):        self.providers = providers        def search(self, query: str, max_results: int) -> list:        """Busca usando múltiplos provedores"""        all_results = []        for provider in self.providers:            results = provider.search(query, num=max_results)            all_results.extend(results)            if len(all_results) >= max_results:                break        return all_results[:max_results]
4.3 Factory pattern para provedores
# lead_extractor/services/search_factory.pydef get_search_providers() -> list[SearchProvider]:    """Retorna lista de provedores configurados"""    providers = []        if config('SERPER_API_KEY'):        providers.append(SerperSearchProvider())        if config('BING_API_KEY'):        providers.append(BingPlacesProvider())        return providers
Benefícios
Adicionar nova API: criar classe que implementa SearchProvider
Configuração centralizada via factory
Testes isolados por provedor
Fácil trocar ordem/prioridade de provedores
5. Estrutura de pastas
Estrutura atual
lead_extractor/├── services.py (1761 linhas!) ❌├── views.py (1564 linhas!) ❌├── models.py├── credit_service.py├── stripe_service.py├── viper_queue_service.py└── decorators.py
Problemas
Arquivos muito grandes (services.py com 1761 linhas, views.py com 1564 linhas)
Falta de organização por domínio
Tudo misturado em poucos arquivos
Estrutura recomendada
lead_extractor/├── models/│   ├── __init__.py│   ├── user.py│   ├── lead.py│   ├── search.py│   └── credit.py├── services/│   ├── __init__.py│   ├── search/│   │   ├── __init__.py│   │   ├── search_service.py│   │   ├── search_providers.py│   │   └── search_factory.py│   ├── enrichment/│   │   ├── __init__.py│   │   ├── lead_enrichment.py│   │   └── viper_enrichment.py│   ├── credit/│   │   ├── __init__.py│   │   └── credit_service.py (mover de credit_service.py)│   └── payment/│       ├── __init__.py│       └── stripe_service.py (mover de stripe_service.py)├── views/│   ├── __init__.py│   ├── auth.py│   ├── dashboard.py│   ├── search.py│   ├── lead.py│   └── payment.py├── api/│   ├── __init__.py│   ├── views.py (endpoints JSON)│   └── serializers.py (se usar DRF)└── utils/    ├── __init__.py    ├── decorators.py    └── validators.py
Resumo executivo
Prioridade alta
Extrair regras de negócio das views para services
Criar LeadService e LeadEnrichmentService para eliminar duplicação
Refatorar process_search_async() para usar abstração de provedores de busca
Dividir services.py e views.py em módulos menores
Prioridade média
Migrar para Class-Based Views gradualmente
Criar Forms para validação
Adicionar Managers customizados nos models
Implementar interface SearchProvider para novas APIs
Prioridade baixa
Considerar Django REST Framework para APIs
Usar Signals para lógica pós-criação
Reorganizar estrutura de pastas por domínio
Métricas de qualidade
Métrica	Atual	Recomendado
Linhas por arquivo	1761 (services.py)	< 500
Acoplamento Views-Services	Alto	Baixo
Duplicação de código	~30%	< 5%
Facilidade de adicionar API	Difícil	Fácil
Testabilidade	Média	Alta
Conclusão
O projeto funciona, mas precisa de refatoração arquitetural para escalar. Os principais problemas são:
Acoplamento forte entre views e lógica de negócio
Duplicação significativa de código
Falta de abstração para adicionar novas APIs
Arquivos muito grandes dificultando manutenção
Com as melhorias sugeridas, o código ficará mais:
Manutenível: fácil de entender e modificar
Testável: lógica isolada e testável
Escalável: fácil adicionar novas funcionalidades
Padronizado: segue práticas do Django 4.2]

⚡ 5. Fase 4: Velocidade e UX

Objetivo: Reduzir o tempo de carregamento das páginas e o consumo de memória do servidor.

📝 Itens de Ação:

Otimização SQL: Aplicar .defer('viper_data') em todas as consultas de listagem (Dashboard/Histórico) para não carregar JSONs pesados desnecessariamente.

Índices de Banco: Criar índices parciais no PostgreSQL para filtrar CNPJs válidos e índices GIN para o campo request_data na fila.

Sanitização Eficiente: Refatorar sanitize_lead_data para evitar copy.deepcopy(), utilizando construção seletiva de dicionários.

📑 Relatório de Referência (Performance & DB)

[Relatório de Performance e Otimização de Banco de Dados
1. Gargalos de Query (N+1)
Problemas identificados
1.1 Carregamento completo de viper_data em loops
Localização: services.py - funções get_leads_from_cache() e get_existing_leads_from_db()
Problema:
services.pyLines 1072-1120
        # Processar leads que o usuário ainda não acessou        for lead in cached_leads_new:            if len(results) >= quantity:                break                            cnpj = lead.cnpj                        # Evitar duplicatas na mesma busca            if cnpj in cnpjs_processed:                continue            cnpjs_processed.add(cnpj)                        # Criar LeadAccess e debitar crédito (é novo acesso)            lead_access, created = LeadAccess.objects.get_or_create(                user=user_profile,                lead=lead,                defaults={                    'search': search_obj,                    'credits_paid': 1,                }            )                        # Se é novo acesso, debitar crédito            if created:                success, new_balance, error = debit_credits(                    user_profile,                    1,                    description=f"Lead (cache): {lead.name}"                )                                if not success:                    logger.warning(f"Erro ao debitar crédito para lead {lead.id}: {error}")                    # Continuar mesmo se débito falhar (já criou LeadAccess)                        # Sanitizar dados (esconder QSA/telefones até enriquecer)            sanitized_viper_data = sanitize_lead_data(                {'viper_data': lead.viper_data or {}},                show_partners=(lead_access.enriched_at is not None)            ).get('viper_data', {})
Impacto: cada iteração carrega o JSON completo de viper_data (pode ter centenas de KB), mesmo quando só campos básicos são usados.
1.2 Consulta N+1 em export_leads_csv
Localização: views.py:288
Problema:
views.pyLines 288-303
    # Buscar leads via LeadAccess (garantindo ownership)    # Usar select_related para evitar N+1 queries    lead_accesses = LeadAccess.objects.filter(user=user_profile).select_related('lead', 'search', 'lead__cached_search').order_by('-accessed_at')        # Se search_id fornecido, filtrar por pesquisa (já validado acima)    is_last_search = False    if search_id:        lead_accesses = lead_accesses.filter(search=search_obj)                # Verificar se é a última pesquisa (mais recente)        last_search = Search.objects.filter(user=user_profile).order_by('-created_at').first()        if last_search and last_search.id == search_id:            is_last_search = True    # Contar leads para log de auditoria    leads_count = lead_accesses.count()    for lead_access in lead_accesses:
Impacto: select_related está presente, mas lead.viper_data é carregado completo para todos os registros, mesmo que só alguns campos sejam usados.
1.3 Múltiplas consultas em get_existing_leads_from_db
Localização: services.py:936-948
Problema:
services.pyLines 936-948
        # Buscar CNPJs que o usuário já tem acesso nas 3 últimas pesquisas        last_3_searches = Search.objects.filter(            user=user_profile        ).order_by('-created_at')[:3]                accessed_cnpjs = set()        if last_3_searches.exists():            last_3_search_ids = set(last_3_searches.values_list('id', flat=True))            accessed_cnpjs = set(                LeadAccess.objects.filter(                    user=user_profile,                    search_id__in=last_3_search_ids                ).values_list('lead__cnpj', flat=True)            )
Impacto: 3 queries separadas (Search, values_list, LeadAccess) que poderiam ser reduzidas.
Recomendações
Usar .defer('viper_data') ou .only() em queries que não precisam do JSON completo:
# Em get_leads_from_cache e get_existing_leads_from_dbcached_leads_new = Lead.objects.filter(    cached_search=cached_search,    cnpj__isnull=False).exclude(cnpj='').defer('viper_data').order_by('-created_at')[:quantity * 3]# Carregar viper_data apenas quando necessário (lazy loading)# Ou usar .only('id', 'name', 'address', 'phone_maps', 'cnpj', 'cached_search_id')
Otimizar get_existing_leads_from_db com uma única query:
# Substituir 3 queries por 1 usando Subqueryfrom django.db.models import OuterRef, Subqueryaccessed_cnpjs = set(    LeadAccess.objects.filter(        user=user_profile,        search__in=Search.objects.filter(            user=user_profile        ).order_by('-created_at')[:3]    ).values_list('lead__cnpj', flat=True).distinct())
Adicionar prefetch_related em search_history:
# views.py:775searches = Search.objects.filter(user=user_profile).select_related(    'user', 'cached_search').prefetch_related(    'lead_accesses__lead'  # Já existe, mas pode melhorar).only(    'id', 'niche', 'location', 'created_at', 'status', 'results_count').order_by('-created_at')[:3]
2. Estratégia de Indexação
Índices faltantes
2.1 LeadAccess - busca por usuário e data
Localização: models.py:182-186
Problema:
models.pyLines 182-186
        indexes = [            models.Index(fields=['user', 'accessed_at']),            models.Index(fields=['lead', 'user']),            models.Index(fields=['search', 'user']),        ]
Análise: o índice ['user', 'accessed_at'] existe, mas a ordem pode não ser ideal para order_by('-accessed_at'). PostgreSQL pode não usar o índice de forma eficiente em ordenação descendente.
Recomendação:
# Adicionar índice funcional para ordenação descendente# Ou criar índice composto otimizadoindexes = [    models.Index(fields=['user', '-accessed_at']),  # PostgreSQL suporta DESC    models.Index(fields=['lead', 'user']),    models.Index(fields=['search', 'user']),    # Novo: índice para buscas frequentes de CNPJs acessados    models.Index(fields=['user', 'lead__cnpj'], name='leadaccess_user_cnpj_idx'),]
2.2 Lead - busca por CNPJ e cached_search
Localização: models.py:159-162
Problema:
models.pyLines 159-162
        indexes = [            models.Index(fields=['cnpj']),            models.Index(fields=['cached_search', 'cnpj']),  # Para get_leads_from_cache otimizado        ]
Análise: o índice composto ['cached_search', 'cnpj'] é útil, mas falta índice para filtros com cnpj__isnull=False e exclude(cnpj='').
Recomendações:
# Adicionar índices parciais (PostgreSQL)indexes = [    models.Index(fields=['cnpj']),    models.Index(fields=['cached_search', 'cnpj']),    # Índice parcial para CNPJs válidos (reduz tamanho do índice)    models.Index(        fields=['cached_search', '-created_at'],        condition=Q(cnpj__isnull=False) & ~Q(cnpj=''),        name='lead_cached_search_cnpj_valid_idx'    ),]
2.3 ViperRequestQueue - busca em JSONField
Localização: models.py:222-227
Problema:
models.pyLines 222-227
        indexes = [            models.Index(fields=['status', 'priority', 'created_at']),  # Para buscar próximo item            models.Index(fields=['user', 'status']),  # Para buscar requisições do usuário            models.Index(fields=['user', 'request_type', 'status']),  # Para buscar duplicatas (otimiza find_existing_request)            # Nota: Índice funcional para request_data->>'cnpj' será criado via migration customizada        ]
Análise: a nota indica que um índice funcional para request_data->>'cnpj' será criado, mas não está implementado.
Recomendação:
# Migration customizada para criar índice GIN em JSONField# No PostgreSQL, usar índice GIN para buscas eficientes em JSONfrom django.contrib.postgres.indexes import GinIndexclass Meta:    indexes = [        # ... índices existentes ...        GinIndex(            fields=['request_data'],            name='viperrequestqueue_request_data_gin_idx',            opclasses=['jsonb_path_ops']  # Otimizado para operadores @>        ),    ]
2.4 CachedSearch - busca por nicho e localização
Localização: models.py:78-80
Problema:
models.pyLines 78-80
        indexes = [            models.Index(fields=['niche_normalized', 'location_normalized']),        ]
Análise: o índice existe, mas unique_together já cria um índice único. Verificar se está sendo usado corretamente.
Recomendação: manter o índice composto. Adicionar índice para last_updated se houver ordenações frequentes:
indexes = [    models.Index(fields=['niche_normalized', 'location_normalized']),    models.Index(fields=['-last_updated']),  # Para ordenação em listagens]
Resumo de índices recomendados
Modelo	Campo(s)	Tipo	Prioridade
LeadAccess	user, -accessed_at	Composto DESC	Alta
Lead	cached_search, -created_at (parcial CNPJ válido)	Composto parcial	Alta
ViperRequestQueue	request_data	GIN (JSONB)	Média
Lead	cnpj (parcial não-nulo)	Parcial	Média
CachedSearch	-last_updated	Simples	Baixa
3. Custo de Processamento - Campos JSON grandes
Análise de viper_data
3.1 Tamanho estimado do JSON
Cada viper_data pode conter:
Dados básicos da empresa: ~2-5 KB
Telefones: ~1-2 KB
Emails: ~0.5-1 KB
Sócios/QSA: ~5-20 KB (pode ter muitos sócios)
Endereços: ~1-2 KB
Total estimado: 10-30 KB por lead
3.2 Impacto em memória
Localização: múltiplas funções em services.py
Problema:
services.pyLines 995-998
            # Sanitizar dados (esconder QSA/telefones até enriquecer)            sanitized_viper_data = sanitize_lead_data(                {'viper_data': lead.viper_data or {}},                show_partners=(lead_access.enriched_at is not None)            ).get('viper_data', {})
Impacto:
100 leads = 1-3 MB em memória apenas para viper_data
Em loops, cada iteração carrega o JSON completo
sanitize_lead_data faz copy.deepcopy(), duplicando o uso de memória
3.3 Consultas que carregam viper_data desnecessariamente
get_leads_from_cache() - linha 1062-1065:
Carrega viper_data completo mesmo quando só precisa de campos básicos
get_existing_leads_from_db() - linha 926-929:
Mesmo problema
export_leads_csv() - linha 288:
Carrega todos os viper_data mesmo que só alguns campos sejam exportados
Recomendações
3.1 Lazy loading de viper_data
# Carregar apenas campos necessários inicialmenteleads = Lead.objects.filter(...).only(    'id', 'name', 'address', 'phone_maps', 'cnpj', 'cached_search_id')# Carregar viper_data apenas quando necessário (lazy)for lead in leads:    # Acessar lead.viper_data só quando precisar sanitizar    if need_full_data:        lead.refresh_from_db(fields=['viper_data'])
3.2 Otimizar sanitize_lead_data
def sanitize_lead_data(lead_data, show_partners=False, has_enriched_access=False):    # Em vez de deepcopy, fazer cópia seletiva apenas dos campos necessários    sanitized = {        'name': lead_data.get('name'),        'address': lead_data.get('address'),        'phone_maps': lead_data.get('phone_maps'),        'cnpj': lead_data.get('cnpj'),    }        if 'viper_data' in lead_data and lead_data['viper_data']:        viper_data = lead_data['viper_data']        sanitized_viper = {}                # Copiar apenas campos necessários (não fazer deepcopy completo)        if has_enriched_access:            sanitized_viper['telefones'] = viper_data.get('telefones')            sanitized_viper['emails'] = viper_data.get('emails')            sanitized_viper['socios_qsa'] = viper_data.get('socios_qsa')                sanitized['viper_data'] = sanitized_viper        return sanitized
3.3 Usar values() para exportação CSV
# Em export_leads_csv, usar values() para carregar apenas campos necessárioslead_accesses = LeadAccess.objects.filter(    user=user_profile).select_related('lead').values(    'lead__name', 'lead__cnpj', 'lead__phone_maps',     'lead__address', 'lead__viper_data'  # Ainda precisa, mas apenas uma vez)
3.4 Considerar separação de dados grandes
# Criar modelo separado para dados enriquecidos (opcional, refatoração maior)class LeadEnrichment(models.Model):    lead = models.OneToOneField(Lead, on_delete=models.CASCADE)    telefones = models.JSONField()    emails = models.JSONField()    socios_qsa = models.JSONField()    # Dados grandes separados do Lead principal
4. Estratégia de Cache Global - CachedSearch
Análise atual
4.1 Implementação do CachedSearch
Localização: models.py:63-83
models.pyLines 63-83
class CachedSearch(models.Model):    """    Cache global de pesquisas normalizadas para reutilização.    Dados nunca expiram - base histórica permanente.    """    niche_normalized = models.CharField(max_length=255)    location_normalized = models.CharField(max_length=255)  # Formato: "Cidade - UF"    total_leads_cached = models.IntegerField(default=0)    last_updated = models.DateTimeField(auto_now=True)    expires_at = models.DateTimeField(null=True, blank=True)  # DEPRECATED: Mantido para migração, não usado mais    created_at = models.DateTimeField(auto_now_add=True)    class Meta:        unique_together = [['niche_normalized', 'location_normalized']]        ordering = ['-last_updated']        indexes = [            models.Index(fields=['niche_normalized', 'location_normalized']),        ]
Pontos positivos:
Cache permanente (sem expiração)
Normalização de nicho e localização
Índice composto para buscas rápidas
4.2 Uso do cache
Localização: services.py:789-813
services.pyLines 789-813
def get_cached_search(niche_normalized, location_normalized):    """    Busca um CachedSearch existente.    Dados nunca expiram - base histórica permanente.        Args:        niche_normalized: Nicho normalizado        location_normalized: Localização normalizada (formato: "Cidade - UF")        Returns:        CachedSearch ou None: Cache existente ou None se não existe    """    if not niche_normalized or not location_normalized:        return None        try:        cached = CachedSearch.objects.filter(            niche_normalized=niche_normalized,            location_normalized=location_normalized        ).first()                return cached    except Exception as e:        logger.error(f"Erro ao buscar cache: {e}", exc_info=True)        return None
Problemas identificados:
Sem cache em memória (Redis/Memcached)
total_leads_cached pode ficar desatualizado
Contagem de leads é feita com values('cnpj').distinct().count() a cada uso
4.3 Atualização do cache
Localização: services.py:1015-1022
services.pyLines 1015-1022
            # Contar leads únicos por CNPJ usando values('cnpj').distinct()            total_leads = Lead.objects.filter(                cached_search=cached_search,                cnpj__isnull=False            ).exclude(cnpj='').values('cnpj').distinct().count()                        if cached_search.total_leads_cached != total_leads:                cached_search.total_leads_cached = total_leads                cached_search.save(update_fields=['total_leads_cached', 'last_updated'])
Problema: a contagem é executada toda vez que há atualização, o que pode ser custoso com muitos leads.
Recomendações
4.1 Adicionar cache em memória (Redis)
# Usar Django cache framework com Redisfrom django.core.cache import cachedef get_cached_search(niche_normalized, location_normalized):    cache_key = f"cached_search:{niche_normalized}:{location_normalized}"        # Tentar cache em memória primeiro    cached = cache.get(cache_key)    if cached:        return cached        # Se não está em cache, buscar no banco    cached = CachedSearch.objects.filter(        niche_normalized=niche_normalized,        location_normalized=location_normalized    ).first()        if cached:        # Cachear por 1 hora        cache.set(cache_key, cached, 3600)        return cached
4.2 Otimizar atualização de total_leads_cached
# Usar signal ou atualização assíncronafrom django.db.models.signals import post_save, post_deletefrom django.dispatch import receiver@receiver([post_save, post_delete], sender=Lead)def update_cached_search_count(sender, instance, **kwargs):    if instance.cached_search:        # Atualizar de forma assíncrona (usar Celery ou thread)        update_cached_search_count_async.delay(instance.cached_search.id)# Ou usar contagem incremental (mais eficiente)def increment_cached_search_count(cached_search):    CachedSearch.objects.filter(id=cached_search.id).update(        total_leads_cached=models.F('total_leads_cached') + 1,        last_updated=timezone.now()    )
4.3 Adicionar estatísticas de uso do cache
class CachedSearch(models.Model):    # ... campos existentes ...    hit_count = models.IntegerField(default=0)  # Quantas vezes foi usado    last_hit_at = models.DateTimeField(null=True, blank=True)        def increment_hit(self):        CachedSearch.objects.filter(id=self.id).update(            hit_count=models.F('hit_count') + 1,            last_hit_at=timezone.now()        )
4.4 Considerar particionamento para grandes volumes
# Se CachedSearch crescer muito, considerar particionamento por data# Ou usar tabela separada para estatísticasclass CachedSearchStats(models.Model):    cached_search = models.OneToOneField(CachedSearch, on_delete=models.CASCADE)    total_leads = models.IntegerField()    last_counted_at = models.DateTimeField()    # Atualizar via job periódico (não em tempo real)
Resumo executivo
Prioridades de otimização
Alta prioridade:
Implementar .defer('viper_data') em listagens de leads
Adicionar índices parciais para CNPJs válidos
Otimizar get_existing_leads_from_db para reduzir queries
Média prioridade:
Implementar índice GIN para ViperRequestQueue.request_data
Adicionar cache Redis para CachedSearch
Otimizar sanitize_lead_data para evitar deepcopy completo
Baixa prioridade:
Adicionar estatísticas de uso do cache
Considerar separação de dados grandes (refatoração maior)
Impacto esperado
Redução de tempo de resposta: 40-60% em listagens de leads
Redução de uso de memória: 50-70% em operações com muitos leads
Redução de carga no banco: 30-50% com índices otimizados
Melhoria em cache hits: 80-90% com Redis
Métricas recomendadas para monitoramento
Tempo médio de resposta de queries de leads
Uso de memória por requisição
Taxa de cache hit do CachedSearch
Número de queries N+1 detectadas (usar Django Debug Toolbar)
Tamanho médio de viper_data por lead
]

🤖 6. Instruções para o Desenvolvedor / IA (Cursor)

Ao realizar qualquer alteração neste repositório, siga as diretrizes abaixo:

Prioridade de Execução: Siga a ordem das Fases. Não inicie otimizações de performance (Fase 4) se houver riscos de segurança abertos (Fase 1).

Integridade Financeira: Qualquer alteração em credit_service.py deve garantir atomicidade via transaction.atomic() e proteção contra race conditions via select_for_update().

Princípio da Não-Quebra: Mantenha a compatibilidade das assinaturas das funções até que a refatoração completa da Fase 3 seja iniciada.

Verificação de Ownership: Toda e qualquer entrega de dados de Leads deve ser precedida por uma verificação na tabela LeadAccess vinculada ao user_profile da requisição.