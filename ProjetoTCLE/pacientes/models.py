from django.db import models
from django.conf import settings 

class Paciente(models.Model):
    nome = models.CharField('Nome Completo', max_length=255)
    cpf = models.CharField('CPF', max_length=14, unique=True)
    data_nascimento = models.DateField('Data de Nascimento')
    telefone = models.CharField('Telefone', max_length=20)
    rg = models.CharField('RG', max_length=20, blank=True, null=True)
    
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
    
# Modelo da Biblioteca de Templates
class TemplateTCLE(models.Model):
    CATEGORIAS = (
        ('CIRURGICO', 'Procedimentos Cirúrgicos'),
        ('ANESTESICO', 'Procedimentos Anestésicos'),
        ('EXAME', 'Exames Diagnósticos Invasivos'),
        ('HEMOTERAPIA', 'Hemoterapia'),
        ('ODONTO', 'Procedimentos Odontológicos'),
        ('ALTO_RISCO', 'Terapias de Alto Risco'),
    )
    
    titulo = models.CharField('Título do Template', max_length=200)
    categoria = models.CharField('Categoria', max_length=20, choices=CATEGORIAS)
    texto_base = models.TextField('Texto do Documento')
    ativo = models.BooleanField(default=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    
    def __str__(self):
        return self.titulo