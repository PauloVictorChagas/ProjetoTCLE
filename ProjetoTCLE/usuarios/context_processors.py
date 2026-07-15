from .utils import eh_admin_geral, get_instituicao_contexto


def unidade_ativa_processor(request):
    
    if not request.user.is_authenticated:
        return {}

    is_admin = eh_admin_geral(request.user)
    unidade_ativa = get_instituicao_contexto(request) if is_admin else None

    return {
        'eh_admin_geral': is_admin,
        'unidade_ativa': unidade_ativa,
    }
