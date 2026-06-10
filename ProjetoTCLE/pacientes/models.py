from django.db import models
from django.conf import settings 

class Paciente(models.Model):
    nome = models.CharField('Nome Completo', max_length=255)
    cpf = models.CharField('CPF', max_length=14, unique=True)
    data_nascimento = models.DateField('Data de Nascimento')
    telefone = models.CharField('Telefone', max_length=20)
    rg = models.CharField('RG', max_length=20, blank=True, null=True)
    email = models.EmailField('E-mail', blank=True, null=True)

    # Campos de Endereço
    cep = models.CharField('CEP', max_length=9, blank=True, null=True)
    tipo_logradouro = models.CharField('Tipo de Logradouro', max_length=20, blank=True, null=True)
    logradouro = models.CharField('Logradouro', max_length=255, blank=True, null=True)
    numero = models.CharField('Número', max_length=20, blank=True, null=True)
    complemento = models.CharField('Complemento', max_length=100, blank=True, null=True)
    bairro = models.CharField('Bairro', max_length=100, blank=True, null=True)
    cidade = models.CharField('Cidade', max_length=100, blank=True, null=True)
    uf = models.CharField('UF', max_length=2, blank=True, null=True)
    
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