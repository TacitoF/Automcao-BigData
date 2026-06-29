"""
tls_compat.py - Contexto SSL/TLS compatível com servidores de email legados.

Alguns servidores de email mais antigos (comum em sistemas internos de
órgãos públicos) não suportam o nível de segurança que versões recentes do
Python/OpenSSL exigem por padrão. Isso causa erros como
'SSLV3_ALERT_HANDSHAKE_FAILURE' mesmo quando a conexão, credenciais e rede
estão corretas — é só uma incompatibilidade de versão/cifra de TLS.

Este contexto relaxa esse nível de exigência (permite TLS 1.0+ e cifras mais
antigas), mas a conexão continua sempre criptografada via TLS. Não desliga
verificação de certificado nem deixa a conexão em texto puro.
"""

import ssl


def get_legacy_context(verify_hostname: bool = True, verify_cert: bool = True) -> ssl.SSLContext:
    """Contexto TLS com nível de segurança reduzido (SECLEVEL=1),
    para interoperar com servidores antigos. Ainda exige TLS, só aceita
    versões/cifras mais antigas que o padrão atual do Python rejeitaria.

    verify_hostname=False desliga APENAS a checagem de hostname (CN/SAN do
    certificado contra o endereço usado na conexão). A cadeia de
    certificado, validade e assinatura continuam sendo verificadas
    normalmente - a conexão continua criptografada via TLS. Use isso só
    quando o servidor é acessado por IP (sem hostname/DNS reverso
    disponível) e o certificado foi emitido para um hostname diferente do
    IP usado na conexão - nesse cenário, a checagem de hostname falha por
    construção mesmo com o servidor correto e o certificado válido.

    verify_cert=False desliga TODA a validação do certificado (cadeia,
    validade/expiração e assinatura), além do hostname. A conexão
    continua criptografada via TLS, mas deixa de garantir que o
    certificado apresentado é genuíno e ainda válido - ou seja, fica
    vulnerável a interceptação (man-in-the-middle) por qualquer um com
    acesso à rede pela qual a conexão passa. Use isso apenas como medida
    temporária, em rede interna confiável, enquanto um certificado
    expirado ou inválido no servidor não é renovado - nunca como
    configuração permanente."""
    context = ssl.create_default_context()

    try:
        context.minimum_version = ssl.TLSVersion.TLSv1
    except (AttributeError, ValueError):
        pass

    try:
        context.set_ciphers("DEFAULT@SECLEVEL=1")
    except ssl.SSLError:
        pass

    if not verify_hostname:
        context.check_hostname = False

    if not verify_cert:
        # check_hostname precisa ser desligado antes de CERT_NONE, ou o
        # módulo ssl recusa a combinação (ValueError).
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

    return context