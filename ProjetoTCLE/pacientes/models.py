from django.db import models
from django.conf import settings 

class Paciente(models.Model):
    nome = models.CharField('Nome Completo', max_length=255)
    cpf = models.CharField('CPF', max_length=14, unique=True)
    data_nascimento = models.DateField('Data de Nascimento')
    telefone = models.CharField('Telefone', max_length=20)
    
    # Campos opcionais
    email = models.EmailField('E-mail', blank=True, null=True)
    endereco = models.CharField('Endereço', max_length=255, blank=True, null=True)
    
    # Rastreabilidade (Quem criou e quando)
    criado_em = models.DateTimeField(auto_now_add=True)
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True
    )

    def __str__(self):
        return f"{self.nome} ({self.cpf})"