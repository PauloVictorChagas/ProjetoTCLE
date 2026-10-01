"""
Testes do app `usuarios`: autenticação, senhas, sessões, controle de acesso
(perfis) e isolamento entre unidades de saúde.

Execute com:  python manage.py test
"""
import os
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.contrib.messages import get_messages
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from .models import Instituicao, Usuario
from .validators import erros_politica_senha, tem_numeros_em_sequencia

SENHA_OK = 'Sup3r#Forte'          # atende à política, sem sequências numéricas
SENHA_NOVA = 'Nov@Senha7x'


def mensagens(response):
    return [str(m) for m in get_messages(response.wsgi_request)]


class BaseTestCase(TestCase):
    """Cria duas unidades (A e B) com usuários de cada perfil."""

    @classmethod
    def setUpTestData(cls):
        cls.inst_a = Instituicao.objects.create(nome='Unidade A', cnpj='11.222.333/0001-81')
        cls.inst_b = Instituicao.objects.create(nome='Unidade B', cnpj='22.333.444/0001-81')
        cls.admin = cls._novo('admin@ex.com', 'ADM', None)
        cls.coord_a = cls._novo('coord.a@ex.com', 'COORDENADOR', cls.inst_a)
        cls.padrao_a = cls._novo('padrao.a@ex.com', 'PADRAO', cls.inst_a)
        cls.coord_b = cls._novo('coord.b@ex.com', 'COORDENADOR', cls.inst_b)
        cls.padrao_b = cls._novo('padrao.b@ex.com', 'PADRAO', cls.inst_b)

    @staticmethod
    def _novo(email, perfil, instituicao, senha=SENHA_OK, primeiro_acesso=False):
        user = Usuario(username=email, email=email, perfil=perfil, instituicao=instituicao,
                       first_name=email.split('@')[0], primeiro_acesso=primeiro_acesso)
        user.set_password(senha)
        user.save()
        return user

    def setUp(self):
        cache.clear()  # zera o contador de tentativas de login

    def logar_como(self, user, unidade=None):
        self.client.force_login(user)
        if unidade is not None:
            session = self.client.session
            session['instituicao_ativa_id'] = unidade.id
            session.save()


