from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.views import LoginView
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render

from pacientes.models import CategoriaTemplate, DocumentoEmitido, Paciente, TemplateTCLE

from . import throttle
from .forms import FormularioLogin
from .models import Instituicao, Usuario
from .utils import eh_admin_geral, get_instituicao_contexto, senha_pendente, validar_senha
from .validators import cnpj_valido, formatar_cnpj, limpar_texto

# Perfis que o Administrador pode atribuir a membros de uma unidade.
# (O Administrador Geral é criado só por `createsuperuser`/`/admin/`.)
PERFIS_ATRIBUIVEIS = {'COORDENADOR', 'PADRAO'}


def eh_admin(user):
    return eh_admin_geral(user)


class LoginSeguroView(LoginView):
    """Login com limite de tentativas; responde 429 quando o bloqueio é acionado."""
    template_name = 'usuarios/login.html'
    authentication_form = FormularioLogin

    def form_invalid(self, form):
        resposta = super().form_invalid(form)
        if 'bloqueado' in [e.code for e in form.non_field_errors().as_data()]:
            resposta.status_code = 429
        return resposta


# ---------------------------------------------------------------------------
# Validações compartilhadas de cadastro de usuário
# ---------------------------------------------------------------------------
def _email_em_uso(email, excluir_pk=None):
    consulta = Usuario.objects.filter(Q(email__iexact=email) | Q(username__iexact=email))
    if excluir_pk:
        consulta = consulta.exclude(pk=excluir_pk)
    return consulta.exists()


def _validar_dados_usuario(nome, email, profissao, excluir_pk=None):
    """Devolve (dados_limpos, lista_de_erros)."""
    nome = limpar_texto(nome)
    email = limpar_texto(email).lower()
    profissao = limpar_texto(profissao)
    erros = []

    if not nome:
        erros.append('Informe o nome do usuário.')
    elif len(nome) > 150:
        erros.append('O nome deve ter no máximo 150 caracteres.')

    try:
        if len(email) > 150:
            raise ValidationError('e-mail longo demais')
        validate_email(email)
    except ValidationError:
        erros.append('Informe um e-mail válido (até 150 caracteres).')
    else:
        if _email_em_uso(email, excluir_pk):
            erros.append('Este e-mail já está em uso no sistema.')

    if len(profissao) > 100:
        erros.append('A profissão deve ter no máximo 100 caracteres.')

    return {'nome': nome, 'email': email, 'profissao': profissao}, erros


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
    # A troca obrigatória da senha inicial é imposta pelo
    # TrocaSenhaObrigatoriaMiddleware, para todas as rotas do sistema.
    instituicao = get_instituicao_contexto(request)

    # O Dashboard é sempre o de UMA unidade. O Administrador Geral que ainda não
    # entrou em nenhuma unidade não tem Dashboard: ele começa (e volta) na tela
    # de gerenciamento/seleção de unidades.
    if eh_admin_geral(request.user) and not instituicao:
        return redirect('painel_adm')

    contexto = {
        'total_tcles': 0,
        'total_pacientes': 0,
        'total_assinados': 0,
        'total_pendentes': 0,
        'documentos_recentes': [],
        'total_templates': 0,
        'categorias_templates': [],
    }

    if instituicao:
        documentos = DocumentoEmitido.objects.filter(instituicao=instituicao)
        contexto['total_tcles'] = documentos.count()
        contexto['total_pacientes'] = Paciente.objects.filter(instituicao=instituicao).count()
        contexto['total_assinados'] = documentos.filter(status='ASSINADO').count()
        contexto['total_pendentes'] = documentos.filter(status='PENDENTE').count()
        contexto['documentos_recentes'] = documentos.select_related(
            'paciente', 'template_origem', 'template_origem__categoria'
        ).order_by('-data_emissao')[:5]

        templates = TemplateTCLE.objects.filter(instituicao=instituicao)
        contexto['total_templates'] = templates.count()
        contexto['categorias_templates'] = (
            CategoriaTemplate.objects.filter(instituicao=instituicao)
            .annotate(qtd_templates=Count('templates'))
            .filter(qtd_templates__gt=0)
            .order_by('-qtd_templates')
        )

    return render(request, 'usuarios/dashboard.html', contexto)


