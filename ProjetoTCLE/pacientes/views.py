from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from .models import Paciente, TemplateTCLE, CategoriaTemplate

@login_required
def gerenciar_pacientes(request):
    # 1. Identifica a clínica do usuário logado
    instituicao = request.user.instituicao
    
    # Trava de segurança caso um ADM sem clínica acesse a rota
    if not instituicao:
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
    instituicao = request.user.instituicao
    
    if not instituicao:
        messages.error(request, 'Acesso negado. Nenhuma unidade de saúde vinculada.')
        return redirect('dashboard')

    if request.method == 'POST':
        template_id = request.POST.get('template_id')
        titulo = request.POST.get('titulo')
        nome_categoria = request.POST.get('categoria')
        texto_base = request.POST.get('texto_base')
        
        # Como Categoria é uma Chave Estrangeira, nós pegamos do banco ou criamos uma nova na hora
        categoria_obj, created = CategoriaTemplate.objects.get_or_create(
            instituicao=instituicao,
            nome=nome_categoria
        )

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
    templates = TemplateTCLE.objects.filter(instituicao=instituicao).order_by('-atualizado_em')
    
    contexto = {
        'templates': templates
    }
    return render(request, 'pacientes/biblioteca.html', contexto)


@login_required
def teste_pdf(request):
    # Rota provisória para mantermos o urls.py funcionando
    return render(request, 'pacientes/teste_pdf.html')