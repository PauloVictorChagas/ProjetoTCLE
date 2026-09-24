from .models import Instituicao


def eh_admin_geral(user):
    """Retorna True se o usuário é o Administrador Geral (ou superuser)."""
    return user.is_authenticated and (user.perfil == 'ADM' or user.is_superuser)


def get_instituicao_contexto(request):

    user = request.user

    if eh_admin_geral(user):
        inst_id = request.session.get('instituicao_ativa_id')
        if not inst_id:
            return None
        return Instituicao.objects.filter(id=inst_id).first()

    return user.instituicao


def senha_pendente(user):
    """
    True se o usuário ainda está com a senha inicial (provisória) e precisa trocá-la.
    O superusuário criado pelo `createsuperuser` fica de fora: ele não recebe
    senha provisória de ninguém.
    """
    return bool(user.is_authenticated and user.primeiro_acesso and not user.is_superuser)
