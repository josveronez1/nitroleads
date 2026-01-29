from django.db import transaction
from django.db.models import F
from .models import UserProfile, CreditTransaction
import logging

logger = logging.getLogger(__name__)


def debit_credits(user_id, amount, description=None):
    """
    Debita créditos do usuário de forma atômica.
    
    Args:
        user_id: ID do UserProfile ou objeto UserProfile
        amount: Quantidade de créditos a debitar (positivo)
        description: Descrição opcional da transação
    
    Returns:
        tuple: (success: bool, new_balance: int, error_message: str)
    """
    try:
        with transaction.atomic():
            # Se user_id é um objeto, usar diretamente, senão buscar
            if isinstance(user_id, UserProfile):
                user_profile = user_id
                # Buscar novamente com lock para garantir consistência
                user_profile = UserProfile.objects.select_for_update().get(id=user_profile.id)
            else:
                user_profile = UserProfile.objects.select_for_update().get(id=user_id)
            
            # Verificar e debitar créditos atomicamente usando F() expression
            # Isso previne race conditions: a verificação e o débito acontecem em uma única operação SQL
            updated_count = UserProfile.objects.filter(
                id=user_profile.id,
                credits__gte=amount  # Verificação condicional no banco
            ).update(credits=F('credits') - amount)
            
            if updated_count == 0:
                # Atualizar objeto para obter saldo atual
                user_profile.refresh_from_db()
                return False, user_profile.credits, f"Créditos insuficientes. Disponível: {user_profile.credits}, Necessário: {amount}"
            
            # Atualizar o objeto para obter o valor atualizado
            user_profile.refresh_from_db()
            
            # Criar transação de uso
            CreditTransaction.objects.create(
                user=user_profile,
                transaction_type='usage',
                amount=-amount,  # Negativo para débito
                description=description or f"Uso de {amount} crédito(s)"
            )
            
            logger.info(f"Créditos debitados: {amount} do usuário {user_profile.email}. Novo saldo: {user_profile.credits}")
            
            return True, user_profile.credits, None
            
    except UserProfile.DoesNotExist:
        return False, 0, f"Usuário não encontrado: {user_id}"
    except Exception as e:
        logger.error(f"Erro ao debitar créditos: {e}")
        return False, 0, str(e)


def add_credits(user_id, amount, description=None, kiwify_sale_id=None, payment_gateway='kiwify'):
    """
    Adiciona créditos ao usuário de forma atômica.
    
    Args:
        user_id: ID do UserProfile ou objeto UserProfile
        amount: Quantidade de créditos a adicionar (positivo)
        description: Descrição opcional da transação
        kiwify_sale_id: ID da venda na Kiwify (order_id do webhook)
        payment_gateway: 'kiwify' ou 'stripe' (apenas para histórico; novas transações usam 'kiwify')
    
    Returns:
        tuple: (success: bool, new_balance: int, error_message: str)
    """
    try:
        with transaction.atomic():
            # Se user_id é um objeto, usar diretamente, senão buscar
            if isinstance(user_id, UserProfile):
                user_profile = user_id
            else:
                user_profile = UserProfile.objects.select_for_update().get(id=user_id)
            
            # Adicionar créditos
            user_profile.credits = F('credits') + amount
            user_profile.save(update_fields=['credits'])
            
            # Atualizar o objeto para obter o valor atualizado
            user_profile.refresh_from_db()
            
            # Criar transação de compra
            CreditTransaction.objects.create(
                user=user_profile,
                transaction_type='purchase',
                amount=amount,
                kiwify_sale_id=kiwify_sale_id,
                payment_gateway=payment_gateway,
                description=description or f"Compra de {amount} crédito(s)"
            )
            
            logger.info(f"Créditos adicionados: {amount} ao usuário {user_profile.email}. Novo saldo: {user_profile.credits}")
            
            return True, user_profile.credits, None
            
    except UserProfile.DoesNotExist:
        return False, 0, f"Usuário não encontrado: {user_id}"
    except Exception as e:
        logger.error(f"Erro ao adicionar créditos: {e}")
        return False, 0, str(e)


def check_credits(user_id):
    """
    Verifica o saldo de créditos do usuário.
    
    Args:
        user_id: ID do UserProfile ou objeto UserProfile
    
    Returns:
        int: Saldo de créditos
    """
    try:
        if isinstance(user_id, UserProfile):
            return user_id.credits
        
        user_profile = UserProfile.objects.get(id=user_id)
        return user_profile.credits
    except UserProfile.DoesNotExist:
        return 0

