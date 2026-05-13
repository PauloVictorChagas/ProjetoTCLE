from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from .models import Usuario

# 1. Função que o 'segurança' vai usar para testar se é Admin
def eh_admin(user):
    return user.perfil == 'ADMIN'

@login_required
def dashboard(request):
    return render(request, 'usuarios/dashboard.html')

# O segurança testa: Se não for admin, manda de volta pro dashboard
@login_required
@user_passes_test(eh_admin, login_url='dashboard')
def gerenciar_equipe(request):
    # Se o formulário foi enviado (método POST)
    if request.method == 'POST':
        nome = request.POST.get('nome')
        email = request.POST.get('email')
        perfil = request.POST.get('perfil')
        profissao = request.POST.get('profissao')
        senha = request.POST.get('senha')
        
        try:
            # Usamos o nosso Manager para criar o usuário de forma segura
            Usuario.objects.create_user(
                email=email,
                password=senha,
                nome=nome,
                perfil=perfil,
                profissao=profissao
            )
            # Avisa que deu certo e recarrega a página
            messages.success(request, 'Membro da equipe cadastrado com sucesso!')
            return redirect('gerenciar_equipe')
            
        except Exception as e:
            # Se o email já existir, por exemplo, ele cai aqui
            messages.error(request, f'Erro ao cadastrar: Esse e-mail já está em uso.')

    # Pega todos os usuários cadastrados do banco de dados para mostrar na tabela
    equipe = Usuario.objects.all().order_by('nome')
    
    return render(request, 'usuarios/gerenciar_equipe.html', {'equipe': equipe})