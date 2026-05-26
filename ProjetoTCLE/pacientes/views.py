from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone 
from .models import Paciente, TemplateTCLE
from weasyprint import HTML
from django.http import HttpResponse

@login_required
def gerenciar_pacientes(request):
    # Lógica de Cadastro
    if request.method == 'POST':
        nome = request.POST.get('nome')
        cpf = request.POST.get('cpf')
        data_nascimento = request.POST.get('data_nascimento')
        telefone = request.POST.get('telefone')
        email = request.POST.get('email')
        endereco = request.POST.get('endereco')

        try:
            Paciente.objects.create(
                nome=nome,
                cpf=cpf,
                data_nascimento=data_nascimento,
                telefone=telefone,
                email=email,
                endereco=endereco,
                criado_por=request.user
            )
            messages.success(request, 'Paciente cadastrado com sucesso!')
            return redirect('pacientes')
        except Exception as e:
            messages.error(request, 'Erro ao cadastrar. Verifique os dados.')

    # Buscando todos os pacientes
    pacientes = Paciente.objects.all().order_by('-criado_em')
    
    # Calculando estatísticas para os Cards
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