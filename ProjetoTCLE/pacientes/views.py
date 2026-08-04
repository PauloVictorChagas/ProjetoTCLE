import json
import re
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.http import HttpResponse
from .models import Paciente, TemplateTCLE, CategoriaTemplate, DocumentoEmitido
from usuarios.utils import get_instituicao_contexto, eh_admin_geral


TOKEN_ASSINATURA_PACIENTE = re.compile(r'\[assinatura_paciente\]', re.IGNORECASE)
TOKEN_ASSINATURA_PROFISSIONAL = re.compile(r'\[assinatura_profissional\]', re.IGNORECASE)


def renderizar_corpo_documento(documento):
    """
    Escapa o texto final do TCLE e substitui os marcadores de assinatura
    ([assinatura_paciente] / [assinatura_profissional]) pelas imagens
    capturadas, exatamente no ponto do texto em que foram inseridos na
    categoria. Se o template não tiver marcadores, as assinaturas
    disponíveis são anexadas ao final do documento.
    """
    texto_escapado = escape(documento.texto_final or '')

    img_paciente = (
        f'<img src="{documento.assinatura_paciente}" class="assinatura-img">'
        if documento.assinatura_paciente else
        '<span class="assinatura-pendente">(assinatura do paciente/responsável)</span>'
    )
    img_profissional = (
        f'<img src="{documento.assinatura_profissional}" class="assinatura-img">'
        if documento.assinatura_profissional else
        '<span class="assinatura-pendente">(assinatura do profissional)</span>'
    )

    tinha_token_paciente = bool(TOKEN_ASSINATURA_PACIENTE.search(texto_escapado))
    tinha_token_profissional = bool(TOKEN_ASSINATURA_PROFISSIONAL.search(texto_escapado))

    html = TOKEN_ASSINATURA_PACIENTE.sub(img_paciente, texto_escapado)
    html = TOKEN_ASSINATURA_PROFISSIONAL.sub(img_profissional, html)
    html = html.replace('\n', '<br>')

    extra = ''
    if not tinha_token_paciente and documento.assinatura_paciente:
        extra += (
            '<div class="assinatura-bloco"><p class="assinatura-legenda">'
            f'Assinatura do Paciente/Responsável</p>{img_paciente}</div>'
        )
    if not tinha_token_profissional and documento.assinatura_profissional:
        extra += (
            '<div class="assinatura-bloco"><p class="assinatura-legenda">'
            f'Assinatura do Profissional</p>{img_profissional}</div>'
        )

    return mark_safe(html + extra)


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
        paciente_id = request.POST.get('paciente_id')
        
        # Coleta os dados do HTML
        nome = request.POST.get('nome')
        cpf = request.POST.get('cpf')
        rg = request.POST.get('rg')
        data_nascimento = request.POST.get('data_nascimento')
        telefone = request.POST.get('telefone')
        email = request.POST.get('email')
        cep = request.POST.get('cep')
        tipo_logradouro = request.POST.get('tipo_logradouro')
        logradouro = request.POST.get('logradouro')
        numero = request.POST.get('numero')
        complemento = request.POST.get('complemento')
        bairro = request.POST.get('bairro')
        cidade = request.POST.get('cidade')
        uf = request.POST.get('uf')

        try:
            if paciente_id:
                # EDITAR PACIENTE EXISTENTE (Garantindo que é da mesma instituição)
                paciente = get_object_or_404(Paciente, id=paciente_id, instituicao=instituicao)
                paciente.nome = nome
                paciente.cpf = cpf
                paciente.rg = rg
                paciente.data_nascimento = data_nascimento
                paciente.telefone = telefone
                paciente.email = email
                paciente.cep = cep
                paciente.tipo_logradouro = tipo_logradouro
                paciente.logradouro = logradouro
                paciente.numero = numero
                paciente.complemento = complemento
                paciente.bairro = bairro
                paciente.cidade = cidade
                paciente.uf = uf
                paciente.save()
                messages.success(request, 'Dados do paciente atualizados com sucesso!')
            else:
                # CADASTRAR NOVO PACIENTE
                Paciente.objects.create(
                    instituicao=instituicao,
                    nome=nome,
                    cpf=cpf,
                    rg=rg,
                    data_nascimento=data_nascimento,
                    telefone=telefone,
                    email=email,
                    cep=cep,
                    tipo_logradouro=tipo_logradouro,
                    logradouro=logradouro,
                    numero=numero,
                    complemento=complemento,
                    bairro=bairro,
                    cidade=cidade,
                    uf=uf,
                    criado_por=request.user
                )
                messages.success(request, 'Novo paciente cadastrado com sucesso!')
        except Exception as e:
            messages.error(request, 'Erro ao salvar. Verifique se o CPF já está cadastrado nesta unidade.')

        return redirect('pacientes')

    # 3. Carrega a lista de pacientes restrita à instituição do usuário
    pacientes = Paciente.objects.filter(instituicao=instituicao).order_by('-criado_em')
    
    # 4. Calcula os dados dos Cards Dinâmicos
    hoje = timezone.now().date()
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
        template_id = request.POST.get('template_id')
        titulo = request.POST.get('titulo')
        categoria_id = request.POST.get('categoria')
        texto_base = request.POST.get('texto_base')

        categoria_obj = get_object_or_404(CategoriaTemplate, id=categoria_id, instituicao=instituicao)

        try:
            if template_id:
                # EDITAR
                template = get_object_or_404(TemplateTCLE, id=template_id, instituicao=instituicao)
                template.titulo = titulo
                template.categoria = categoria_obj
                template.texto_base = texto_base
                template.ativo = request.POST.get('ativo') == 'on' # Transforma o checkbox HTML em Boolean
                template.save()
                messages.success(request, 'Template atualizado com sucesso!')
            else:
                # CRIAR
                TemplateTCLE.objects.create(
                    instituicao=instituicao,
                    categoria=categoria_obj,
                    titulo=titulo,
                    texto_base=texto_base,
                    criado_por=request.user,
                    ativo=True
                )
                messages.success(request, 'Novo template adicionado à biblioteca!')
        except Exception as e:
            messages.error(request, f'Erro ao salvar template: {str(e)}')

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
        'pode_gerenciar_categorias': pode_gerenciar_categorias(request.user),
    }
    return render(request, 'pacientes/biblioteca.html', contexto)


