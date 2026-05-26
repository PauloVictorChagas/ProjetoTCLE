from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone 
from .models import Paciente
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