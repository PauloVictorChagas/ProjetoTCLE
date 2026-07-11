from .utils import eh_admin_geral, get_instituicao_contexto


def unidade_ativa_processor(request):
    """
    Disponibiliza em TODOS os templates:
      - eh_admin_geral: True se o usuário logado é o Administrador Geral.
      - unidade_ativa: a Instituicao que o Administrador está gerenciando
        no momento (None se ele ainda estiver na tela "Unidades de Saúde").
    """
    if not request.user.is_authenticated:
        return {}

    is_admin = eh_admin_geral(request.user)
    unidade_ativa = get_instituicao_contexto(request) if is_admin else None

    return {
        'eh_admin_geral': is_admin,
        'unidade_ativa': unidade_ativa,
    }
