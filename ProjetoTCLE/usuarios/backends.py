from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model

class EmailBackend(ModelBackend):
    """
    Ensina o Django a autenticar usuários pelo E-mail de forma segura,
    evitando erros caso existam e-mails duplicados no banco.
    """
    def authenticate(self, request, username=None, password=None, **kwargs):
        UserModel = get_user_model()
        
        # Ele pega todos os usuários com esse e-mail e escolhe o primeiro da lista.
        user = UserModel.objects.filter(email=username).first()
        
        # Se não achou nenhum usuário com esse e-mail, retorna vazio (login falha)
        if not user:
            return None
        
        # Se achou, testa a senha
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
            
        return None