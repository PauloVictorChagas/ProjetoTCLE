import base64
import binascii
import datetime
import logging
import re
import unicodedata

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.mail import EmailMessage
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.html import escape
from django.utils.safestring import mark_safe

from usuarios.utils import eh_admin_geral, get_instituicao_contexto
from usuarios.validators import (
    UFS, cep_valido, cpf_valido, formatar_cep, formatar_cpf, limpar_texto, somente_digitos,
)

from .models import CategoriaTemplate, DocumentoEmitido, Paciente, TemplateTCLE

logger = logging.getLogger(__name__)
auditoria = logging.getLogger('tcle.auditoria')


TOKEN_ASSINATURA_PACIENTE = re.compile(r'\[assinatura_paciente\]', re.IGNORECASE)
TOKEN_ASSINATURA_PROFISSIONAL = re.compile(r'\[assinatura_profissional\]', re.IGNORECASE)

# Limites de entrada
TEXTO_MAX = 100_000            # caracteres do texto de um TCLE/categoria
ASSINATURA_MAX = 1_000_000     # caracteres (data URL) por assinatura
ASSINATURA_RE = re.compile(r'^data:image/(png|jpeg);base64,([A-Za-z0-9+/]+={0,2})$')
ASSINATURA_MAGIC = {'png': b'\x89PNG\r\n\x1a\n', 'jpeg': b'\xff\xd8\xff'}


def _id_ou_404(valor):
    """Converte um ID vindo do cliente em int; qualquer coisa estranha vira 404 (não 500)."""
    try:
        numero = int(str(valor).strip())
    except (TypeError, ValueError):
        raise Http404('Identificador inválido.')
    if not 0 < numero < 2 ** 31:
        raise Http404('Identificador inválido.')
    return numero


def assinatura_valida(valor):
    """
    Aceita SOMENTE uma imagem PNG/JPEG em data URL (é o que o canvas gera).
    Isso impede que o campo carregue HTML/atributos (XSS) ou URLs (file://,
    http://...) que o gerador de PDF buscaria no servidor (SSRF/leitura de arquivos).
    """
    if not valor or len(valor) > ASSINATURA_MAX:
        return False
    m = ASSINATURA_RE.match(valor)
    if not m:
        return False
    try:
        conteudo = base64.b64decode(m.group(2), validate=True)
    except (binascii.Error, ValueError):
        return False
    return conteudo.startswith(ASSINATURA_MAGIC[m.group(1)])


def renderizar_corpo_documento(documento):
    """
    Escapa o texto final do TCLE e substitui os marcadores de assinatura
    ([assinatura_paciente] / [assinatura_profissional]) pelas imagens
    capturadas, exatamente no ponto do texto em que foram inseridos na
    categoria. Se o template não tiver marcadores, as assinaturas
    disponíveis são anexadas ao final do documento.

    A assinatura só vira <img> se for uma imagem data URL válida; qualquer
    outro conteúdo (inclusive registros antigos adulterados) é ignorado.
    """
    texto_escapado = escape(documento.texto_final or '')

    ass_paciente = documento.assinatura_paciente if assinatura_valida(documento.assinatura_paciente) else None
    ass_profissional = documento.assinatura_profissional if assinatura_valida(documento.assinatura_profissional) else None

    img_paciente = (
        f'<img src="{ass_paciente}" class="assinatura-img">'
        if ass_paciente else
        '<span class="assinatura-pendente">(assinatura do paciente/responsável)</span>'
    )
    img_profissional = (
        f'<img src="{ass_profissional}" class="assinatura-img">'
        if ass_profissional else
        '<span class="assinatura-pendente">(assinatura do profissional)</span>'
    )

    tinha_token_paciente = bool(TOKEN_ASSINATURA_PACIENTE.search(texto_escapado))
    tinha_token_profissional = bool(TOKEN_ASSINATURA_PROFISSIONAL.search(texto_escapado))

    # Função (e não string) no sub(): a imagem nunca é interpretada como escapes de regex
    html = TOKEN_ASSINATURA_PACIENTE.sub(lambda _m: img_paciente, texto_escapado)
    html = TOKEN_ASSINATURA_PROFISSIONAL.sub(lambda _m: img_profissional, html)
    html = html.replace('\n', '<br>')

    extra = ''
    if not tinha_token_paciente and ass_paciente:
        extra += (
            '<div class="assinatura-bloco"><p class="assinatura-legenda">'
            f'Assinatura do Paciente/Responsável</p>{img_paciente}</div>'
        )
    if not tinha_token_profissional and ass_profissional:
        extra += (
            '<div class="assinatura-bloco"><p class="assinatura-legenda">'
            f'Assinatura do Profissional</p>{img_profissional}</div>'
        )

    return mark_safe(html + extra)


