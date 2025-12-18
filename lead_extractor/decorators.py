"""
Decoradores para validação de segurança e autenticação.
"""
from functools import wraps
from django.http import JsonResponse, HttpResponseForbidden
from django.shortcuts import redirect
import logging

logger = logging.getLogger(__name__)


def require_user_profile(view_func):
    """
    Decorator que garante que a view tenha um user_profile válido.
    Redireciona para login se não estiver autenticado.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        user_profile = getattr(request, 'user_profile', None)
        
        if not user_profile:
            # Se for requisição AJAX, retornar JSON
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'error': 'Não autenticado',
                    'redirect': '/login/'
                }, status=401)
            # Caso contrário, redirecionar para login
            return redirect('login')
        
        return view_func(request, *args, **kwargs)
    
    return _wrapped_view


def validate_user_ownership(model_class, lookup_field='user', user_attr='user_profile'):
    """
    Decorator factory que valida que o objeto pertence ao usuário.
    
    Args:
        model_class: Classe do modelo Django a verificar
        lookup_field: Campo do modelo que referencia o UserProfile (default: 'user')
        user_attr: Atributo da request que contém o UserProfile (default: 'user_profile')
    
    Usage:
        @validate_user_ownership(Search, lookup_field='user')
        def my_view(request, search_id):
            search = Search.objects.get(id=search_id)
            ...
    """
    def decorator(view_func):
        @wraps(view_func)
        @require_user_profile
        def _wrapped_view(request, *args, **kwargs):
            user_profile = getattr(request, user_attr)
            
            # Procurar por um ID nos kwargs ou args
            obj_id = None
            for key in ['id', 'search_id', 'lead_id', 'queue_id']:
                if key in kwargs:
                    obj_id = kwargs[key]
                    break
            
            if obj_id:
                try:
                    # Buscar objeto
                    obj = model_class.objects.get(id=obj_id)
                    
                    # Verificar ownership
                    obj_user = getattr(obj, lookup_field)
                    if obj_user != user_profile:
                        logger.warning(
                            f"Tentativa de acesso não autorizado: usuário {user_profile.email} "
                            f"tentou acessar {model_class.__name__} {obj_id} de {obj_user.email}"
                        )
                        
                        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                            return JsonResponse({
                                'error': 'Acesso negado. Este recurso não pertence a você.'
                            }, status=403)
                        
                        return HttpResponseForbidden('Acesso negado. Este recurso não pertence a você.')
                    
                    # Adicionar objeto aos kwargs para uso na view
                    kwargs[f'{model_class.__name__.lower()}_obj'] = obj
                    
                except model_class.DoesNotExist:
                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                        return JsonResponse({
                            'error': 'Recurso não encontrado'
                        }, status=404)
                    return HttpResponseForbidden('Recurso não encontrado')
            
            return view_func(request, *args, **kwargs)
        
        return _wrapped_view
    return decorator

