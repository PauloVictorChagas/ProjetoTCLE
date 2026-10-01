from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class EmailBackend(ModelBackend):
    """
    Autentica pelo E-mail (sem diferenciar maiúsculas de minúsculas).

    Se mais de um cadastro tiver o mesmo e-mail (o e-mail não é único no modelo
    padrão do Django), só autentica quando EXATAMENTE UM deles confere com a
    senha informada; nunca "escolhe o primeiro".
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        UserModel = get_user_model()
        if username is None:
            username = kwargs.get(UserModel.USERNAME_FIELD)
        if not username or password is None:
            return None

        candidatos = list(UserModel.objects.filter(email__iexact=username.strip())[:5])
        if not candidatos:
            # Gasta o mesmo tempo de um hash real, para não revelar (por tempo de
            # resposta) quais e-mails existem.
            UserModel().set_password(password)
            return None

        aprovados = [u for u in candidatos
                     if u.check_password(password) and self.user_can_authenticate(u)]
        return aprovados[0] if len(aprovados) == 1 else None
