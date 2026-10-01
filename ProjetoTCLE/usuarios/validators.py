"""
Política de senhas do sistema.

Regras (valem para toda nova senha e para toda alteração de senha):
  - no mínimo 8 caracteres;
  - pelo menos 1 letra;
  - pelo menos 1 número;
  - pelo menos 1 caractere especial;
  - os números não podem estar em sequência crescente ou decrescente
    (12, 23, 34, 123, 456, 21, 321...).

O frontend replica estas regras em `usuarios/_politica_senha.html`, mas a
validação que vale é esta, no backend.
"""
import re
import unicodedata

from django.core.exceptions import ValidationError

TAMANHO_MINIMO_SENHA = 8
# Limite superior: evita gastar CPU calculando hash de "senhas" gigantes.
TAMANHO_MAXIMO_SENHA = 128
DIGITOS = '0123456789'

AJUDA_POLITICA_SENHA = (
    'Mínimo de 8 caracteres, com pelo menos 1 letra, 1 número e 1 caractere '
    'especial. Não use números em sequência (ex.: 12, 321, 456).'
)


def tem_numeros_em_sequencia(senha):
    """True se dois dígitos vizinhos formam uma sequência (crescente ou decrescente)."""
    for atual, proximo in zip(senha, senha[1:]):
        if atual in DIGITOS and proximo in DIGITOS and abs(int(atual) - int(proximo)) == 1:
            return True
    return False


def erros_politica_senha(senha):
    """Devolve a lista de regras violadas (lista vazia = senha válida)."""
    senha = senha or ''
    erros = []

    if len(senha) < TAMANHO_MINIMO_SENHA:
        erros.append(f'A senha deve ter no mínimo {TAMANHO_MINIMO_SENHA} caracteres.')
    if len(senha) > TAMANHO_MAXIMO_SENHA:
        erros.append(f'A senha deve ter no máximo {TAMANHO_MAXIMO_SENHA} caracteres.')
    if not any(c.isalpha() for c in senha):
        erros.append('A senha deve conter pelo menos 1 letra.')
    if not any(c in DIGITOS for c in senha):
        erros.append('A senha deve conter pelo menos 1 número.')
    if not any(not c.isalnum() and not c.isspace() for c in senha):
        erros.append('A senha deve conter pelo menos 1 caractere especial.')
    if tem_numeros_em_sequencia(senha):
        erros.append('Os números da senha não podem estar em sequência crescente ou decrescente (ex.: 12, 321, 456).')

    return erros


class PoliticaSenhaValidator:
    """Mesma política, no formato de AUTH_PASSWORD_VALIDATORS (createsuperuser, /admin/...)."""

    def validate(self, password, user=None):
        erros = erros_politica_senha(password)
        if erros:
            raise ValidationError(erros, code='senha_fora_da_politica')

    def get_help_text(self):
        return AJUDA_POLITICA_SENHA


# ---------------------------------------------------------------------------
# Utilitários de validação de entradas (usados pelas views)
# ---------------------------------------------------------------------------
def limpar_texto(valor, tamanho_max=None):
    """
    Texto de UMA linha: remove caracteres de controle (inclusive quebras de linha,
    úteis para injeção de cabeçalhos de e-mail/HTTP) e colapsa espaços.
    Não corta o texto: quem chama compara com `tamanho_max` para validar.
    """
    if valor is None:
        return ''
    texto = ''.join(
        ' ' if unicodedata.category(c).startswith('C') else c
        for c in str(valor)
    )
    return ' '.join(texto.split())


def somente_digitos(valor):
    return re.sub(r'\D', '', valor or '')


def _digito_verificador(digitos, pesos):
    soma = sum(int(d) * p for d, p in zip(digitos, pesos))
    resto = soma % 11
    return '0' if resto < 2 else str(11 - resto)


def cpf_valido(valor):
    """Valida CPF (11 dígitos + dígitos verificadores; rejeita 111.111.111-11 etc.)."""
    d = somente_digitos(valor)
    if len(d) != 11 or d == d[0] * 11:
        return False
    d1 = _digito_verificador(d[:9], range(10, 1, -1))
    d2 = _digito_verificador(d[:9] + d1, range(11, 1, -1))
    return d[9:] == d1 + d2


def formatar_cpf(valor):
    d = somente_digitos(valor)
    return f'{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}'


def cnpj_valido(valor):
    d = somente_digitos(valor)
    if len(d) != 14 or d == d[0] * 14:
        return False
    pesos1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    d1 = _digito_verificador(d[:12], pesos1)
    d2 = _digito_verificador(d[:12] + d1, [6] + pesos1)
    return d[12:] == d1 + d2


def formatar_cnpj(valor):
    d = somente_digitos(valor)
    return f'{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}'


def cep_valido(valor):
    return len(somente_digitos(valor)) == 8


def formatar_cep(valor):
    d = somente_digitos(valor)
    return f'{d[:5]}-{d[5:]}'


UFS = frozenset({
    'AC', 'AL', 'AP', 'AM', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MT', 'MS', 'MG', 'PA',
    'PB', 'PR', 'PE', 'PI', 'RJ', 'RN', 'RS', 'RO', 'RR', 'SC', 'SP', 'SE', 'TO',
})