def pode_gerenciar_categorias(user):
    """Administrador Geral e Coordenador podem criar/editar categorias de TCLE."""
    return eh_admin_geral(user) or user.perfil == 'COORDENADOR'

def _texto_longo(valor):
    """Texto de várias linhas: remove NUL/controles (menos \n e \t) e espaços nas pontas."""
    valor = (valor or '').replace('\r\n', '\n').replace('\r', '\n')
    valor = ''.join(c for c in valor if c in '\n\t' or not unicodedata.category(c).startswith('C'))
    return valor.strip()


def _validar_paciente(post, instituicao, paciente_existente=None):
    """Valida e normaliza os dados do formulário de paciente. Devolve (dados, erros)."""
    erros = []
    g = lambda campo: limpar_texto(post.get(campo))

    def obrigatorio(campo, rotulo, maximo):
        valor = g(campo)
        if not valor:
            erros.append(f'Informe {rotulo}.')
        elif len(valor) > maximo:
            erros.append(f'{rotulo[0].upper()}{rotulo[1:]} deve ter no máximo {maximo} caracteres.')
        return valor

    dados = {}
    dados['nome'] = obrigatorio('nome', 'o nome completo', 255)
    dados['rg'] = obrigatorio('rg', 'o RG', 20)
    dados['tipo_logradouro'] = obrigatorio('tipo_logradouro', 'o tipo de logradouro', 20)
    dados['logradouro'] = obrigatorio('logradouro', 'o logradouro', 255)
    dados['numero'] = obrigatorio('numero', 'o número', 20)
    dados['bairro'] = obrigatorio('bairro', 'o bairro', 100)
    dados['cidade'] = obrigatorio('cidade', 'a cidade', 100)

    complemento = g('complemento')
    if len(complemento) > 100:
        erros.append('O complemento deve ter no máximo 100 caracteres.')
    dados['complemento'] = complemento or None

    # CPF (11 dígitos válidos). Um CPF já gravado e NÃO alterado é aceito como está,
    # para não impedir a edição de cadastros antigos.
    cpf_digitos = somente_digitos(post.get('cpf'))
    inalterado = paciente_existente is not None and cpf_digitos == somente_digitos(paciente_existente.cpf)
    if not inalterado and not cpf_valido(cpf_digitos):
        erros.append('CPF inválido.')
    dados['cpf'] = formatar_cpf(cpf_digitos) if len(cpf_digitos) == 11 else g('cpf')
    if len(cpf_digitos) == 11:
        duplicados = Paciente.objects.filter(
            instituicao=instituicao, cpf__in=[dados['cpf'], cpf_digitos])
        if paciente_existente:
            duplicados = duplicados.exclude(pk=paciente_existente.pk)
        if duplicados.exists():
            erros.append('Já existe um paciente com este CPF nesta unidade.')

    # Data de nascimento
    try:
        nascimento = datetime.date.fromisoformat((post.get('data_nascimento') or '').strip())
        if nascimento > timezone.localdate() or nascimento.year < 1900:
            raise ValueError
        dados['data_nascimento'] = nascimento
    except ValueError:
        erros.append('Data de nascimento inválida.')

    telefone = g('telefone')
    if not 10 <= len(somente_digitos(telefone)) <= 13 or len(telefone) > 20:
        erros.append('Telefone inválido (use DDD + número).')
    dados['telefone'] = telefone

    email = g('email').lower()
    if email:
        try:
            if len(email) > 254:
                raise ValidationError('longo')
            validate_email(email)
        except ValidationError:
            erros.append('E-mail do paciente inválido.')
    dados['email'] = email or None

    if not cep_valido(post.get('cep')):
        erros.append('CEP inválido.')
    dados['cep'] = formatar_cep(post.get('cep')) if cep_valido(post.get('cep')) else g('cep')

    uf = g('uf').upper()
    if uf not in UFS:
        erros.append('UF inválida.')
    dados['uf'] = uf

    return dados, erros


