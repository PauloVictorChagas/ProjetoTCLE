from django.contrib import messages
from django.shortcuts import redirect

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
