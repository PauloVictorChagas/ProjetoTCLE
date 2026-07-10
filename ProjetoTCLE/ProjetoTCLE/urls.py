from django.contrib import admin
from django.urls import path
from django.contrib.auth.views import LoginView, LogoutView
from usuarios import views
from pacientes import views as pacientes_views

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # Rota para a nossa tela de login
    path('login/', LoginView.as_view(template_name='usuarios/login.html'), name='login'),
    
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
    
    # Rota de teste weasyprint
    path('teste-pdf/', pacientes_views.teste_pdf, name='teste_pdf'),
    
    # Rota para tela da Biblioteca de Templates do TCLE
    path('biblioteca/', pacientes_views.biblioteca_tcle, name='biblioteca'),

    # Nova rota para a Troca de Senha
    path('trocar-senha/', views.trocar_senha, name='trocar_senha'),
    
    # Rota da Equipe para o Coordenador
    path('equipe/', views.gerenciar_equipe, name='gerenciar_equipe'),
    
    # Rota da Equipe para o Administrador (Leva o ID da clínica no clique do card)
    path('equipe/<int:id_instituicao>/', views.gerenciar_equipe, name='gerenciar_equipe_inst'),
]