from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models

class UsuarioManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('O usuário deve ter um endereço de e-mail')
        
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('perfil', 'ADMIN')

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser precisa ter is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser precisa ter is_superuser=True.')

        return self.create_user(email, password, **extra_fields)


class Usuario(AbstractUser):
    username = None 
    email = models.EmailField('Endereço de E-mail', unique=True)
    
    nome = models.CharField('Nome Completo', max_length=255)
    
    OPCOES_DE_PERFIL = (
        ('ADMIN', 'Administrador'),
        ('PADRAO', 'Usuário Padrão'),
    )
    
    perfil = models.CharField(max_length=10, choices=OPCOES_DE_PERFIL, default='PADRAO')
    profissao = models.CharField(max_length=100, blank=True, null=True)

    USERNAME_FIELD = 'email'
    
    REQUIRED_FIELDS = ['nome'] 

    objects = UsuarioManager()

    def __str__(self):
        return self.nome