@login_required
def criar_categoria(request):
    instituicao = get_instituicao_contexto(request)
    if not instituicao:
        return redirect('painel_adm' if eh_admin_geral(request.user) else 'dashboard')

    if not pode_gerenciar_categorias(request.user):
        messages.error(request, 'Você não tem permissão para gerenciar categorias.')
        return redirect('biblioteca')

    if request.method == 'POST':
        nome = request.POST.get('nome')
        texto_padrao = request.POST.get('texto_padrao', '')

        try:
            CategoriaTemplate.objects.create(
                instituicao=instituicao,
                nome=nome,
                texto_padrao=texto_padrao,
                criado_por=request.user,
            )
            messages.success(request, 'Categoria cadastrada com sucesso!')
        except Exception:
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
        categoria.nome = request.POST.get('nome')
        categoria.texto_padrao = request.POST.get('texto_padrao', '')
        try:
            categoria.save()
            messages.success(request, 'Categoria atualizada com sucesso!')
        except Exception:
            messages.error(request, 'Erro: já existe uma categoria com esse nome nesta unidade.')

    return redirect('biblioteca')


@login_required
def teste_pdf(request):
    # Rota provisória para mantermos o urls.py funcionando
    return render(request, 'pacientes/teste_pdf.html')


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
        template_id = request.POST.get('template_id')
        paciente_id = request.POST.get('paciente_id')
        tipo = request.POST.get('tipo')  # 'paciente' ou 'responsavel'
        responsavel_id = request.POST.get('responsavel_id')
        texto_final = request.POST.get('texto_final', '').strip()
        assinatura_paciente = request.POST.get('assinatura_paciente', '').strip()
        assinatura_profissional = request.POST.get('assinatura_profissional', '').strip()

        template_obj = get_object_or_404(TemplateTCLE, id=template_id, instituicao=instituicao)
        paciente_obj = get_object_or_404(Paciente, id=paciente_id, instituicao=instituicao)

        responsavel_obj = None
        if tipo == 'responsavel':
            if not responsavel_id:
                messages.error(request, 'Selecione o Responsável para continuar.')
                return redirect('gerar_tcle')
            responsavel_obj = get_object_or_404(Paciente, id=responsavel_id, instituicao=instituicao)

        if not texto_final:
            messages.error(request, 'O texto do termo não pode ficar vazio.')
            return redirect('gerar_tcle')

        if not assinatura_paciente or not assinatura_profissional:
            messages.error(request, 'É necessário coletar as duas assinaturas (Paciente/Responsável e Profissional) antes de salvar.')
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

        DocumentoEmitido.objects.create(
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

    documentos = DocumentoEmitido.objects.filter(instituicao=instituicao).select_related(
        'paciente', 'template_origem', 'template_origem__categoria', 'medico_emissor'
    ).order_by('-data_emissao')

    busca = request.GET.get('busca', '').strip()
    if busca:
        documentos = documentos.filter(paciente__nome__icontains=busca)

    documentos_view = []
    for doc in documentos:
        documentos_view.append({
            'obj': doc,
            'corpo_html': renderizar_corpo_documento(doc),
        })

    contexto = {
        'documentos_view': documentos_view,
        'busca': busca,
    }
    return render(request, 'pacientes/historico.html', contexto)


@login_required
def documento_pdf(request, documento_id):
    instituicao = get_instituicao_contexto(request)
    documento = get_object_or_404(
        DocumentoEmitido.objects.select_related('paciente', 'template_origem', 'template_origem__categoria', 'medico_emissor'),
        id=documento_id, instituicao=instituicao,
    )

    contexto = {
        'documento': documento,
        'instituicao': instituicao,
        'corpo_html': renderizar_corpo_documento(documento),
    }
    html_string = render(request, 'pacientes/documento_pdf.html', contexto).content.decode('utf-8')

    try:
        from weasyprint import HTML
    except ImportError:
        # Ambiente sem as dependências de sistema do WeasyPrint (Pango/Cairo)
        # instaladas: devolve o termo em HTML para impressão manual do navegador.
        return HttpResponse(html_string)

    pdf_bytes = HTML(string=html_string, base_url=request.build_absolute_uri('/')).write_pdf()
    resposta = HttpResponse(pdf_bytes, content_type='application/pdf')
    nome_arquivo = f"TCLE_{documento.paciente.nome.replace(' ', '_')}_{documento.id}.pdf"
    resposta['Content-Disposition'] = f'inline; filename="{nome_arquivo}"'
    return resposta
