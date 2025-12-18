"""
Comando Django para processar a fila de requisições do Viper.
Roda continuamente processando requisições uma por vez.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from lead_extractor.viper_queue_service import process_next_request, mark_request_completed, mark_request_failed
from lead_extractor.services import get_partners_internal
import time
import logging

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

    def handle(self, *args, **options):
        process_once = options['once']
        interval = options['interval']
        
        self.stdout.write(self.style.SUCCESS('Iniciando processador de fila do Viper...'))
        
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
                            result = get_partners_internal(cnpj, retry=False)
                            
                            if result is not None:
                                mark_request_completed(queue_item, result)
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

