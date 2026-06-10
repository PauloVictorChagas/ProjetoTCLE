from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone 
from .models import Paciente, TemplateTCLE
from weasyprint import HTML
from django.http import HttpResponse

@login_required
def gerenciar_pacientes(request):
    if request.method == 'POST':
        paciente_id = request.POST.get('paciente_id')
        
        # Coleta todos os dados do formulário
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

        if paciente_id:
            # MODO EDIÇÃO
            try:
                paciente = Paciente.objects.get(id=paciente_id)
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
                messages.success(request, 'Paciente atualizado com sucesso!')
            except Exception as e:
                messages.error(request, 'Erro ao atualizar: Verifique se o CPF/RG já existem em outro cadastro.')
        else:
            # MODO CRIAÇÃO (Novo Paciente)
            try:
                Paciente.objects.create(
                    nome=nome, cpf=cpf, rg=rg, data_nascimento=data_nascimento,
                    telefone=telefone, email=email, cep=cep, tipo_logradouro=tipo_logradouro,
                    logradouro=logradouro, numero=numero, complemento=complemento,
                    bairro=bairro, cidade=cidade, uf=uf, criado_por=request.user
                )
                messages.success(request, 'Paciente cadastrado com sucesso!')
            except Exception as e:
                messages.error(request, f'Erro ao cadastrar: {str(e)}')

        # Este return pertence ao IF do POST (alinhado com o 'if paciente_id:')
        return redirect('pacientes')

    # MODO LEITURA (GET) - Este bloco é ativado ao apenas abrir a página
    # Fica alinhado com o primeiro 'if request.method'
    pacientes = Paciente.objects.all().order_by('-criado_em')
    
    hoje = timezone.now().date()
    total_pacientes = pacientes.count()
    cadastros_hoje = pacientes.filter(criado_em__date=hoje).count()
    cadastros_mes = pacientes.filter(criado_em__year=hoje.year, criado_em__month=hoje.month).count()
    
    contexto = {
        'pacientes': pacientes,
        'total_pacientes': total_pacientes,
        'cadastros_hoje': cadastros_hoje,
        'cadastros_mes': cadastros_mes,
    }
    
    return render(request, 'pacientes/lista.html', contexto)

def teste_pdf(request):
    html = HTML(string="<h1>WeasyPrint funcionando!</h1>")
    pdf = html.write_pdf()
    return HttpResponse(pdf, content_type="application/pdf")

#View para a Biblioteca de Templates do TCLE

@login_required
def biblioteca_tcle(request):
    if request.method == 'POST':
        # Pegamos todos os dados do formulário
        template_id = request.POST.get('template_id') # Campo oculto que diz se é edição
        titulo = request.POST.get('titulo')
        categoria = request.POST.get('categoria')
        texto_base = request.POST.get('texto_base')
        ativo = request.POST.get('ativo') == 'on' # Se o checkbox estiver marcado, retorna True
        
        if template_id:
            # MODO EDIÇÃO
            try:
                template = TemplateTCLE.objects.get(id=template_id)
                template.titulo = titulo
                template.categoria = categoria
                template.texto_base = texto_base
                template.ativo = ativo
                template.save()
                messages.success(request, 'Template atualizado com sucesso!')
            except Exception as e:
                messages.error(request, 'Erro ao atualizar o template.')
        else:
            # MODO CRIAÇÃO (Novo Template)
            try:
                TemplateTCLE.objects.create(
                    titulo=titulo,
                    categoria=categoria,
                    texto_base=texto_base,
                    ativo=True, # Novos sempre nascem ativos
                    criado_por=request.user
                )
                messages.success(request, 'Template cadastrado com sucesso!')
            except Exception as e:
                messages.error(request, 'Erro ao salvar o template.')

        return redirect('biblioteca')

    templates = TemplateTCLE.objects.all().order_by('-atualizado_em')
    return render(request, 'pacientes/biblioteca.html', {'templates': templates})