def pode_gerenciar_categorias(user):
    """Administrador Geral e Coordenador podem criar/editar categorias de TCLE."""
    return eh_admin_geral(user) or user.perfil == 'COORDENADOR'


@login_required
def gerenciar_pacientes(request):
    # 1. Identifica a clínica ativa (a do próprio usuário, ou a que o
    # Administrador Geral escolheu gerenciar)
    instituicao = get_instituicao_contexto(request)

    # Trava de segurança caso ninguém tenha uma unidade ativa no momento
    if not instituicao:
        if eh_admin_geral(request.user):
            messages.error(request, 'Selecione uma Unidade de Saúde para gerenciar antes de acessar pacientes.')
            return redirect('painel_adm')
        messages.error(request, 'Você precisa estar vinculado a uma Unidade de Saúde para acessar pacientes.')
        return redirect('dashboard')

    # 2. Processa os formulários (Criar ou Editar)
    if request.method == 'POST':
        paciente_id = (request.POST.get('paciente_id') or '').strip()
        paciente = None
        if paciente_id:
            # EDITAR: garante que o paciente é da mesma instituição
            paciente = get_object_or_404(Paciente, id=_id_ou_404(paciente_id), instituicao=instituicao)

        dados, erros = _validar_paciente(request.POST, instituicao, paciente)
        if erros:
            messages.error(request, ' '.join(erros))
            return redirect('pacientes')

        try:
            with transaction.atomic():
                if paciente:
                    for campo, valor in dados.items():
                        setattr(paciente, campo, valor)
                    paciente.save()
                    auditoria.info('paciente_editado user=%s unidade=%s paciente=%s',
                                   request.user.pk, instituicao.pk, paciente.pk)
                    messages.success(request, 'Dados do paciente atualizados com sucesso!')
                else:
                    novo = Paciente.objects.create(instituicao=instituicao, criado_por=request.user, **dados)
                    auditoria.info('paciente_criado user=%s unidade=%s paciente=%s',
                                   request.user.pk, instituicao.pk, novo.pk)
                    messages.success(request, 'Novo paciente cadastrado com sucesso!')
        except IntegrityError:
            messages.error(request, 'Erro ao salvar. Já existe um paciente com este CPF nesta unidade.')
        except Exception:
            logger.exception('Falha ao salvar paciente')
            messages.error(request, 'Não foi possível salvar o paciente. Tente novamente.')

        return redirect('pacientes')

    # 3. Carrega a lista de pacientes restrita à instituição do usuário
    pacientes = Paciente.objects.filter(instituicao=instituicao).order_by('-criado_em')

    # 4. Calcula os dados dos Cards Dinâmicos
    hoje = timezone.localdate()
    inicio_mes = hoje.replace(day=1)

    contexto = {
        'pacientes': pacientes,
        'total_pacientes': pacientes.count(),
        'cadastros_hoje': pacientes.filter(criado_em__date=hoje).count(),
        'cadastros_mes': pacientes.filter(criado_em__date__gte=inicio_mes).count(),
    }
    return render(request, 'pacientes/lista.html', contexto)


