"""
Comando Django para processar a fila de requisições do Viper.
Roda continuamente processando requisições uma por vez.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from lead_extractor.viper_queue_service import process_next_request, mark_request_completed, mark_request_failed
from lead_extractor.services import get_partners_internal
from lead_extractor.models import Lead
import time
import logging
import json

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Processa a fila de requisições do Viper (uma por vez)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--once',
            action='store_true',
            help='Processar apenas um item e sair (útil para cron)',
        )
        parser.add_argument(
            '--interval',
            type=int,
            default=5,
            help='Intervalo em segundos entre processamentos quando não há itens (default: 5)',
        )
        parser.add_argument(
            '--cleanup',
            action='store_true',
            help='Executar limpeza de requisições antigas e sair',
        )
        parser.add_argument(
            '--auto-cleanup',
            action='store_true',
            help='Executar limpeza automaticamente no início (antes de processar)',
        )

    def cleanup_old_requests(self):
        """
        Remove requisições antigas do banco de dados:
        - completed com mais de 7 dias
        - failed com mais de 30 dias
        """
        from .models import ViperRequestQueue
        from datetime import timedelta
        
        cutoff_completed = timezone.now() - timedelta(days=7)
        cutoff_failed = timezone.now() - timedelta(days=30)
        
        # Remover completed antigas
        deleted_completed = ViperRequestQueue.objects.filter(
            status='completed',
            completed_at__lt=cutoff_completed
        ).delete()[0]
        
        # Remover failed antigas
        deleted_failed = ViperRequestQueue.objects.filter(
            status='failed',
            completed_at__lt=cutoff_failed
        ).delete()[0]
        
        total_deleted = deleted_completed + deleted_failed
        
        if total_deleted > 0:
            self.stdout.write(self.style.SUCCESS(
                f'Limpeza concluída: {deleted_completed} completed e {deleted_failed} failed removidas'
            ))
            logger.info(f"Limpeza de requisições antigas: {deleted_completed} completed, {deleted_failed} failed")
        else:
            self.stdout.write('Nenhuma requisição antiga encontrada para remover')
        
        return total_deleted

    def handle(self, *args, **options):
        process_once = options['once']
        interval = options['interval']
        cleanup_only = options['cleanup']
        auto_cleanup = options['auto_cleanup']
        
        # Se --cleanup, executar limpeza e sair
        if cleanup_only:
            self.stdout.write(self.style.SUCCESS('Executando limpeza de requisições antigas...'))
            self.cleanup_old_requests()
            return
        
        self.stdout.write(self.style.SUCCESS('Iniciando processador de fila do Viper...'))
        
        # Se --auto-cleanup, executar limpeza no início
        if auto_cleanup:
            self.stdout.write('Executando limpeza automática...')
            self.cleanup_old_requests()
        
        while True:
            try:
                # Buscar próximo item da fila (com lock)
                queue_item = process_next_request()
                
                if queue_item:
                    self.stdout.write(f'Processando requisição {queue_item.id} (tipo: {queue_item.request_type})...')
                    
                    try:
                        # Processar baseado no tipo de requisição
                        if queue_item.request_type == 'partners':
                            cnpj = queue_item.request_data.get('cnpj')
                            if not cnpj:
                                raise ValueError('CNPJ não encontrado nos dados da requisição')
                            
                            # Chamar função original (sem retry aqui, pois já está na fila)
                            result = get_partners_internal(cnpj, retry=True)
                            
                            if result is not None:
                                # Normalizar estrutura de dados: garantir formato {'socios': [...]}
                                # A API pode retornar lista diretamente ou dict com 'socios'
                                if isinstance(result, list):
                                    normalized_result = {'socios': result}
                                elif isinstance(result, dict) and 'socios' in result:
                                    normalized_result = result
                                elif isinstance(result, dict):
                                    # Se é dict mas não tem 'socios', assumir que os dados estão no nível raiz
                                    normalized_result = {'socios': [result]} if result else {'socios': []}
                                else:
                                    # Formato desconhecido, criar estrutura padrão
                                    normalized_result = {'socios': []}
                                    logger.warning(f"Formato de resultado inesperado para CNPJ {cnpj}: {type(result)}")
                                
                                # Salvar QSA no Lead.viper_data se lead estiver associado
                                if queue_item.lead:
                                    lead = queue_item.lead
                                    # Garantir que viper_data é um dict
                                    if not lead.viper_data:
                                        lead.viper_data = {}
                                    
                                    # Salvar resultado normalizado em socios_qsa
                                    lead.viper_data['socios_qsa'] = normalized_result
                                    lead.save(update_fields=['viper_data'])
                                    logger.info(f"QSA salvo no Lead {lead.id} para CNPJ {cnpj}")
                                else:
                                    # Se não tiver lead associado, tentar encontrar pelo CNPJ
                                    lead = Lead.objects.filter(cnpj=cnpj, user=queue_item.user).first()
                                    if lead:
                                        if not lead.viper_data:
                                            lead.viper_data = {}
                                        lead.viper_data['socios_qsa'] = normalized_result
                                        lead.save(update_fields=['viper_data'])
                                        logger.info(f"QSA salvo no Lead {lead.id} para CNPJ {cnpj} (encontrado pelo CNPJ)")
                                
                                # Salvar resultado normalizado também no queue_item
                                mark_request_completed(queue_item, normalized_result)
                                self.stdout.write(self.style.SUCCESS(f'✓ Requisição {queue_item.id} processada com sucesso'))
                            else:
                                raise Exception('Resultado vazio da API')
                        else:
                            raise ValueError(f'Tipo de requisição não suportado: {queue_item.request_type}')
                        
                    except Exception as e:
                        error_msg = str(e)
                        mark_request_failed(queue_item, error_msg)
                        self.stdout.write(self.style.ERROR(f'✗ Requisição {queue_item.id} falhou: {error_msg}'))
                        logger.error(f"Erro ao processar requisição {queue_item.id}: {error_msg}", exc_info=True)
                
                else:
                    # Não há itens na fila
                    if process_once:
                        # Se --once, sair
                        self.stdout.write('Nenhum item na fila. Saindo.')
                        break
                    else:
                        # Aguardar antes de tentar novamente
                        time.sleep(interval)
                        continue
                
                # Se processou um item e está em modo --once, sair
                if process_once:
                    break
                    
                # Pequeno delay entre processamentos para não sobrecarregar
                time.sleep(1)
                
            except KeyboardInterrupt:
                self.stdout.write(self.style.WARNING('\nInterrompido pelo usuário. Saindo...'))
                break
            except Exception as e:
                logger.error(f"Erro no processador de fila: {e}", exc_info=True)
                self.stdout.write(self.style.ERROR(f'Erro: {e}'))
                # Aguardar antes de tentar novamente
                time.sleep(interval)