# ---------------------------------------------------------------------------
# Política de senhas
# ---------------------------------------------------------------------------
class PoliticaSenhaTests(TestCase):
    def test_senha_valida(self):
        self.assertEqual(erros_politica_senha(SENHA_OK), [])

    def test_regras_violadas(self):
        casos = {
            'Ab1#': 'mínimo',                 # curta
            '12345678#': 'letra',             # sem letra
            'Abcdefgh#': 'número',            # sem número
            'Abcdefg1': 'especial',           # sem especial
            'Abc#1234x': 'sequência',         # 1234
            'Abc#9876x': 'sequência',         # decrescente
        }
        for senha, trecho in casos.items():
            with self.subTest(senha=senha):
                erros = ' '.join(erros_politica_senha(senha))
                self.assertIn(trecho, erros)

    def test_sequencia_numerica(self):
        self.assertTrue(tem_numeros_em_sequencia('a12b'))
        self.assertTrue(tem_numeros_em_sequencia('a21b'))
        self.assertFalse(tem_numeros_em_sequencia('a1b2'))
        self.assertFalse(tem_numeros_em_sequencia('a13b'))


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------
class LoginTests(BaseTestCase):
    def _login(self, email, senha):
        return self.client.post(reverse('login'), {'username': email, 'password': senha})

    def _logado(self):
        return '_auth_user_id' in self.client.session

    def test_login_por_email_ignora_maiusculas(self):
        self._login('PADRAO.A@EX.COM', SENHA_OK)
        self.assertTrue(self._logado())

    def test_senha_errada_nao_loga(self):
        self._login('padrao.a@ex.com', 'errada')
        self.assertFalse(self._logado())

    def test_usuario_inativo_nao_loga(self):
        Usuario.objects.filter(pk=self.padrao_a.pk).update(is_active=False)
        self._login('padrao.a@ex.com', SENHA_OK)
        self.assertFalse(self._logado())

    def _duplicado(self, senha):
        # E-mail não é único no modelo padrão (ex.: cadastro feito pelo /admin).
        outro = Usuario(username='outro-login', email='padrao.a@ex.com', instituicao=self.inst_b)
        outro.set_password(senha)
        outro.save()
        return outro

    def test_email_duplicado_autentica_quem_tem_a_senha(self):
        # Antes: o backend escolhia sempre o "primeiro" cadastro e o segundo nunca conseguia entrar.
        outro = self._duplicado('Out@r0Senha')
        self._login('padrao.a@ex.com', 'Out@r0Senha')
        self.assertEqual(self.client.session.get('_auth_user_id'), str(outro.pk))

    def test_email_duplicado_com_mesma_senha_resolve_pelo_username_unico(self):
        # Por e-mail a conta é ambígua (o backend de e-mail recusa); quem responde é o
        # backend padrão, pelo username (único): entra a conta cujo username é o e-mail,
        # nunca "o primeiro da lista".
        outro = self._duplicado(SENHA_OK)
        self._login('padrao.a@ex.com', SENHA_OK)
        self.assertEqual(self.client.session.get('_auth_user_id'), str(self.padrao_a.pk))
        self.assertNotEqual(self.client.session.get('_auth_user_id'), str(outro.pk))

        from .backends import EmailBackend
        self.assertIsNone(EmailBackend().authenticate(None, 'padrao.a@ex.com', SENHA_OK))

    def test_bloqueio_apos_tentativas_falhas(self):
        for _ in range(6):
            self._login('padrao.a@ex.com', 'errada')
        # Mesmo com a senha correta, o login fica bloqueado durante o intervalo
        resp = self._login('padrao.a@ex.com', SENHA_OK)
        self.assertFalse(self._logado(), 'Login deveria estar temporariamente bloqueado')
        self.assertContains(resp, 'Muitas tentativas', status_code=429)

    def test_bloqueio_nao_afeta_outra_conta(self):
        for _ in range(6):
            self._login('padrao.a@ex.com', 'errada')
        self._login('padrao.b@ex.com', SENHA_OK)
        self.assertTrue(self._logado())

    def test_login_bem_sucedido_zera_contador(self):
        for _ in range(3):
            self._login('padrao.a@ex.com', 'errada')
        self._login('padrao.a@ex.com', SENHA_OK)
        self.assertTrue(self._logado())
        self.client.logout()
        for _ in range(3):
            self._login('padrao.a@ex.com', 'errada')
        self._login('padrao.a@ex.com', SENHA_OK)
        self.assertTrue(self._logado())

    def test_redirecionamento_externo_e_ignorado(self):
        resp = self.client.post(reverse('login') + '?next=https://evil.example/',
                                {'username': 'padrao.a@ex.com', 'password': SENHA_OK})
        self.assertRedirects(resp, '/', fetch_redirect_response=False)

    def test_logout_exige_post(self):
        self.logar_como(self.padrao_a)
        self.client.get(reverse('logout'))
        self.assertTrue(self._logado())
        self.client.post(reverse('logout'))
        self.assertFalse(self._logado())

    def test_sessao_e_renovada_no_login(self):
        self.client.get(reverse('login'))
        antes = self.client.session.session_key
        self._login('padrao.a@ex.com', SENHA_OK)
        self.assertNotEqual(antes, self.client.session.session_key)

    def test_unidade_inativa_bloqueia_usuarios(self):
        Instituicao.objects.filter(pk=self.inst_a.pk).update(ativo=False)
        self.logar_como(self.padrao_a)
        resp = self.client.get(reverse('dashboard'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse('login'), resp.url)
        self.assertFalse(self._logado())


# ---------------------------------------------------------------------------
# Troca de senha / primeiro acesso
# ---------------------------------------------------------------------------
class TrocaSenhaTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.novo = self._novo('novo@ex.com', 'PADRAO', self.inst_a, senha='Prov@Sen6x', primeiro_acesso=True)

    def test_primeiro_acesso_bloqueia_todo_o_sistema(self):
        self.client.force_login(self.novo)
        for nome in ('dashboard', 'pacientes', 'biblioteca', 'historico', 'gerar_tcle', 'gerenciar_equipe'):
            with self.subTest(rota=nome):
                resp = self.client.get(reverse(nome))
                self.assertRedirects(resp, reverse('trocar_senha'), fetch_redirect_response=False)

    def test_primeiro_acesso_bloqueia_post_direto(self):
        self.client.force_login(self.novo)
        resp = self.client.post(reverse('pacientes'), {'nome': 'X'})
        self.assertRedirects(resp, reverse('trocar_senha'), fetch_redirect_response=False)

    def test_troca_valida_libera_o_sistema(self):
        self.client.force_login(self.novo)
        resp = self.client.post(reverse('trocar_senha'), {'senha1': SENHA_NOVA, 'senha2': SENHA_NOVA})
        self.assertRedirects(resp, reverse('dashboard'), fetch_redirect_response=False)
        self.novo.refresh_from_db()
        self.assertFalse(self.novo.primeiro_acesso)
        self.assertTrue(self.novo.check_password(SENHA_NOVA))
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 200)

    def test_nova_senha_nao_pode_ser_a_provisoria(self):
        self.client.force_login(self.novo)
        self.client.post(reverse('trocar_senha'), {'senha1': 'Prov@Sen6x', 'senha2': 'Prov@Sen6x'})
        self.novo.refresh_from_db()
        self.assertTrue(self.novo.primeiro_acesso, 'A senha provisória não pode ser reutilizada')

    def test_senhas_diferentes_sao_recusadas(self):
        self.client.force_login(self.novo)
        self.client.post(reverse('trocar_senha'), {'senha1': SENHA_NOVA, 'senha2': SENHA_NOVA + 'x'})
        self.novo.refresh_from_db()
        self.assertTrue(self.novo.primeiro_acesso)

    def test_senha_comum_e_recusada(self):
        # 'P@ssw0rd' cumpre a política própria, mas consta na lista de senhas comuns.
        self.client.force_login(self.novo)
        self.client.post(reverse('trocar_senha'), {'senha1': 'P@ssw0rd', 'senha2': 'P@ssw0rd'})
        self.novo.refresh_from_db()
        self.assertTrue(self.novo.primeiro_acesso, 'Senhas comuns deveriam ser recusadas')

    def test_senha_fora_da_politica_e_recusada(self):
        self.client.force_login(self.novo)
        self.client.post(reverse('trocar_senha'), {'senha1': 'abc12345', 'senha2': 'abc12345'})
        self.novo.refresh_from_db()
        self.assertTrue(self.novo.primeiro_acesso)

    def test_troca_voluntaria_exige_senha_atual(self):
        self.client.force_login(self.padrao_a)
        self.client.post(reverse('trocar_senha'), {'senha1': SENHA_NOVA, 'senha2': SENHA_NOVA})
        self.padrao_a.refresh_from_db()
        self.assertTrue(self.padrao_a.check_password(SENHA_OK), 'Sem a senha atual a troca deve falhar')

        self.client.post(reverse('trocar_senha'),
                         {'senha_atual': 'errada', 'senha1': SENHA_NOVA, 'senha2': SENHA_NOVA})
        self.padrao_a.refresh_from_db()
        self.assertTrue(self.padrao_a.check_password(SENHA_OK))

        self.client.post(reverse('trocar_senha'),
                         {'senha_atual': SENHA_OK, 'senha1': SENHA_NOVA, 'senha2': SENHA_NOVA})
        self.padrao_a.refresh_from_db()
        self.assertTrue(self.padrao_a.check_password(SENHA_NOVA))

    def test_troca_mantem_a_sessao_e_invalida_as_outras(self):
        outro_navegador = self.client_class()
        outro_navegador.force_login(self.padrao_a)
        self.client.force_login(self.padrao_a)
        self.client.post(reverse('trocar_senha'),
                         {'senha_atual': SENHA_OK, 'senha1': SENHA_NOVA, 'senha2': SENHA_NOVA})
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 200)
        self.assertEqual(outro_navegador.get(reverse('dashboard')).status_code, 302)


