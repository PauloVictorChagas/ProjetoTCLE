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
from django.core.exceptions import ValidationError

TAMANHO_MINIMO_SENHA = 8
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
