from django.db import models
from django.contrib.auth.models import AbstractUser

class Instituicao(models.Model):
    """
    Entidade central do sistema (Multi-Tenant).
    """
    nome = models.CharField('Nome da Instituição', max_length=255)
    cnpj = models.CharField('CNPJ', max_length=18, unique=True, blank=True, null=True)
    telefone = models.CharField('Telefone', max_length=20, blank=True, null=True)
    ativo = models.BooleanField('Instituição Ativa', default=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.nome

    class Meta:
        verbose_name = 'Instituição'
        verbose_name_plural = 'Instituições'

class Usuario(AbstractUser):
    PERFIL_CHOICES = [
        ('ADM', 'Administrador Geral'),
        ('COORDENADOR', 'Coordenador da Instituição'),
        ('PADRAO', 'Usuário Padrão (Profissional de Saúde)'),
    ]
    
    perfil = models.CharField('Nível de Acesso', max_length=20, choices=PERFIL_CHOICES, default='PADRAO')
    profissao = models.CharField('Profissão', max_length=100, blank=True, null=True)
    primeiro_acesso = models.BooleanField('Primeiro Acesso', default=True) # Trava de segurança
    
    instituicao = models.ForeignKey(
        Instituicao, 
        on_delete=models.CASCADE, 
        related_name='funcionarios',
        blank=True, 
        null=True,
        help_text='Deixar em branco apenas se o perfil for Administrador Geral (ADM).'
    )

    def __str__(self):
        return f"{self.username} - {self.get_perfil_display()}"