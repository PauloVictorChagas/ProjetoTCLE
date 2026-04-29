# usuarios/models.py

from django.contrib.auth.models import AbstractUser
from django.db import models

class Usuario(AbstractUser):
    # Definimos as opções disponíveis para o perfil
    OPCOES_DE_PERFIL = (
        ('ADMIN', 'Administrador'),
        ('PADRAO', 'Usuário Padrão'),
    )
    
    # Campo para definir se é Admin ou Padrão
    perfil = models.CharField(
        max_length=10, 
        choices=OPCOES_DE_PERFIL, 
        default='PADRAO'
    )
    
    # Campo de texto livre para a profissão (como você pediu)
    profissao = models.CharField(
        max_length=100, 
        blank=True, # Permite que o campo fique em branco no formulário
        null=True   # Permite que o campo fique vazio no banco de dados
    )

    def __str__(self):
        return self.username