@login_required
def biblioteca_tcle(request):
    instituicao = get_instituicao_contexto(request)

    if not instituicao:
        if eh_admin_geral(request.user):
            messages.error(request, 'Selecione uma Unidade de Saúde para gerenciar antes de acessar a biblioteca.')
            return redirect('painel_adm')
        messages.error(request, 'Acesso negado. Nenhuma unidade de saúde vinculada.')
        return redirect('dashboard')

    if request.method == 'POST':
        template_id = (request.POST.get('template_id') or '').strip()
        titulo = limpar_texto(request.POST.get('titulo'))
        texto_base = _texto_longo(request.POST.get('texto_base'))
        # Resumo do card: obrigatório, em uma linha só, com limite de caracteres
        resumo = limpar_texto(request.POST.get('resumo'))

        if not resumo:
            messages.error(request, 'Informe o resumo do template.')
            return redirect('biblioteca')
        if len(resumo) > TemplateTCLE.RESUMO_MAX_LENGTH:
            messages.error(
                request,
                f'O resumo deve ter no máximo {TemplateTCLE.RESUMO_MAX_LENGTH} caracteres '
                f'(o texto enviado tem {len(resumo)}).'
            )
            return redirect('biblioteca')
        if not titulo or len(titulo) > 255:
            messages.error(request, 'Informe o título do template (até 255 caracteres).')
            return redirect('biblioteca')
        if not texto_base or len(texto_base) > TEXTO_MAX:
            messages.error(request, f'Informe o texto do template (até {TEXTO_MAX} caracteres).')
            return redirect('biblioteca')

        categoria_obj = get_object_or_404(
            CategoriaTemplate, id=_id_ou_404(request.POST.get('categoria')), instituicao=instituicao)

        try:
            if template_id:
                # EDITAR
                template = get_object_or_404(TemplateTCLE, id=_id_ou_404(template_id), instituicao=instituicao)
                template.titulo = titulo
                template.resumo = resumo
                template.categoria = categoria_obj
                template.texto_base = texto_base
                template.ativo = request.POST.get('ativo') == 'on'  # Transforma o checkbox HTML em Boolean
                template.save()
                auditoria.info('template_editado user=%s unidade=%s template=%s',
                               request.user.pk, instituicao.pk, template.pk)
                messages.success(request, 'Template atualizado com sucesso!')
            else:
                # CRIAR
                novo = TemplateTCLE.objects.create(
                    instituicao=instituicao,
                    categoria=categoria_obj,
                    titulo=titulo,
                    resumo=resumo,
                    texto_base=texto_base,
                    criado_por=request.user,
                    ativo=True
                )
                auditoria.info('template_criado user=%s unidade=%s template=%s',
                               request.user.pk, instituicao.pk, getattr(novo, 'pk', None))
                messages.success(request, 'Novo template adicionado à biblioteca!')
        except Http404:
            raise
        except Exception:
            # Detalhes internos (SQL, nomes de tabelas...) vão para o log, não para a tela
            logger.exception('Falha ao salvar template')
            messages.error(request, 'Não foi possível salvar o template. Tente novamente.')

        return redirect('biblioteca')

    # Carrega templates restritos à instituição
    templates = TemplateTCLE.objects.filter(instituicao=instituicao).select_related('categoria').order_by('-atualizado_em')
    categorias = CategoriaTemplate.objects.filter(instituicao=instituicao).order_by('nome')

    # Texto padrão de cada categoria, para o editor dinâmico do "Novo Template" (JS)
    categorias_json = {
        str(cat.id): {'nome': cat.nome, 'texto': cat.texto_padrao}
        for cat in categorias
    }

    contexto = {
        'templates': templates,
        'categorias': categorias,
        'categorias_dict': categorias_json,
        'resumo_max_length': TemplateTCLE.RESUMO_MAX_LENGTH,
        'pode_gerenciar_categorias': pode_gerenciar_categorias(request.user),
    }
    return render(request, 'pacientes/biblioteca.html', contexto)


