from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.utils.cache import add_never_cache_headers

from .utils import senha_pendente


class TrocaSenhaObrigatoriaMiddleware:
    """
    Enquanto a senha inicial não for trocada, o usuário só alcança a tela de
    troca de senha (e o logout). Qualquer outra URL — mesmo digitada na barra
    de endereço ou enviada por POST direto — é redirecionada para lá.
    """

    URLS_LIBERADAS = {'trocar_senha', 'logout', 'login'}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        if not senha_pendente(request.user):
            return None

        match = request.resolver_match
        if match and not match.namespace and match.url_name in self.URLS_LIBERADAS:
            return None

        messages.warning(request, 'Por segurança, você precisa alterar sua senha provisória antes de continuar.')
        return redirect('trocar_senha')


class AcessoSeguroMiddleware:
    """
    1. Desativar uma Unidade (Instituicao.ativo = False) passa a bloquear os
       usuários dela imediatamente, inclusive com sessão já aberta.
    2. Respostas para usuários autenticados nunca são guardadas em cache do
       navegador/proxies (contêm dados de pacientes): o botão "voltar" após o
       logout não reexibe as páginas.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if (
            user.is_authenticated
            and not user.is_superuser
            and user.perfil != 'ADM'
            and user.instituicao_id
            and not user.instituicao.ativo
        ):
            logout(request)
            messages.error(request, 'A unidade de saúde vinculada ao seu usuário está inativa. Procure o administrador.')
            response = redirect('login')
        else:
            response = self.get_response(request)

        if request.user.is_authenticated or response.status_code in (301, 302):
            add_never_cache_headers(response)
        return response
