"""
Limitação de tentativas (força bruta) baseada no cache do Django.

Cada escopo (ex.: 'login', 'trocasenha') mantém dois contadores em janela fixa:
  - por (IP + identificador): barra um cliente que insiste em uma conta;
  - por identificador, de qualquer IP: barra ataques distribuídos a uma conta.

Observação: o cache padrão do Django (LocMemCache) é por processo. Em produção
com vários processos/servidores configure um cache compartilhado (Redis,
Memcached ou banco) em `CACHES` para que o limite valha para todos.
"""
import hashlib
import logging

from django.core.cache import cache

logger = logging.getLogger(__name__)

LIMITE_POR_IP_E_IDENTIFICADOR = 5
LIMITE_POR_IDENTIFICADOR = 20
JANELA_SEGUNDOS = 15 * 60


def _ip(request):
    # REMOTE_ADDR é o único valor que o cliente não consegue forjar.
    return (request.META.get('REMOTE_ADDR') if request is not None else None) or 'desconhecido'


def _chaves(escopo, request, identificador, limites):
    ident = hashlib.sha256((identificador or '').strip().lower().encode('utf-8')).hexdigest()[:32]
    return [
        (f'throttle:{escopo}:{_ip(request)}:{ident}', limites[0]),
        (f'throttle:{escopo}:{ident}', limites[1]),
    ]


def bloqueado(escopo, request, identificador,
              limites=(LIMITE_POR_IP_E_IDENTIFICADOR, LIMITE_POR_IDENTIFICADOR)):
    return any(cache.get(chave, 0) >= limite
               for chave, limite in _chaves(escopo, request, identificador, limites))


def registrar_falha(escopo, request, identificador,
                    limites=(LIMITE_POR_IP_E_IDENTIFICADOR, LIMITE_POR_IDENTIFICADOR)):
    for chave, limite in _chaves(escopo, request, identificador, limites):
        if not cache.add(chave, 1, JANELA_SEGUNDOS):
            try:
                total = cache.incr(chave)
            except ValueError:  # a chave expirou entre o add e o incr
                cache.set(chave, 1, JANELA_SEGUNDOS)
                total = 1
            if total == limite:
                logger.warning('Bloqueio temporário por excesso de tentativas: escopo=%s ip=%s',
                               escopo, _ip(request))


def limpar(escopo, request, identificador,
           limites=(LIMITE_POR_IP_E_IDENTIFICADOR, LIMITE_POR_IDENTIFICADOR)):
    cache.delete_many([chave for chave, _ in _chaves(escopo, request, identificador, limites)])
