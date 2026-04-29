# urls.py principal

from django.contrib import admin
from django.urls import path
from django.contrib.auth.views import LoginView

urlpatterns = [
    path('admin/', admin.site.urls),
    # Rota para a nossa tela de login
    path('login/', LoginView.as_view(template_name='usuarios/login.html'), name='login'),
]