@login_required
def trocar_senha(request):
    user = request.user
    pendente = senha_pendente(user)  # primeiro acesso: ainda com a senha provisória

    if request.method == 'POST':
        senha_atual = request.POST.get('senha_atual') or ''
        senha1 = request.POST.get('senha1') or ''
        senha2 = request.POST.get('senha2') or ''

        if not pendente and throttle.bloqueado('trocasenha', request, str(user.pk), (5, 5)):
            messages.error(request, 'Muitas tentativas. Aguarde alguns minutos e tente novamente.')
        elif not pendente and not user.check_password(senha_atual):
            # Sem a senha atual, uma sessão sequestrada/esquecida aberta não
            # consegue trocar a senha e assumir a conta.
            throttle.registrar_falha('trocasenha', request, str(user.pk), (5, 5))
            messages.error(request, 'A senha atual está incorreta.')
        elif senha1 != senha2:
            messages.error(request, 'As senhas não coincidem.')
        elif user.check_password(senha1):
            messages.error(request, 'A nova senha deve ser diferente da senha atual.')
        else:
            erros = validar_senha(senha1, user)
            if erros:
                messages.error(request, ' '.join(erros))
            else:
                user.set_password(senha1)
                user.primeiro_acesso = False  # Tira a trava
                user.save(update_fields=['password', 'primeiro_acesso'])
                update_session_auth_hash(request, user)  # mantém esta sessão; encerra as demais
                throttle.limpar('trocasenha', request, str(user.pk), (5, 5))
                messages.success(request, 'Sua senha foi atualizada com sucesso!')
                return redirect('dashboard')

    return render(request, 'usuarios/trocar_senha.html', {'primeiro_acesso': pendente})


@login_required
def gerenciar_equipe(request, id_instituicao=None):
    is_admin = eh_admin_geral(request.user)
    is_coordenador = request.user.perfil == 'COORDENADOR'

    # Se vier um ID explícito na URL (link antigo), passamos a "entrar" nessa
    # unidade também, para manter a sessão consistente com a sidebar.
    if id_instituicao and is_admin:
        unidade_url = get_object_or_404(Instituicao, id=id_instituicao)
        request.session['instituicao_ativa_id'] = unidade_url.id

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

    def voltar():
        if id_instituicao:
            return redirect('gerenciar_equipe_inst', id_instituicao=instituicao.id)
        return redirect('gerenciar_equipe')

    # Lógica de salvar um novo membro (POST)
    if request.method == 'POST':
        dados, erros = _validar_dados_usuario(
            request.POST.get('nome'), request.POST.get('email'), request.POST.get('profissao'))
        senha = request.POST.get('senha') or ''
        perfil = request.POST.get('perfil')

        # Trava de segurança no servidor: o Coordenador só pode cadastrar
        # Usuário Padrão, não importa o que tenha vindo no formulário.
        if not is_admin:
            perfil = 'PADRAO'
        elif perfil not in PERFIS_ATRIBUIVEIS:
            erros.append('Perfil inválido.')

        if not erros:
            # A senha provisória também precisa cumprir a política de senhas.
            erros += validar_senha(senha, Usuario(username=dados['email'], email=dados['email'],
                                                  first_name=dados['nome']))
        if erros:
            messages.error(request, ' '.join(erros))
            return voltar()

        try:
            with transaction.atomic():
                novo_user = Usuario.objects.create_user(
                    username=dados['email'], email=dados['email'], password=senha,
                    first_name=dados['nome'], perfil=perfil, profissao=dados['profissao'] or None,
                    instituicao=instituicao, primeiro_acesso=True,
                )
            messages.success(request, 'Usuário cadastrado com sucesso!')
        except IntegrityError:
            messages.error(request, 'Erro: Este e-mail já está em uso no sistema.')
        return voltar()

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

    if membro.is_superuser or membro.perfil == 'ADM':
        messages.error(request, 'Este usuário não pode ser editado por aqui.')
        return redirect('gerenciar_equipe')

    if request.method == 'POST':
        dados, erros = _validar_dados_usuario(
            request.POST.get('nome'), request.POST.get('email'), request.POST.get('profissao'),
            excluir_pk=membro.pk)
        perfil = request.POST.get('perfil')
        if perfil not in PERFIS_ATRIBUIVEIS:
            erros.append('Perfil inválido.')

        nova_senha = request.POST.get('senha') or ''
        if nova_senha and not erros:
            erros += validar_senha(nova_senha, Usuario(username=dados['email'], email=dados['email'],
                                                       first_name=dados['nome']))
        if erros:
            messages.error(request, ' '.join(erros))
            return redirect('gerenciar_equipe')

        membro.first_name = dados['nome']
        membro.email = dados['email']
        membro.username = dados['email']
        membro.perfil = perfil
        membro.profissao = dados['profissao'] or None
        if nova_senha:
            membro.set_password(nova_senha)
            # Quem redefine a senha a conhece: o usuário precisa trocá-la no
            # próximo acesso (e as sessões antigas dele deixam de valer).
            membro.primeiro_acesso = True

        try:
            with transaction.atomic():
                membro.save()
            messages.success(request, 'Dados do usuário atualizados com sucesso!')
        except IntegrityError:
            messages.error(request, 'Erro ao atualizar: verifique se o e-mail já está em uso.')

    return redirect('gerenciar_equipe')


