from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import update_session_auth_hash
from django.contrib import messages
from .models import Instituicao, Usuario
from .utils import eh_admin_geral, get_instituicao_contexto

def eh_admin(user):
    return eh_admin_geral(user)


@login_required
@user_passes_test(eh_admin, login_url='dashboard')
def entrar_unidade(request, id_instituicao):
    """
    O Administrador Geral clica no card de uma Unidade de Saúde e passa a
    'gerenciá-la' como se fosse o Coordenador daquela unidade.
    """
    instituicao = get_object_or_404(Instituicao, id=id_instituicao)
    request.session['instituicao_ativa_id'] = instituicao.id
    messages.success(request, f'Você está gerenciando a unidade "{instituicao.nome}".')
    return redirect('dashboard')


@login_required
@user_passes_test(eh_admin, login_url='dashboard')
def sair_unidade(request):
    """Encerra a 'impersonação' e devolve o Administrador ao painel geral."""
    request.session.pop('instituicao_ativa_id', None)
    return redirect('painel_adm')

@login_required
def dashboard(request):
    # Se for o primeiro acesso (e não for o ADM principal), força a troca de senha
    if request.user.primeiro_acesso and not request.user.is_superuser:
        messages.warning(request, 'Por segurança, você precisa alterar sua senha provisória.')
        return redirect('trocar_senha')
    return render(request, 'usuarios/dashboard.html')

@login_required
def trocar_senha(request):
    if request.method == 'POST':
        senha1 = request.POST.get('senha1')
        senha2 = request.POST.get('senha2')
        
        if senha1 == senha2 and len(senha1) >= 6:
            request.user.set_password(senha1)
            request.user.primeiro_acesso = False # Tira a trava
            request.user.save()
            update_session_auth_hash(request, request.user) # Impede o Django de deslogar o usuário
            messages.success(request, 'Sua senha foi atualizada com sucesso!')
            return redirect('dashboard')
        else:
            messages.error(request, 'As senhas não coincidem ou são muito curtas (mínimo 6 caracteres).')
            
    return render(request, 'usuarios/trocar_senha.html')

@login_required
def gerenciar_equipe(request, id_instituicao=None):
    is_admin = eh_admin_geral(request.user)
    is_coordenador = request.user.perfil == 'COORDENADOR'

    # Se vier um ID explícito na URL (link antigo), passamos a "entrar" nessa
    # unidade também, para manter a sessão consistente com a sidebar.
    if id_instituicao and is_admin:
        request.session['instituicao_ativa_id'] = id_instituicao

    instituicao = get_instituicao_contexto(request)

    if not instituicao:
        if is_admin:
            return redirect('painel_adm')
        messages.error(request, 'Você precisa estar vinculado a uma Unidade de Saúde.')
        return redirect('dashboard')

    # Só o Administrador e o Coordenador têm acesso a esta tela
    if not (is_admin or is_coordenador):
        messages.error(request, 'Você não tem permissão para acessar a Gestão de Equipe.')
        return redirect('dashboard')

    # Lógica de salvar um novo membro (POST)
    if request.method == 'POST':
        nome = request.POST.get('nome')
        email = request.POST.get('email')
        perfil = request.POST.get('perfil')
        profissao = request.POST.get('profissao')
        senha = request.POST.get('senha')

        # Trava de segurança no servidor: o Coordenador só pode cadastrar
        # Usuário Padrão, não importa o que tenha vindo no formulário.
        if not is_admin:
            perfil = 'PADRAO'

        try:
            novo_user = Usuario.objects.create_user(username=email, email=email, password=senha)
            # Forçamos a injeção dos dados extras para não ter erro
            novo_user.first_name = nome
            novo_user.perfil = perfil
            novo_user.profissao = profissao
            novo_user.instituicao = instituicao
            novo_user.primeiro_acesso = True
            novo_user.save()
            messages.success(request, 'Usuário cadastrado com sucesso!')
        except Exception as e:
            messages.error(request, 'Erro: Este e-mail já está em uso no sistema.')
        
        # Recarrega a página certa
        if id_instituicao:
            return redirect('gerenciar_equipe_inst', id_instituicao=instituicao.id)
        return redirect('gerenciar_equipe')

    equipe = Usuario.objects.filter(instituicao=instituicao).order_by('-date_joined')
    contexto = {
        'equipe': equipe,
        'instituicao_atual': instituicao,
        # Só o Administrador pode editar cadastros existentes e cadastrar Coordenadores
        'pode_editar': is_admin,
        'pode_cadastrar_coordenador': is_admin,
    }
    return render(request, 'usuarios/gerenciar_equipe.html', contexto)


@login_required
@user_passes_test(eh_admin, login_url='dashboard')
def editar_membro_equipe(request, membro_id):
    """
    Atualiza os dados de um membro já cadastrado.
    Exclusivo do Administrador Geral: o Coordenador não pode editar
    cadastros existentes (a view exige 'eh_admin').
    """
    instituicao = get_instituicao_contexto(request)
    if not instituicao:
        return redirect('painel_adm')

    membro = get_object_or_404(Usuario, id=membro_id, instituicao=instituicao)

    if request.method == 'POST':
        membro.first_name = request.POST.get('nome')
        membro.email = request.POST.get('email')
        membro.username = request.POST.get('email')
        membro.perfil = request.POST.get('perfil')
        membro.profissao = request.POST.get('profissao')

        nova_senha = request.POST.get('senha')
        if nova_senha:
            membro.set_password(nova_senha)

        try:
            membro.save()
            messages.success(request, 'Dados do usuário atualizados com sucesso!')
        except Exception as e:
            messages.error(request, 'Erro ao atualizar: verifique se o e-mail já está em uso.')

    return redirect('gerenciar_equipe')

@login_required
@user_passes_test(eh_admin, login_url='dashboard')
def painel_adm(request):
    # Sempre que o ADM está na tela de "Unidades de Saúde", ele não está
    # mais gerenciando nenhuma unidade específica.
    request.session.pop('instituicao_ativa_id', None)

    if request.method == 'POST':
        nome_inst = request.POST.get('nome_inst')
        cnpj = request.POST.get('cnpj')
        telefone = request.POST.get('telefone')
        nome_coord = request.POST.get('nome_coord')
        email_coord = request.POST.get('email_coord')
        senha_coord = request.POST.get('senha_coord')

        try:
            nova_inst = Instituicao.objects.create(nome=nome_inst, cnpj=cnpj, telefone=telefone)
            
            # Forçando a criação correta do perfil do Coordenador
            coord = Usuario.objects.create_user(username=email_coord, email=email_coord, password=senha_coord)
            coord.first_name = nome_coord
            coord.perfil = 'COORDENADOR'
            coord.instituicao = nova_inst
            coord.primeiro_acesso = True
            coord.save()
            
            messages.success(request, 'Clínica e Coordenador cadastrados com sucesso!')
        except Exception as e:
            messages.error(request, f'Erro ao cadastrar: verifique se o e-mail ou CNPJ já existem.')
        
        return redirect('painel_adm')

    instituicoes = Instituicao.objects.all().order_by('-criado_em')
    return render(request, 'usuarios/painel_adm.html', {'instituicoes': instituicoes})