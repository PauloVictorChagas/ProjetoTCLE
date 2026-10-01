"""
Testes do app `pacientes`: isolamento entre unidades, permissões, validação de
entradas, XSS/SSRF no documento assinado, PDF e envio de e-mail.

Execute com:  python manage.py test
"""
from unittest import mock

from django.core import mail
from django.test import override_settings
from django.urls import reverse

from usuarios.tests import BaseTestCase, mensagens

from .models import CategoriaTemplate, DocumentoEmitido, Paciente, TemplateTCLE
from .views import renderizar_corpo_documento

# PNG 1x1 válido, no formato enviado pelo canvas do navegador
PNG_B64 = ('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==')
ASSINATURA_OK = f'data:image/png;base64,{PNG_B64}'

CPF_VALIDO_1 = '529.982.247-25'
CPF_VALIDO_2 = '111.444.777-35'


class PacientesBase(BaseTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.cat_a = CategoriaTemplate.objects.create(instituicao=cls.inst_a, nome='Cirúrgico', texto_padrao='x')
        cls.cat_b = CategoriaTemplate.objects.create(instituicao=cls.inst_b, nome='Cirúrgico', texto_padrao='x')
        cls.tpl_a = TemplateTCLE.objects.create(instituicao=cls.inst_a, categoria=cls.cat_a, titulo='Modelo A',
                                                resumo='r', texto_base='Texto base A', criado_por=cls.coord_a)
        cls.tpl_b = TemplateTCLE.objects.create(instituicao=cls.inst_b, categoria=cls.cat_b, titulo='Modelo B',
                                                resumo='r', texto_base='Texto base B', criado_por=cls.coord_b)
        cls.pac_a = cls._paciente(cls.inst_a, 'Maria da Silva', CPF_VALIDO_1, cls.padrao_a)
        cls.pac_b = cls._paciente(cls.inst_b, 'José Souza', CPF_VALIDO_2, cls.padrao_b)
        cls.doc_a = cls._documento(cls.inst_a, cls.pac_a, cls.tpl_a, cls.padrao_a)
        cls.doc_b = cls._documento(cls.inst_b, cls.pac_b, cls.tpl_b, cls.padrao_b)

    @staticmethod
    def _paciente(inst, nome, cpf, user):
        return Paciente.objects.create(
            instituicao=inst, nome=nome, cpf=cpf, rg='12.345.678-9', data_nascimento='1990-05-17',
            telefone='(75) 99999-0000', email='paciente@ex.com', cep='44000-000', tipo_logradouro='Rua',
            logradouro='das Flores', numero='10', bairro='Centro', cidade='Feira', uf='BA', criado_por=user)

    @staticmethod
    def _documento(inst, paciente, template, user, **extra):
        dados = dict(instituicao=inst, paciente=paciente, template_origem=template, medico_emissor=user,
                     dados_preenchidos={}, texto_final='Eu, [assinatura_paciente], concordo.',
                     assinatura_paciente=ASSINATURA_OK, assinatura_profissional=ASSINATURA_OK, status='ASSINADO')
        dados.update(extra)
        return DocumentoEmitido.objects.create(**dados)

    def dados_paciente(self, **extra):
        dados = {'nome': 'Ana Paula Lima', 'cpf': '39053344705', 'rg': '1234567', 'data_nascimento': '1985-03-02',
                 'telefone': '(75) 98888-7777', 'email': 'ana@ex.com', 'cep': '44000-000',
                 'tipo_logradouro': 'Rua', 'logradouro': 'A', 'numero': '1', 'complemento': '',
                 'bairro': 'Centro', 'cidade': 'Feira de Santana', 'uf': 'BA'}
        dados.update(extra)
        return dados


# ---------------------------------------------------------------------------
# XSS / SSRF a partir da assinatura
# ---------------------------------------------------------------------------
class AssinaturaSegurancaTests(PacientesBase):
    PAYLOADS = [
        'x" onerror="alert(document.cookie)',
        '"><script>alert(1)</script>',
        'javascript:alert(1)',
        'file:///etc/passwd',
        'http://169.254.169.254/latest/meta-data/',
        'data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==',
        'data:image/svg+xml;base64,PHN2ZyBvbmxvYWQ9YWxlcnQoMSk+',
        f'{ASSINATURA_OK}" onload="x',
    ]

    def test_render_nao_injeta_atributos(self):
        for payload in self.PAYLOADS:
            with self.subTest(payload=payload):
                doc = self._documento(self.inst_a, self.pac_a, self.tpl_a, self.padrao_a,
                                      assinatura_paciente=payload, assinatura_profissional=payload)
                html = str(renderizar_corpo_documento(doc))
                self.assertNotIn('onerror', html)
                self.assertNotIn('onload', html)
                self.assertNotIn('<script', html)
                self.assertNotIn('file://', html)
                self.assertNotIn('169.254', html)
                self.assertNotIn('javascript:', html)

    def test_render_mantem_assinatura_valida(self):
        html = str(renderizar_corpo_documento(self.doc_a))
        self.assertIn(f'src="{ASSINATURA_OK}"', html)

    def test_texto_final_continua_escapado(self):
        doc = self._documento(self.inst_a, self.pac_a, self.tpl_a, self.padrao_a,
                              texto_final='<img src=x onerror=alert(1)> [assinatura_profissional]')
        html = str(renderizar_corpo_documento(doc))
        self.assertNotIn('<img src=x', html)
        self.assertIn('&lt;img src=x', html)

    def test_historico_nao_reflete_payload(self):
        self._documento(self.inst_a, self.pac_a, self.tpl_a, self.padrao_a,
                        assinatura_paciente='x" onerror="alert(1)')
        self.logar_como(self.padrao_a)
        resp = self.client.get(reverse('historico'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('onerror=&quot;alert(1)', resp.content.decode())
        self.assertNotIn('onerror="alert(1)', resp.content.decode())

    def test_gerar_tcle_recusa_assinatura_invalida(self):
        self.logar_como(self.padrao_a)
        antes = DocumentoEmitido.objects.count()
        for payload in self.PAYLOADS:
            with self.subTest(payload=payload):
                self.client.post(reverse('gerar_tcle'), self._post_tcle(assinatura_paciente=payload))
        self.assertEqual(DocumentoEmitido.objects.count(), antes)

    def test_gerar_tcle_recusa_assinatura_gigante(self):
        self.logar_como(self.padrao_a)
        gigante = 'data:image/png;base64,' + 'A' * (1_500_000)  # abaixo do limite de corpo do Django, acima do limite da assinatura
        self.client.post(reverse('gerar_tcle'), self._post_tcle(assinatura_profissional=gigante))
        self.assertFalse(DocumentoEmitido.objects.filter(assinatura_profissional=gigante).exists())

    def _post_tcle(self, **extra):
        dados = {'template_id': self.tpl_a.id, 'paciente_id': self.pac_a.id, 'tipo': 'paciente',
                 'texto_final': 'Termo final', 'assinatura_paciente': ASSINATURA_OK,
                 'assinatura_profissional': ASSINATURA_OK}
        dados.update(extra)
        return dados

    def test_pdf_nao_busca_recursos_externos(self):
        from .views import pdf_url_fetcher
        for url in ('file:///etc/hostname', 'http://127.0.0.1:9/x.png', 'https://example.com/a.png',
                    'ftp://example.com/x'):
            with self.subTest(url=url):
                with self.assertRaises(Exception):
                    pdf_url_fetcher(url)
        # data: URI de imagem continua permitido
        resultado = pdf_url_fetcher(ASSINATURA_OK)
        self.assertTrue(resultado)


# ---------------------------------------------------------------------------
# Isolamento entre unidades (multi-tenant) e permissões
# ---------------------------------------------------------------------------
class IsolamentoTests(PacientesBase):
    def setUp(self):
        super().setUp()
        self.logar_como(self.padrao_a)

    def test_pdf_de_outra_unidade_da_404(self):
        self.assertEqual(self.client.get(reverse('documento_pdf', args=[self.doc_b.id])).status_code, 404)

    def test_email_de_outra_unidade_da_404(self):
        resp = self.client.post(reverse('documento_enviar_email', args=[self.doc_b.id]))
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(len(mail.outbox), 0)

    def test_historico_lista_so_documentos_da_unidade(self):
        resp = self.client.get(reverse('historico'))
        ids = [d['obj'].id for d in resp.context['documentos_view']]
        self.assertIn(self.doc_a.id, ids)
        self.assertNotIn(self.doc_b.id, ids)

    def test_nao_gera_tcle_com_paciente_ou_template_de_outra_unidade(self):
        base = {'tipo': 'paciente', 'texto_final': 'x', 'assinatura_paciente': ASSINATURA_OK,
                'assinatura_profissional': ASSINATURA_OK}
        antes = DocumentoEmitido.objects.count()
        r1 = self.client.post(reverse('gerar_tcle'), {**base, 'template_id': self.tpl_a.id, 'paciente_id': self.pac_b.id})
        r2 = self.client.post(reverse('gerar_tcle'), {**base, 'template_id': self.tpl_b.id, 'paciente_id': self.pac_a.id})
        self.assertEqual((r1.status_code, r2.status_code), (404, 404))
        self.assertEqual(DocumentoEmitido.objects.count(), antes)

    def test_nao_edita_paciente_de_outra_unidade(self):
        resp = self.client.post(reverse('pacientes'), self.dados_paciente(paciente_id=self.pac_b.id, nome='Hack'))
        self.assertIn(resp.status_code, (302, 404))
        self.pac_b.refresh_from_db()
        self.assertEqual(self.pac_b.nome, 'José Souza')

    def test_nao_edita_template_nem_categoria_de_outra_unidade(self):
        self.logar_como(self.coord_a)
        self.client.post(reverse('biblioteca'), {'template_id': self.tpl_b.id, 'titulo': 'Hack', 'resumo': 'r',
                                                 'categoria': self.cat_a.id, 'texto_base': 'x'})
        self.tpl_b.refresh_from_db()
        self.assertEqual(self.tpl_b.titulo, 'Modelo B')
        # categoria de outra unidade não pode ser usada num template da unidade A
        self.client.post(reverse('biblioteca'), {'titulo': 'Novo', 'resumo': 'r',
                                                 'categoria': self.cat_b.id, 'texto_base': 'x'})
        self.assertFalse(TemplateTCLE.objects.filter(titulo='Novo').exists())
        resp = self.client.post(reverse('editar_categoria', args=[self.cat_b.id]), {'nome': 'Hack', 'texto_padrao': ''})
        self.assertEqual(resp.status_code, 404)

    def test_admin_sem_unidade_ativa_nao_acessa_dados(self):
        self.logar_como(self.admin)
        for nome in ('pacientes', 'biblioteca', 'historico', 'gerar_tcle'):
            with self.subTest(rota=nome):
                self.assertRedirects(self.client.get(reverse(nome)), reverse('painel_adm'),
                                     fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse('documento_pdf', args=[self.doc_a.id])).status_code, 404)

    def test_admin_na_unidade_a_nao_ve_documento_da_b(self):
        self.logar_como(self.admin, unidade=self.inst_a)
        self.assertEqual(self.client.get(reverse('documento_pdf', args=[self.doc_a.id])).status_code, 200)
        self.assertEqual(self.client.get(reverse('documento_pdf', args=[self.doc_b.id])).status_code, 404)

    def test_usuario_padrao_nao_gerencia_categorias(self):
        self.client.post(reverse('criar_categoria'), {'nome': 'Nova', 'texto_padrao': ''})
        self.assertFalse(CategoriaTemplate.objects.filter(nome='Nova').exists())
        self.client.post(reverse('editar_categoria', args=[self.cat_a.id]), {'nome': 'Hack', 'texto_padrao': ''})
        self.cat_a.refresh_from_db()
        self.assertEqual(self.cat_a.nome, 'Cirúrgico')

    def test_coordenador_gerencia_categorias(self):
        self.logar_como(self.coord_a)
        self.client.post(reverse('criar_categoria'), {'nome': 'Nova', 'texto_padrao': 'abc'})
        self.assertTrue(CategoriaTemplate.objects.filter(instituicao=self.inst_a, nome='Nova').exists())


# ---------------------------------------------------------------------------
# Emissão do TCLE
# ---------------------------------------------------------------------------
class GerarTcleTests(PacientesBase):
    def setUp(self):
        super().setUp()
        self.logar_como(self.padrao_a)

    def _post(self, **extra):
        dados = {'template_id': self.tpl_a.id, 'paciente_id': self.pac_a.id, 'tipo': 'paciente',
                 'texto_final': 'Termo final', 'assinatura_paciente': ASSINATURA_OK,
                 'assinatura_profissional': ASSINATURA_OK}
        dados.update(extra)
        self.client.raise_request_exception = False
        return self.client.post(reverse('gerar_tcle'), dados)

    def test_fluxo_feliz(self):
        antes = DocumentoEmitido.objects.count()
        resp = self._post()
        self.assertRedirects(resp, reverse('pacientes'), fetch_redirect_response=False)
        self.assertEqual(DocumentoEmitido.objects.count(), antes + 1)
        doc = DocumentoEmitido.objects.latest('id')
        self.assertEqual(doc.medico_emissor, self.padrao_a)
        self.assertEqual(doc.instituicao, self.inst_a)
        self.assertEqual(doc.status, 'ASSINADO')

    def test_template_inativo_nao_pode_ser_emitido(self):
        TemplateTCLE.objects.filter(pk=self.tpl_a.pk).update(ativo=False)
        antes = DocumentoEmitido.objects.count()
        self._post()
        self.assertEqual(DocumentoEmitido.objects.count(), antes)

    def test_ids_invalidos_nao_geram_erro_500(self):
        for extra in ({'template_id': 'abc'}, {'paciente_id': ''}, {'paciente_id': "1' OR '1'='1"},
                      {'template_id': '99999999999999999999'}):
            with self.subTest(extra=extra):
                self.assertEqual(self._post(**extra).status_code, 404)

    def test_tipo_invalido_e_recusado(self):
        antes = DocumentoEmitido.objects.count()
        self._post(tipo='qualquer-coisa')
        self.assertEqual(DocumentoEmitido.objects.count(), antes)

    def test_responsavel_de_outra_unidade_e_recusado(self):
        antes = DocumentoEmitido.objects.count()
        resp = self._post(tipo='responsavel', responsavel_id=self.pac_b.id)
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(DocumentoEmitido.objects.count(), antes)

    def test_texto_muito_grande_e_recusado(self):
        antes = DocumentoEmitido.objects.count()
        self._post(texto_final='A' * 300_000)
        self.assertEqual(DocumentoEmitido.objects.count(), antes)

    def test_sem_assinaturas_nao_emite(self):
        antes = DocumentoEmitido.objects.count()
        self._post(assinatura_paciente='')
        self.assertEqual(DocumentoEmitido.objects.count(), antes)


# ---------------------------------------------------------------------------
# Cadastro de pacientes: validação de entradas
# ---------------------------------------------------------------------------
class CadastroPacienteTests(PacientesBase):
    def setUp(self):
        super().setUp()
        self.logar_como(self.padrao_a)
        self.client.raise_request_exception = False

    def _post(self, **extra):
        return self.client.post(reverse('pacientes'), self.dados_paciente(**extra))

    def test_cadastro_valido_normaliza_cpf(self):
        self._post()
        self.assertEqual(Paciente.objects.get(nome='Ana Paula Lima').cpf, '390.533.447-05')

    def test_cpf_invalido_e_recusado(self):
        for cpf in ('123.456.789-00', '111.111.111-11', '123', 'abc.def.ghi-jk', ''):
            with self.subTest(cpf=cpf):
                self._post(cpf=cpf)
                self.assertFalse(Paciente.objects.filter(nome='Ana Paula Lima').exists())

    def test_cpf_duplicado_com_formatacao_diferente(self):
        self._post(cpf='529.982.247-25')              # já existe (pac_a) na unidade A, com máscara
        self._post(nome='Outra Ana', cpf='52998224725')
        self.assertEqual(Paciente.objects.filter(instituicao=self.inst_a, cpf='529.982.247-25').count(), 1)
        self.assertFalse(Paciente.objects.filter(nome='Outra Ana').exists())

    def test_mesmo_cpf_em_unidades_diferentes_e_permitido(self):
        self.logar_como(self.padrao_b)
        self._post(cpf=CPF_VALIDO_1, nome='Na unidade B')
        self.assertTrue(Paciente.objects.filter(instituicao=self.inst_b, nome='Na unidade B').exists())

    def test_campos_invalidos_sao_recusados(self):
        casos = [
            {'data_nascimento': '2999-01-01'},   # futura
            {'data_nascimento': 'ontem'},        # inválida
            {'email': 'sem-arroba'},
            {'uf': 'ZZ'},
            {'nome': '   '},
            {'nome': 'A' * 300},
            {'cep': '12'},
            {'telefone': ''},
        ]
        for extra in casos:
            with self.subTest(extra=extra):
                self._post(**extra)
                self.assertEqual(Paciente.objects.filter(instituicao=self.inst_a).count(), 1)

    def test_id_de_paciente_invalido_nao_da_500(self):
        for pid in ('abc', '99999999999999999999', '-1'):
            with self.subTest(pid=pid):
                self.assertIn(self._post(paciente_id=pid).status_code, (302, 404))

    def test_edicao_valida(self):
        self._post(paciente_id=self.pac_a.id, cpf=CPF_VALIDO_1, nome='Maria Editada')
        self.pac_a.refresh_from_db()
        self.assertEqual(self.pac_a.nome, 'Maria Editada')

    def test_edicao_preserva_cpf_legado_invalido(self):
        Paciente.objects.filter(pk=self.pac_a.pk).update(cpf='000.000.000-00')
        self._post(paciente_id=self.pac_a.id, cpf='000.000.000-00', nome='Só o nome mudou')
        self.pac_a.refresh_from_db()
        self.assertEqual(self.pac_a.nome, 'Só o nome mudou')

    def test_mensagem_de_erro_indica_o_motivo_real(self):
        resp = self._post(data_nascimento='ontem')
        texto = ' '.join(mensagens(resp))
        self.assertNotIn('CPF já está cadastrado', texto)

    def test_caracteres_de_controle_sao_removidos(self):
        self._post(nome='Ana\r\nBcc: x@evil.com')
        p = Paciente.objects.get(cpf='390.533.447-05')
        self.assertEqual(p.nome, 'Ana Bcc: x@evil.com')


# ---------------------------------------------------------------------------
# Biblioteca de templates
# ---------------------------------------------------------------------------
class BibliotecaTests(PacientesBase):
    def setUp(self):
        super().setUp()
        self.logar_como(self.coord_a)
        self.client.raise_request_exception = False

    def _post(self, **extra):
        dados = {'titulo': 'Novo modelo', 'resumo': 'Resumo curto', 'categoria': self.cat_a.id, 'texto_base': 'Corpo'}
        dados.update(extra)
        return self.client.post(reverse('biblioteca'), dados)

    def test_criacao_valida(self):
        self._post()
        self.assertTrue(TemplateTCLE.objects.filter(instituicao=self.inst_a, titulo='Novo modelo').exists())

    def test_categoria_invalida_nao_da_500(self):
        for cat in ('abc', '', '99999999999999999999'):
            with self.subTest(cat=cat):
                self.assertEqual(self._post(categoria=cat).status_code, 404)

    def test_titulo_e_texto_obrigatorios(self):
        self._post(titulo='   ')
        self._post(titulo='Sem corpo', texto_base='   ')
        self.assertFalse(TemplateTCLE.objects.filter(titulo__in=['   ', 'Sem corpo']).exists())

    def test_titulo_grande_demais(self):
        self._post(titulo='T' * 300)
        self.assertFalse(TemplateTCLE.objects.filter(titulo__startswith='TTTT').exists())

    def test_erro_interno_nao_vaza_para_o_usuario(self):
        with mock.patch.object(TemplateTCLE.objects, 'create', side_effect=RuntimeError('SEGREDO-INTERNO db=10.0.0.5')):
            resp = self._post()
        self.assertNotIn('SEGREDO-INTERNO', ' '.join(mensagens(resp)))

    def test_categoria_sem_nome_e_recusada(self):
        self.client.post(reverse('criar_categoria'), {'nome': '   ', 'texto_padrao': ''})
        self.assertEqual(CategoriaTemplate.objects.filter(instituicao=self.inst_a).count(), 1)

    def test_categoria_duplicada_e_recusada(self):
        resp = self.client.post(reverse('criar_categoria'), {'nome': 'Cirúrgico', 'texto_padrao': ''})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(CategoriaTemplate.objects.filter(instituicao=self.inst_a, nome='Cirúrgico').count(), 1)

    def test_pagina_renderiza(self):
        self.assertEqual(self.client.get(reverse('biblioteca')).status_code, 200)


# ---------------------------------------------------------------------------
# PDF e e-mail
# ---------------------------------------------------------------------------
class PdfEmailTests(PacientesBase):
    def setUp(self):
        super().setUp()
        self.logar_como(self.padrao_a)

    def test_pdf_e_gerado(self):
        resp = self.client.get(reverse('documento_pdf', args=[self.doc_a.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/pdf')
        self.assertTrue(resp.content.startswith(b'%PDF'))

    def test_nome_do_arquivo_com_caracteres_especiais(self):
        pac = self._paciente(self.inst_a, 'João "Zé"\r\nX-Injetado: 1 Ção', '390.533.447-05', self.padrao_a)
        doc = self._documento(self.inst_a, pac, self.tpl_a, self.padrao_a)
        resp = self.client.get(reverse('documento_pdf', args=[doc.id]))
        self.assertEqual(resp.status_code, 200)
        cd = resp['Content-Disposition']
        self.assertNotIn('\n', cd)
        self.assertNotIn('\r', cd)
        self.assertNotIn('X-Injetado', resp.headers)
        self.assertTrue(cd.startswith('inline'))

    def test_pdf_sem_weasyprint_usa_fallback_html(self):
        with mock.patch('pacientes.views._importar_weasyprint', side_effect=OSError('sem pango')):
            resp = self.client.get(reverse('documento_pdf', args=[self.doc_a.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('text/html', resp['Content-Type'])

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_envio_de_email(self):
        resp = self.client.post(reverse('documento_enviar_email', args=[self.doc_a.id]))
        self.assertRedirects(resp, reverse('historico'), fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['paciente@ex.com'])
        self.assertEqual(len(mail.outbox[0].attachments), 1)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_envio_exige_post(self):
        self.client.get(reverse('documento_enviar_email', args=[self.doc_a.id]))
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_envio_com_template_removido_nao_da_500(self):
        TemplateTCLE.objects.filter(pk=self.tpl_a.pk).delete()
        self.client.raise_request_exception = False
        resp = self.client.post(reverse('documento_enviar_email', args=[self.doc_a.id]))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)

    def test_falha_de_smtp_nao_vaza_detalhes(self):
        with mock.patch('django.core.mail.EmailMessage.send',
                        side_effect=Exception('535 auth failed user=smtp-user pass=SEGREDO')):
            resp = self.client.post(reverse('documento_enviar_email', args=[self.doc_a.id]))
        self.assertNotIn('SEGREDO', ' '.join(mensagens(resp)))

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_nao_envia_sem_pdf(self):
        with mock.patch('pacientes.views._importar_weasyprint', side_effect=OSError('sem pango')):
            self.client.post(reverse('documento_enviar_email', args=[self.doc_a.id]))
        self.assertEqual(len(mail.outbox), 0, 'Não deve dizer "em anexo" sem anexar o PDF')

    def test_historico_e_paginas_de_pacientes_nao_ficam_em_cache(self):
        for nome in ('historico', 'pacientes'):
            with self.subTest(rota=nome):
                self.assertIn('no-store', self.client.get(reverse(nome))['Cache-Control'])