def _validar_categoria(post, instituicao, excluir_pk=None):
    nome = limpar_texto(post.get('nome'))
    texto = _texto_longo(post.get('texto_padrao'))
    erro = None
    if not nome or len(nome) > 100:
        erro = 'Informe o nome da categoria (até 100 caracteres).'
    elif len(texto) > TEXTO_MAX:
        erro = f'O texto padrão deve ter no máximo {TEXTO_MAX} caracteres.'
    else:
        duplicada = CategoriaTemplate.objects.filter(instituicao=instituicao, nome__iexact=nome)
        if excluir_pk:
            duplicada = duplicada.exclude(pk=excluir_pk)
        if duplicada.exists():
            erro = 'Erro: já existe uma categoria com esse nome nesta unidade.'
    return nome, texto, erro


@login_required
def criar_categoria(request):
    instituicao = get_instituicao_contexto(request)
    if not instituicao:
        return redirect('painel_adm' if eh_admin_geral(request.user) else 'dashboard')

    if not pode_gerenciar_categorias(request.user):
        messages.error(request, 'Você não tem permissão para gerenciar categorias.')
        return redirect('biblioteca')

    if request.method == 'POST':
        nome, texto, erro = _validar_categoria(request.POST, instituicao)
        if erro:
            messages.error(request, erro)
            return redirect('biblioteca')
        try:
            with transaction.atomic():
                CategoriaTemplate.objects.create(
                    instituicao=instituicao, nome=nome, texto_padrao=texto, criado_por=request.user)
            messages.success(request, 'Categoria cadastrada com sucesso!')
        except IntegrityError:
            messages.error(request, 'Erro: já existe uma categoria com esse nome nesta unidade.')

    return redirect('biblioteca')


@login_required
def editar_categoria(request, categoria_id):
    instituicao = get_instituicao_contexto(request)
    if not instituicao:
        return redirect('painel_adm' if eh_admin_geral(request.user) else 'dashboard')

    if not pode_gerenciar_categorias(request.user):
        messages.error(request, 'Você não tem permissão para gerenciar categorias.')
        return redirect('biblioteca')

    categoria = get_object_or_404(CategoriaTemplate, id=categoria_id, instituicao=instituicao)

    if request.method == 'POST':
        nome, texto, erro = _validar_categoria(request.POST, instituicao, excluir_pk=categoria.pk)
        if erro:
            messages.error(request, erro)
            return redirect('biblioteca')
        categoria.nome = nome
        categoria.texto_padrao = texto
        try:
            with transaction.atomic():
                categoria.save()
            messages.success(request, 'Categoria atualizada com sucesso!')
        except IntegrityError:
            messages.error(request, 'Erro: já existe uma categoria com esse nome nesta unidade.')

    return redirect('biblioteca')