@login_required
@user_passes_test(eh_admin, login_url='dashboard')
def painel_adm(request):
    # Sempre que o ADM está na tela de "Unidades de Saúde", ele não está
    # mais gerenciando nenhuma unidade específica.
    request.session.pop('instituicao_ativa_id', None)

    if request.method == 'POST':
        nome_inst = limpar_texto(request.POST.get('nome_inst'))
        cnpj = limpar_texto(request.POST.get('cnpj'))
        telefone = limpar_texto(request.POST.get('telefone'))
        senha_coord = request.POST.get('senha_coord') or ''
        dados, erros = _validar_dados_usuario(
            request.POST.get('nome_coord'), request.POST.get('email_coord'), '')

        if not nome_inst:
            erros.append('Informe o nome da unidade.')
        elif len(nome_inst) > 255:
            erros.append('O nome da unidade deve ter no máximo 255 caracteres.')
        if len(telefone) > 20:
            erros.append('O telefone deve ter no máximo 20 caracteres.')

        if cnpj:
            if not cnpj_valido(cnpj):
                erros.append('CNPJ inválido.')
            else:
                cnpj = formatar_cnpj(cnpj)
                if Instituicao.objects.filter(cnpj=cnpj).exists():
                    erros.append('Já existe uma unidade com este CNPJ.')

        # Valida a senha ANTES de criar a unidade, para não deixar unidade sem coordenador.
        if not erros:
            erros += validar_senha(senha_coord, Usuario(username=dados['email'], email=dados['email'],
                                                        first_name=dados['nome']))
        if erros:
            messages.error(request, ' '.join(erros))
            return redirect('painel_adm')

        try:
            # Tudo ou nada: se o coordenador não puder ser criado, a unidade também não é.
            with transaction.atomic():
                nova_inst = Instituicao.objects.create(
                    nome=nome_inst, cnpj=cnpj or None, telefone=telefone or None)
                Usuario.objects.create_user(
                    username=dados['email'], email=dados['email'], password=senha_coord,
                    first_name=dados['nome'], perfil='COORDENADOR', instituicao=nova_inst,
                    primeiro_acesso=True,
                )
            messages.success(request, 'Clínica e Coordenador cadastrados com sucesso!')
        except IntegrityError:
            messages.error(request, 'Erro ao cadastrar: verifique se o e-mail ou CNPJ já existem.')

        return redirect('painel_adm')

    instituicoes = Instituicao.objects.all().order_by('-criado_em')
    return render(request, 'usuarios/painel_adm.html', {'instituicoes': instituicoes})