# ---------------------------------------------------------------------------
# Controle de acesso e gestão de equipe
# ---------------------------------------------------------------------------
class ControleDeAcessoTests(BaseTestCase):
    def _cadastrar(self, **extra):
        dados = {'nome': 'Fulano', 'email': 'fulano@ex.com', 'perfil': 'PADRAO',
                 'profissao': 'Enfermeiro', 'senha': 'Prov@Sen6x'}
        dados.update(extra)
        return self.client.post(reverse('gerenciar_equipe'), dados)

    def test_rotas_exigem_login(self):
        for nome in ('dashboard', 'painel_adm', 'gerenciar_equipe', 'pacientes', 'biblioteca',
                     'historico', 'gerar_tcle'):
            with self.subTest(rota=nome):
                resp = self.client.get(reverse(nome))
                self.assertEqual(resp.status_code, 302)
                self.assertIn(reverse('login'), resp.url)

    def test_usuario_padrao_nao_gerencia_equipe(self):
        self.logar_como(self.padrao_a)
        resp = self._cadastrar()
        self.assertRedirects(resp, reverse('dashboard'), fetch_redirect_response=False)
        self.assertFalse(Usuario.objects.filter(email='fulano@ex.com').exists())

    def test_usuario_padrao_e_coordenador_nao_acessam_painel_adm(self):
        for user in (self.padrao_a, self.coord_a):
            with self.subTest(user=user.email):
                self.logar_como(user)
                resp = self.client.post(reverse('painel_adm'), {
                    'nome_inst': 'Nova', 'cnpj': '', 'telefone': '', 'nome_coord': 'X',
                    'email_coord': 'x@ex.com', 'senha_coord': 'Prov@Sen6x'})
                self.assertEqual(resp.status_code, 302)
                self.assertTrue(resp.url.startswith(reverse('dashboard')))
                self.assertFalse(Instituicao.objects.filter(nome='Nova').exists())

    def test_coordenador_so_cria_usuario_padrao(self):
        self.logar_como(self.coord_a)
        self._cadastrar(perfil='ADM')
        novo = Usuario.objects.get(email='fulano@ex.com')
        self.assertEqual(novo.perfil, 'PADRAO')
        self.assertEqual(novo.instituicao, self.inst_a)
        self.assertTrue(novo.primeiro_acesso)

    def test_coordenador_ignora_id_de_outra_unidade_na_url(self):
        self.logar_como(self.coord_a)
        self.client.post(reverse('gerenciar_equipe_inst', args=[self.inst_b.id]), {
            'nome': 'Intruso', 'email': 'intruso@ex.com', 'perfil': 'PADRAO', 'senha': 'Prov@Sen6x'})
        self.assertFalse(Usuario.objects.filter(email='intruso@ex.com', instituicao=self.inst_b).exists())
        resp = self.client.get(reverse('gerenciar_equipe_inst', args=[self.inst_b.id]))
        self.assertEqual(resp.context['instituicao_atual'], self.inst_a)

    def test_coordenador_nao_edita_membros(self):
        self.logar_como(self.coord_a)
        resp = self.client.post(reverse('editar_membro_equipe', args=[self.padrao_a.id]),
                                {'nome': 'Hack', 'email': 'hack@ex.com', 'perfil': 'COORDENADOR'})
        self.assertEqual(resp.status_code, 302)
        self.padrao_a.refresh_from_db()
        self.assertEqual(self.padrao_a.perfil, 'PADRAO')
        self.assertEqual(self.padrao_a.email, 'padrao.a@ex.com')

    def test_admin_nao_edita_membro_de_outra_unidade(self):
        self.logar_como(self.admin, unidade=self.inst_a)
        resp = self.client.post(reverse('editar_membro_equipe', args=[self.padrao_b.id]),
                                {'nome': 'X', 'email': 'x@ex.com', 'perfil': 'PADRAO'})
        self.assertEqual(resp.status_code, 404)

    def test_admin_nao_cria_perfil_invalido_nem_adm(self):
        self.logar_como(self.admin, unidade=self.inst_a)
        for i, perfil in enumerate(('ADM', 'SUPERUSER', '')):
            with self.subTest(perfil=perfil):
                self._cadastrar(email=f'p{i}@ex.com', perfil=perfil)
                self.assertFalse(Usuario.objects.filter(email=f'p{i}@ex.com').exists())

    def test_admin_nao_promove_membro_a_adm_na_edicao(self):
        self.logar_como(self.admin, unidade=self.inst_a)
        self.client.post(reverse('editar_membro_equipe', args=[self.padrao_a.id]), {
            'nome': 'Padrao', 'email': 'padrao.a@ex.com', 'perfil': 'ADM', 'profissao': ''})
        self.padrao_a.refresh_from_db()
        self.assertEqual(self.padrao_a.perfil, 'PADRAO')

    def test_email_invalido_e_recusado(self):
        self.logar_como(self.coord_a)
        self._cadastrar(email='isto-nao-e-email')
        self.assertFalse(Usuario.objects.filter(username='isto-nao-e-email').exists())

    def test_email_duplicado_ignora_maiusculas(self):
        self.logar_como(self.coord_a)
        self._cadastrar(email='PADRAO.A@EX.COM')
        self.assertEqual(Usuario.objects.filter(email__iexact='padrao.a@ex.com').count(), 1)

    def test_email_e_normalizado_em_minusculas(self):
        self.logar_como(self.coord_a)
        self._cadastrar(email='Novo.Nome@Ex.Com')
        self.assertTrue(Usuario.objects.filter(username='novo.nome@ex.com').exists())

    def test_nome_obrigatorio(self):
        self.logar_como(self.coord_a)
        self._cadastrar(nome='   ')
        self.assertFalse(Usuario.objects.filter(email='fulano@ex.com').exists())

    def test_senha_provisoria_fora_da_politica_e_recusada(self):
        self.logar_como(self.coord_a)
        self._cadastrar(senha='P@ssw0rd')  # comum
        self.assertFalse(Usuario.objects.filter(email='fulano@ex.com').exists())

    def test_reset_de_senha_pelo_admin_exige_nova_troca(self):
        self.logar_como(self.admin, unidade=self.inst_a)
        self.client.post(reverse('editar_membro_equipe', args=[self.padrao_a.id]), {
            'nome': 'Padrao', 'email': 'padrao.a@ex.com', 'perfil': 'PADRAO',
            'profissao': '', 'senha': 'Res3t#Prov'})
        self.padrao_a.refresh_from_db()
        self.assertTrue(self.padrao_a.check_password('Res3t#Prov'))
        self.assertTrue(self.padrao_a.primeiro_acesso, 'Senha redefinida por outra pessoa deve ser trocada no próximo acesso')

    def test_edicao_com_email_duplicado_nao_altera(self):
        self.logar_como(self.admin, unidade=self.inst_a)
        self.client.post(reverse('editar_membro_equipe', args=[self.padrao_a.id]), {
            'nome': 'Padrao', 'email': 'COORD.A@ex.com', 'perfil': 'PADRAO', 'profissao': ''})
        self.padrao_a.refresh_from_db()
        self.assertEqual(self.padrao_a.email, 'padrao.a@ex.com')

    def test_admin_nao_edita_superusuario(self):
        root = Usuario(username='root@ex.com', email='root@ex.com', is_superuser=True,
                       is_staff=True, instituicao=self.inst_a, perfil='PADRAO')
        root.set_password(SENHA_OK)
        root.save()
        self.logar_como(self.admin, unidade=self.inst_a)
        resp = self.client.post(reverse('editar_membro_equipe', args=[root.id]), {
            'nome': 'Root', 'email': 'root@ex.com', 'perfil': 'PADRAO', 'senha': 'Res3t#Prov'})
        root.refresh_from_db()
        self.assertTrue(root.check_password(SENHA_OK))
        self.assertEqual(resp.status_code, 302)

    def test_entrar_em_unidade_inexistente(self):
        self.logar_como(self.admin)
        resp = self.client.get(reverse('entrar_unidade', args=[99999]))
        self.assertEqual(resp.status_code, 404)
        resp = self.client.get(reverse('gerenciar_equipe_inst', args=[99999]))
        self.assertIn(resp.status_code, (302, 404))
        self.assertNotIn('instituicao_ativa_id', self.client.session)

    def test_nao_admin_nao_entra_em_unidade(self):
        self.logar_como(self.coord_a)
        self.client.get(reverse('entrar_unidade', args=[self.inst_b.id]))
        self.assertNotIn('instituicao_ativa_id', self.client.session)

    def test_dashboard_so_conta_dados_da_propria_unidade(self):
        self.logar_como(self.coord_a)
        self.assertEqual(self.client.get(reverse('dashboard')).context['total_tcles'], 0)