@login_required
def gerar_tcle(request):
    instituicao = get_instituicao_contexto(request)

    if not instituicao:
        if eh_admin_geral(request.user):
            messages.error(request, 'Selecione uma Unidade de Saúde para gerar um TCLE.')
            return redirect('painel_adm')
        messages.error(request, 'Você precisa estar vinculado a uma Unidade de Saúde para gerar um TCLE.')
        return redirect('dashboard')

    if request.method == 'POST':
        tipo = request.POST.get('tipo')  # 'paciente' ou 'responsavel'
        responsavel_id = request.POST.get('responsavel_id')
        texto_final = _texto_longo(request.POST.get('texto_final'))
        assinatura_paciente = (request.POST.get('assinatura_paciente') or '').strip()
        assinatura_profissional = (request.POST.get('assinatura_profissional') or '').strip()

        # Só documentos e pacientes DESTA unidade; template precisa estar ativo.
        template_obj = get_object_or_404(
            TemplateTCLE, id=_id_ou_404(request.POST.get('template_id')),
            instituicao=instituicao, ativo=True)
        paciente_obj = get_object_or_404(
            Paciente, id=_id_ou_404(request.POST.get('paciente_id')), instituicao=instituicao)

        if tipo not in ('paciente', 'responsavel'):
            messages.error(request, 'Tipo de assinante inválido.')
            return redirect('gerar_tcle')

        responsavel_obj = None
        if tipo == 'responsavel':
            if not responsavel_id:
                messages.error(request, 'Selecione o Responsável para continuar.')
                return redirect('gerar_tcle')
            responsavel_obj = get_object_or_404(
                Paciente, id=_id_ou_404(responsavel_id), instituicao=instituicao)

        if not texto_final:
            messages.error(request, 'O texto do termo não pode ficar vazio.')
            return redirect('gerar_tcle')
        if len(texto_final) > TEXTO_MAX:
            messages.error(request, f'O texto do termo deve ter no máximo {TEXTO_MAX} caracteres.')
            return redirect('gerar_tcle')

        if not assinatura_paciente or not assinatura_profissional:
            messages.error(request, 'É necessário coletar as duas assinaturas (Paciente/Responsável e Profissional) antes de salvar.')
            return redirect('gerar_tcle')
        if not (assinatura_valida(assinatura_paciente) and assinatura_valida(assinatura_profissional)):
            messages.error(request, 'Assinatura inválida. Refaça a assinatura (imagem PNG/JPEG de até ~750 KB).')
            return redirect('gerar_tcle')

        dados_preenchidos = {
            'tipo': tipo,
            'paciente': {'nome': paciente_obj.nome, 'cpf': paciente_obj.cpf, 'rg': paciente_obj.rg},
            'responsavel': (
                {'nome': responsavel_obj.nome, 'cpf': responsavel_obj.cpf, 'rg': responsavel_obj.rg}
                if responsavel_obj else None
            ),
            'profissional': {
                'nome': request.user.get_full_name() or request.user.username,
                'profissao': request.user.profissao or '',
                'registro': request.user.registro_profissional or '',
            },
            'data': timezone.localdate().strftime('%d/%m/%Y'),
        }

        documento = DocumentoEmitido.objects.create(
            instituicao=instituicao,
            paciente=paciente_obj,
            template_origem=template_obj,
            medico_emissor=request.user,
            dados_preenchidos=dados_preenchidos,
            responsavel_nome=responsavel_obj.nome if responsavel_obj else None,
            responsavel_cpf=responsavel_obj.cpf if responsavel_obj else None,
            responsavel_rg=responsavel_obj.rg if responsavel_obj else None,
            texto_final=texto_final,
            assinatura_paciente=assinatura_paciente,
            assinatura_profissional=assinatura_profissional,
            status='ASSINADO',
        )
        auditoria.info('tcle_emitido user=%s unidade=%s documento=%s paciente=%s',
                       request.user.pk, instituicao.pk, documento.pk, paciente_obj.pk)

        messages.success(request, 'TCLE gerado e assinado com sucesso!')
        return redirect('pacientes')

    templates = TemplateTCLE.objects.filter(instituicao=instituicao, ativo=True).select_related('categoria').order_by('titulo')
    pacientes = Paciente.objects.filter(instituicao=instituicao).order_by('nome')

    templates_json = {
        str(t.id): {'titulo': t.titulo, 'categoria': t.categoria.nome, 'texto': t.texto_base}
        for t in templates
    }
    pacientes_json = {
        str(p.id): {'nome': p.nome, 'cpf': p.cpf, 'rg': p.rg}
        for p in pacientes
    }
    profissional_json = {
        'nome': request.user.get_full_name() or request.user.username,
        'profissao': request.user.profissao or '',
        'registro': request.user.registro_profissional or '',
    }

    contexto = {
        'templates': templates,
        'pacientes': pacientes,
        'templates_dict': templates_json,
        'pacientes_dict': pacientes_json,
        'profissional_dict': profissional_json,
        'data_hoje': timezone.localdate().strftime('%d/%m/%Y'),
    }
    return render(request, 'pacientes/gerar_tcle.html', contexto)


