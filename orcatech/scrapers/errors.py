_MARCADORES_BLOQUEIO = (
    "captcha",
    "access denied",
    "too many requests",
    "verify you are human",
    "are you a human",
    "robot check",
    "temporarily blocked",
    "unusual traffic",
)


class BloqueioLoja(RuntimeError):
    """A loja indicou explicitamente um bloqueio ou uma verificação anti-bot."""


def pagina_com_bloqueio(html, url=""):
    texto = (html or "").casefold()
    endereco = (url or "").casefold()
    return any(marcador in texto for marcador in _MARCADORES_BLOQUEIO) or any(
        marcador in endereco
        for marcador in ("account-verification", "captcha", "blocked")
    )