# ---------------------------------------------------------------------------
# Painel do Administrador (cadastro de unidade + coordenador)
# ---------------------------------------------------------------------------
class PainelAdmTests(BaseTestCase):
    def _dados(self, **extra):
        dados = {'nome_inst': 'Unidade C', 'cnpj': '', 'telefone': '(75) 99999-0000',
                 'nome_coord': 'Coord C', 'email_coord': 'coord.c@ex.com', 'senha_coord': 'Prov@Sen6x'}
        dados.update(extra)
        return dados

    def setUp(self):
        super().setUp()
        self.logar_como(self.admin)

    def test_cadastro_completo(self):
        self.client.post(reverse('painel_adm'), self._dados())
        inst = Instituicao.objects.get(nome='Unidade C')
        coord = Usuario.objects.get(email='coord.c@ex.com')
        self.assertEqual(coord.perfil, 'COORDENADOR')
        self.assertEqual(coord.instituicao, inst)
        self.assertTrue(coord.primeiro_acesso)

    def test_email_duplicado_nao_deixa_unidade_orfa(self):
        self.client.post(reverse('painel_adm'), self._dados(email_coord='coord.a@ex.com'))
        self.assertFalse(Instituicao.objects.filter(nome='Unidade C').exists(),
                         'A unidade não deve ser criada se o coordenador não puder ser criado')

    def test_duas_unidades_sem_cnpj(self):
        self.client.post(reverse('painel_adm'), self._dados())
        self.client.post(reverse('painel_adm'), self._dados(nome_inst='Unidade D', email_coord='coord.d@ex.com'))
        self.assertTrue(Instituicao.objects.filter(nome='Unidade D').exists())
        self.assertEqual(Instituicao.objects.filter(cnpj__isnull=True).count(), 2)

    def test_cnpj_invalido_e_recusado(self):
        self.client.post(reverse('painel_adm'), self._dados(cnpj='11.111.111/1111-11'))
        self.assertFalse(Instituicao.objects.filter(nome='Unidade C').exists())

    def test_cnpj_valido_e_normalizado(self):
        self.client.post(reverse('painel_adm'), self._dados(cnpj='33000167000101'))  # CNPJ válido
        self.assertEqual(Instituicao.objects.get(nome='Unidade C').cnpj, '33.000.167/0001-01')

    def test_nome_da_unidade_obrigatorio(self):
        self.client.post(reverse('painel_adm'), self._dados(nome_inst='   '))
        self.assertFalse(Usuario.objects.filter(email='coord.c@ex.com').exists())

    def test_email_do_coordenador_invalido(self):
        self.client.post(reverse('painel_adm'), self._dados(email_coord='sem-arroba'))
        self.assertFalse(Instituicao.objects.filter(nome='Unidade C').exists())

    def test_senha_fora_da_politica(self):
        self.client.post(reverse('painel_adm'), self._dados(senha_coord='P@ssw0rd'))
        self.assertFalse(Instituicao.objects.filter(nome='Unidade C').exists())