@login_required
def historico_tcle(request):
    instituicao = get_instituicao_contexto(request)

    if not instituicao:
        if eh_admin_geral(request.user):
            messages.error(request, 'Selecione uma Unidade de Saúde para ver o histórico.')
            return redirect('painel_adm')
        messages.error(request, 'Você precisa estar vinculado a uma Unidade de Saúde para ver o histórico.')
        return redirect('dashboard')

    documentos_base = DocumentoEmitido.objects.filter(instituicao=instituicao)

    total = documentos_base.count()
    total_assinados = documentos_base.filter(status='ASSINADO').count()
    total_pendentes = documentos_base.filter(status='PENDENTE').count()
    total_recusados = documentos_base.filter(status='RECUSADO').count()

    documentos = documentos_base.select_related(
        'paciente', 'template_origem', 'template_origem__categoria', 'medico_emissor'
    ).order_by('-data_emissao')

    busca = limpar_texto(request.GET.get('busca'))[:100]
    status_filtro = (request.GET.get('status') or '').strip()
    if status_filtro not in dict(DocumentoEmitido.STATUS_CHOICES):
        status_filtro = ''

    if busca:
        documentos = documentos.filter(
            Q(paciente__nome__icontains=busca) |
            Q(template_origem__titulo__icontains=busca) |
            Q(template_origem__categoria__nome__icontains=busca)
        )
    if status_filtro:
        documentos = documentos.filter(status=status_filtro)

    documentos_view = [
        {'obj': doc, 'corpo_html': renderizar_corpo_documento(doc)}
        for doc in documentos
    ]

    contexto = {
        'documentos_view': documentos_view,
        'busca': busca,
        'status_filtro': status_filtro,
        'status_choices': DocumentoEmitido.STATUS_CHOICES,
        'total': total,
        'total_assinados': total_assinados,
        'total_pendentes': total_pendentes,
        'total_recusados': total_recusados,
        'total_filtrado': len(documentos_view),
    }
    return render(request, 'pacientes/historico.html', contexto)


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------
_DATA_IMAGEM_RE = re.compile(r'^data:image/(png|jpeg);base64,', re.IGNORECASE)


def _bloquear_se_nao_for_imagem_embutida(url):
    if not _DATA_IMAGEM_RE.match(url or ''):
        raise ValueError('Recurso externo bloqueado na geração do PDF.')


try:  # WeasyPrint >= 69: o fetcher é uma classe
    from weasyprint import URLFetcher as _URLFetcherBase

    class _FetcherSeguro(_URLFetcherBase):
        def fetch(self, url, headers=None):
            _bloquear_se_nao_for_imagem_embutida(url)
            return super().fetch(url, headers)

    pdf_url_fetcher = _FetcherSeguro(allowed_protocols=['data'])
except ImportError:  # WeasyPrint < 69: o fetcher é uma função
    def pdf_url_fetcher(url, *args, **kwargs):
        _bloquear_se_nao_for_imagem_embutida(url)
        from weasyprint import default_url_fetcher
        return default_url_fetcher(url, allowed_protocols=['data'])


def _importar_weasyprint():
    from weasyprint import HTML
    return HTML


def _gerar_pdf_bytes(request, documento):
    """
    Renderiza o template documento_pdf.html e converte para PDF via
    WeasyPrint. Retorna None se o WeasyPrint (ou suas dependências de
    sistema, como Pango/Cairo) não estiver disponível no ambiente.
    """
    try:
        HTML = _importar_weasyprint()
    except (ImportError, OSError):
        return None

    contexto = {
        'documento': documento,
        'instituicao': documento.instituicao,
        'corpo_html': renderizar_corpo_documento(documento),
    }
    html_string = render_to_string('pacientes/documento_pdf.html', contexto, request=request)
    return HTML(string=html_string, url_fetcher=pdf_url_fetcher).write_pdf()


