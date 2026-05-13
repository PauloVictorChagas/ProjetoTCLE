from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import Paciente

@login_required
def gerenciar_pacientes(request):
    # Se o formulário foi enviado para cadastrar um paciente
    if request.method == 'POST':
        nome = request.POST.get('nome')
        cpf = request.POST.get('cpf')
        data_nascimento = request.POST.get('data_nascimento')
        telefone = request.POST.get('telefone')
        email = request.POST.get('email')
        endereco = request.POST.get('endereco')

        try:
            # Salva o paciente no banco de dados
            Paciente.objects.create(
                nome=nome,
                cpf=cpf,
                data_nascimento=data_nascimento,
                telefone=telefone,
                email=email,
                endereco=endereco,
                criado_por=request.user # Registra qual médico/admin cadastrou
            )
            messages.success(request, 'Paciente cadastrado com sucesso!')
            return redirect('pacientes')
            
        except Exception as e:
            messages.error(request, 'Erro ao cadastrar. Verifique se este CPF já está no sistema.')

    # Busca todos os pacientes ordenados pelos cadastros mais recentes
    lista_pacientes = Paciente.objects.all().order_by('-criado_em')
    
    return render(request, 'pacientes/lista.html', {'pacientes': lista_pacientes})