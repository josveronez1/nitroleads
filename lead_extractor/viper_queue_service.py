"""
Service para gerenciar fila de requisições do Viper.
Garante que apenas uma requisição seja processada por vez.
"""
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from .models import ViperRequestQueue, UserProfile
import logging

logger = logging.getLogger(__name__)


def enqueue_viper_request(user_profile, request_type, request_data, priority=0, lead=None):
    """
    Adiciona uma requisição à fila do Viper.
    
    Args:
        user_profile: UserProfile do usuário
        request_type: Tipo de requisição ('partners', etc)
        request_data: Dados da requisição (dict, ex: {'cnpj': '12345678901234'})
        priority: Prioridade (maior = maior prioridade, default=0)
        lead: Lead opcional para associar à requisição
    
    Returns:
        ViperRequestQueue: Objeto da requisição enfileirada
    """
    queue_item = ViperRequestQueue.objects.create(
        user=user_profile,
        lead=lead,
        request_type=request_type,
        request_data=request_data,
        priority=priority,
        status='pending'
    )
    
    logger.info(f"Requisição {queue_item.id} adicionada à fila do Viper (tipo: {request_type}, usuário: {user_profile.email})")
    return queue_item


def get_queue_status(user_profile):
    """
    Retorna status da fila para o usuário.
    
    Args:
        user_profile: UserProfile do usuário
    
    Returns:
        dict: Status da fila (quantidade pendente, processando, etc)
    """
    pending_count = ViperRequestQueue.objects.filter(
        user=user_profile,
        status='pending'
    ).count()
    
    processing_count = ViperRequestQueue.objects.filter(
        user=user_profile,
        status='processing'
    ).count()
    
    return {
        'pending': pending_count,
        'processing': processing_count,
        'total_waiting': pending_count + processing_count
    }


def get_user_queue_count(user_profile):
    """
    Retorna quantidade de requisições pendentes do usuário.
    
    Args:
        user_profile: UserProfile do usuário
    
    Returns:
        int: Quantidade de requisições pendentes
    """
    return ViperRequestQueue.objects.filter(
        user=user_profile,
        status__in=['pending', 'processing']
    ).count()


def process_next_request():
    """
    Processa o próximo item da fila (com lock atômico).
    Retorna o objeto processado ou None se não houver itens.
    
    Returns:
        ViperRequestQueue: Item processado ou None
    """
    with transaction.atomic():
        # Buscar próximo item com lock (skip_locked=True para evitar deadlock)
        next_item = ViperRequestQueue.objects.select_for_update(
            skip_locked=True
        ).filter(
            status='pending'
        ).order_by(
            '-priority',  # Maior prioridade primeiro
            'created_at'  # Mais antigo primeiro dentro da mesma prioridade
        ).first()
        
        if not next_item:
            return None
        
        # Marcar como processando
        next_item.status = 'processing'
        next_item.started_at = timezone.now()
        next_item.save(update_fields=['status', 'started_at'])
        
        logger.info(f"Processando requisição {next_item.id} da fila (tipo: {next_item.request_type})")
        return next_item


def mark_request_completed(queue_item, result_data):
    """
    Marca uma requisição como completa e salva o resultado.
    
    Args:
        queue_item: ViperRequestQueue a marcar como completo
        result_data: Dados do resultado (dict)
    """
    queue_item.status = 'completed'
    queue_item.result_data = result_data
    queue_item.completed_at = timezone.now()
    queue_item.save(update_fields=['status', 'result_data', 'completed_at'])
    
    logger.info(f"Requisição {queue_item.id} marcada como completa")


def mark_request_failed(queue_item, error_message):
    """
    Marca uma requisição como falhada e salva a mensagem de erro.
    
    Args:
        queue_item: ViperRequestQueue a marcar como falhada
        error_message: Mensagem de erro (str)
    """
    queue_item.status = 'failed'
    queue_item.error_message = error_message
    queue_item.completed_at = timezone.now()
    queue_item.save(update_fields=['status', 'error_message', 'completed_at'])
    
    logger.error(f"Requisição {queue_item.id} falhou: {error_message}")

