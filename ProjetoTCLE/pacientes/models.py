from django.db import models
from django.conf import settings
from usuarios.models import Instituicao  

class Paciente(models.Model):
    instituicao = models.ForeignKey(Instituicao, on_delete=models.CASCADE, related_name='pacientes')
    nome = models.CharField('Nome Completo', max_length=255)
    cpf = models.CharField('CPF', max_length=14)
    rg = models.CharField('RG', max_length=20)
    data_nascimento = models.DateField('Data de Nascimento')
    telefone = models.CharField('Telefone', max_length=20)
    email = models.EmailField('E-mail', blank=True, null=True)
    
    cep = models.CharField('CEP', max_length=9)
    tipo_logradouro = models.CharField('Tipo de Logradouro', max_length=20)
    logradouro = models.CharField('Logradouro', max_length=255)
    numero = models.CharField('Número', max_length=20)
    complemento = models.CharField('Complemento', max_length=100, blank=True, null=True)
    bairro = models.CharField('Bairro', max_length=100)
    cidade = models.CharField('Cidade', max_length=100)
    uf = models.CharField('UF', max_length=2)
    
    criado_em = models.DateTimeField(auto_now_add=True)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)

    def __str__(self):
        return f"{self.nome} ({self.cpf})"

    class Meta:
        unique_together = ('instituicao', 'cpf')

class CategoriaTemplate(models.Model):
    instituicao = models.ForeignKey(Instituicao, on_delete=models.CASCADE, related_name='categorias')
    nome = models.CharField('Nome da Categoria', max_length=100)
    descricao = models.TextField('Descrição / Notas de Orientação', blank=True, null=True)
    texto_padrao = models.TextField(
        'Texto Padrão da Categoria',
        blank=True,
        default='',
        help_text=(
            'Texto fixo obrigatório da categoria. Pode conter variáveis (@profissional, '
            '@paciente, @responsavel, @data) e campos personalizados no formato {Nome do Campo}.'
        ),
    )
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return f"{self.nome} - {self.instituicao.nome}"

    class Meta:
        unique_together = ('instituicao', 'nome')

class TemplateTCLE(models.Model):
    instituicao = models.ForeignKey(Instituicao, on_delete=models.CASCADE, related_name='templates')
    categoria = models.ForeignKey(CategoriaTemplate, on_delete=models.PROTECT, related_name='templates')
    titulo = models.CharField('Título do Template', max_length=255)
    texto_base = models.TextField('Texto Base do Termo')
    configuracao_campos = models.JSONField('Configuração dos Campos Dinâmicos', default=dict, blank=True)
    ativo = models.BooleanField('Disponível para os Médicos', default=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)

    def __str__(self):
        return self.titulo

class DocumentoEmitido(models.Model):
    STATUS_CHOICES = [
        ('PENDENTE', 'Aguardando Assinatura'),
        ('ASSINADO', 'Concluído e Selado'),
        ('CANCELADO', 'Cancelado'),
    ]

    instituicao = models.ForeignKey(Instituicao, on_delete=models.CASCADE)
    paciente = models.ForeignKey(Paciente, on_delete=models.PROTECT)
    template_origem = models.ForeignKey(TemplateTCLE, on_delete=models.SET_NULL, null=True)
    medico_emissor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    
    dados_preenchidos = models.JSONField('Dados Colectados')
    responsavel_nome = models.CharField('Nome do Responsável', max_length=255, blank=True, null=True)
    responsavel_cpf = models.CharField('CPF do Responsável', max_length=14, blank=True, null=True)
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDENTE')
    arquivo_pdf = models.FileField(upload_to='termos_selados/%Y/%m/%d/', blank=True, null=True)
    data_emissao = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"TCLE #{self.id} - {self.paciente.nome}"