# ---------------------------------------------------------------------------
# Cabeçalhos e configuração
# ---------------------------------------------------------------------------
class CabecalhosTests(BaseTestCase):
    def test_paginas_autenticadas_nao_ficam_em_cache(self):
        self.logar_como(self.coord_a)
        resp = self.client.get(reverse('dashboard'))
        self.assertIn('no-store', resp.headers.get('Cache-Control', ''))

    def test_cookies_de_sessao_e_csrf(self):
        self.assertTrue(settings.SESSION_COOKIE_HTTPONLY)
        self.assertEqual(settings.SESSION_COOKIE_SAMESITE, 'Lax')
        self.assertEqual(settings.CSRF_COOKIE_SAMESITE, 'Lax')
        self.assertTrue(settings.SESSION_EXPIRE_AT_BROWSER_CLOSE)
        self.assertLessEqual(settings.SESSION_COOKIE_AGE, 8 * 3600)

    def test_segredos_nao_estao_no_codigo(self):
        self.assertFalse(settings.SECRET_KEY.startswith('django-insecure-'))
        fonte = (Path(settings.BASE_DIR) / 'ProjetoTCLE' / 'settings.py').read_text(encoding='utf-8')
        self.assertNotIn('TCLE628026', fonte)
        self.assertNotIn('django-insecure-ogdxr', fonte)

    def test_teste_pdf_foi_removido(self):
        self.logar_como(self.padrao_a)
        self.client.raise_request_exception = False
        self.assertEqual(self.client.get('/teste-pdf/').status_code, 404)


