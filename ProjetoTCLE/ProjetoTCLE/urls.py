from django.conf import settings
from django.contrib import admin
from django.urls import path
from django.contrib.auth.views import LogoutView
from usuarios import views
from usuarios.forms import FormularioLoginAdmin
from pacientes import views as pacientes_views

# O /admin/ também passa pelo limite de tentativas de login
admin.site.login_form = FormularioLoginAdmin

urlpatterns = [
    path(settings.ADMIN_URL, admin.site.urls),
    
    # Rota para a nossa tela de login
    path('login/', views.LoginSeguroView.as_view(), name='login'),
    
    # Rota de Logout (Sair) - O next_page diz para onde ir depois de sair
    path('logout/', LogoutView.as_view(next_page='login'), name='logout'),
    
    # Rota do Dashboard (Página Inicial será a barra vazia '')
    path('', views.dashboard, name='dashboard'),
    
    # Rota para o Painel do Administrador (Gestão de Instituições)
    path('painel-adm/', views.painel_adm, name='painel_adm'),
    
    # Rota para tela de Gerenciar usuarios (Agora focada no Coordenador)
    path('equipe/', views.gerenciar_equipe, name='gerenciar_equipe'),
    
    # Rota para tela de Cadastro de pacientes
    path('pacientes/', pacientes_views.gerenciar_pacientes, name='pacientes'),
    
    # Rota para tela da Biblioteca de Templates do TCLE
    path('biblioteca/', pacientes_views.biblioteca_tcle, name='biblioteca'),

    # Rota para tela de Gerar TCLE (wizard de Seleção / Revisão / Assinatura)
    path('gerar-tcle/', pacientes_views.gerar_tcle, name='gerar_tcle'),

    # Rotas para o Histórico de TCLEs emitidos e download do PDF
    path('historico/', pacientes_views.historico_tcle, name='historico'),
    path('documentos/<int:documento_id>/pdf/', pacientes_views.documento_pdf, name='documento_pdf'),
    path('documentos/<int:documento_id>/enviar-email/', pacientes_views.documento_enviar_email, name='documento_enviar_email'),

    # Rotas de Categorias de TCLE (Administrador e Coordenador)
    path('categorias/nova/', pacientes_views.criar_categoria, name='criar_categoria'),
    path('categorias/<int:categoria_id>/editar/', pacientes_views.editar_categoria, name='editar_categoria'),

    # Nova rota para a Troca de Senha
    path('trocar-senha/', views.trocar_senha, name='trocar_senha'),
    
    # Rota da Equipe para o Administrador (Leva o ID da clínica no clique do card)
    path('equipe/<int:id_instituicao>/', views.gerenciar_equipe, name='gerenciar_equipe_inst'),

    # Rota para o Administrador editar os dados de um membro já cadastrado
    path('equipe/membro/<int:membro_id>/editar/', views.editar_membro_equipe, name='editar_membro_equipe'),

    # O Administrador Geral clica no card de uma unidade e passa a "ser" o Coordenador dela
    path('unidade/<int:id_instituicao>/entrar/', views.entrar_unidade, name='entrar_unidade'),

    # O Administrador Geral encerra a gestão da unidade e volta para "Unidades de Saúde"
    path('unidade/sair/', views.sair_unidade, name='sair_unidade'),
]