from django.contrib.admin.forms import AdminAuthenticationForm
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError

from . import throttle

MSG_LOGIN_INVALIDO = 'E-mail ou senha incorretos. Tente novamente.'
MSG_BLOQUEIO = 'Muitas tentativas de acesso. Aguarde alguns minutos e tente novamente.'


class LimiteDeTentativasMixin:
    """Bloqueia temporariamente o login após muitas falhas (força bruta)."""

    def clean(self):
        usuario = self.cleaned_data.get('username')
        if usuario and throttle.bloqueado('login', self.request, usuario):
            raise ValidationError(MSG_BLOQUEIO, code='bloqueado')
        try:
            dados = super().clean()
        except ValidationError:
            if usuario:
                throttle.registrar_falha('login', self.request, usuario)
            raise
        if usuario:
            throttle.limpar('login', self.request, usuario)
        return dados


class FormularioLogin(LimiteDeTentativasMixin, AuthenticationForm):
    # Mensagem única: não revela se o e-mail existe ou se a conta está inativa.
    error_messages = {
        'invalid_login': MSG_LOGIN_INVALIDO,
        'inactive': MSG_LOGIN_INVALIDO,
    }


class FormularioLoginAdmin(LimiteDeTentativasMixin, AdminAuthenticationForm):
    pass