class ConfiguracaoEmProducaoTests(TestCase):
    """Importa o settings em um subprocesso, com variáveis de ambiente controladas."""

    def _importar(self, **env):
        base = {k: v for k, v in os.environ.items()
                if not k.startswith(('DJANGO_', 'DB_'))}
        base.update(env)
        base['DB_ENGINE'] = 'sqlite'
        codigo = ('import os; os.environ["DJANGO_SETTINGS_MODULE"]="ProjetoTCLE.settings"; '
                  'from django.conf import settings; settings.SECRET_KEY; '
                  'print(settings.DEBUG, settings.SESSION_COOKIE_SECURE, settings.CSRF_COOKIE_SECURE, '
                  'settings.SECURE_SSL_REDIRECT, settings.SECURE_HSTS_SECONDS, settings.ALLOWED_HOSTS)')
        return subprocess.run([sys.executable, '-c', codigo], cwd=settings.BASE_DIR, env=base,
                              capture_output=True, text=True, timeout=60)

    def test_sem_secret_key_fora_do_debug_falha(self):
        r = self._importar(DJANGO_DEBUG='False')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('DJANGO_SECRET_KEY', r.stderr)

    def test_producao_ativa_cookies_seguros_e_hsts(self):
        r = self._importar(DJANGO_DEBUG='False', DJANGO_SECRET_KEY='x' * 60,
                           DJANGO_ALLOWED_HOSTS='tcle.exemplo.com')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("False True True True", r.stdout)
        self.assertIn("['tcle.exemplo.com']", r.stdout)
        self.assertNotIn(' 0 [', r.stdout)  # HSTS habilitado

    def test_debug_padrao_e_desligado(self):
        r = self._importar(DJANGO_SECRET_KEY='x' * 60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.startswith('False'))