def _nome_arquivo_pdf(documento):
    """Nome de arquivo ASCII seguro (sem aspas, quebras de linha ou acentos)."""
    base = unicodedata.normalize('NFKD', documento.paciente.nome).encode('ascii', 'ignore').decode()
    base = re.sub(r'[^A-Za-z0-9]+', '_', base).strip('_')[:60] or 'paciente'
    return f'TCLE_{base}_{documento.id}.pdf'


def _documento_da_unidade(request, documento_id):
    instituicao = get_instituicao_contexto(request)
    return get_object_or_404(
        DocumentoEmitido.objects.select_related(
            'paciente', 'template_origem', 'template_origem__categoria', 'medico_emissor', 'instituicao'),
        id=documento_id, instituicao=instituicao,
    )


@login_required
def documento_pdf(request, documento_id):
    documento = _documento_da_unidade(request, documento_id)
    auditoria.info('tcle_visualizado user=%s unidade=%s documento=%s',
                   request.user.pk, documento.instituicao_id, documento.pk)

    pdf_bytes = _gerar_pdf_bytes(request, documento)

    if pdf_bytes is None:
        # Ambiente sem as dependências de sistema do WeasyPrint (Pango/Cairo)
        # instaladas: devolve o termo em HTML para impressão manual do navegador.
        contexto = {
            'documento': documento,
            'instituicao': documento.instituicao,
            'corpo_html': renderizar_corpo_documento(documento),
        }
        return render(request, 'pacientes/documento_pdf.html', contexto)

    resposta = HttpResponse(pdf_bytes, content_type='application/pdf')
    resposta['Content-Disposition'] = f'inline; filename="{_nome_arquivo_pdf(documento)}"'
    return resposta


@login_required
def documento_enviar_email(request, documento_id):
    documento = _documento_da_unidade(request, documento_id)

    if request.method != 'POST':
        return redirect('historico')

    nome_paciente = limpar_texto(documento.paciente.nome)
    destinatario = documento.paciente.email
    if not destinatario:
        messages.error(
            request,
            f'Não foi possível enviar: o paciente {nome_paciente} não possui e-mail cadastrado.'
        )
        return redirect('historico')

    pdf_bytes = _gerar_pdf_bytes(request, documento)
    if not pdf_bytes:
        messages.error(request, 'Não foi possível gerar o PDF neste servidor; o e-mail não foi enviado.')
        return redirect('historico')

    template = documento.template_origem  # pode ter sido removido (SET_NULL)
    categoria = template.categoria.nome if template else 'Documento'
    titulo = template.titulo if template else 'Termo de Consentimento'

    assunto = limpar_texto(f'TCLE - {categoria} - {nome_paciente}')
    corpo = (
        f'Olá, {nome_paciente}.\n\n'
        f'Segue em anexo o Termo de Consentimento Livre e Esclarecido referente a '
        f'"{limpar_texto(categoria)} - {limpar_texto(titulo)}", '
        f'emitido em {timezone.localtime(documento.data_emissao).strftime("%d/%m/%Y às %H:%M")}.\n\n'
        f'Este é um e-mail automático enviado por TCLE Digital.'
    )

    email = EmailMessage(assunto, corpo, to=[destinatario])
    email.attach(_nome_arquivo_pdf(documento), pdf_bytes, 'application/pdf')

    try:
        email.send(fail_silently=False)
        auditoria.info('tcle_enviado_email user=%s unidade=%s documento=%s',
                       request.user.pk, documento.instituicao_id, documento.pk)
        messages.success(request, f'TCLE enviado por e-mail para {destinatario}.')
    except Exception:
        logger.exception('Falha ao enviar e-mail do TCLE %s', documento.pk)
        messages.error(request, 'Não foi possível enviar o e-mail. Verifique a configuração de e-mail e tente novamente.')

    return redirect('historico')
