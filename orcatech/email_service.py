import logging
import os
import smtplib
import ssl
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import parseaddr

from .models import EnvioEmail, Orcamento, Usuario, db


logger = logging.getLogger(__name__)
executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="orcamento-email")
_fila_lock = threading.Lock()


class LimiteEnviosAtingido(ValueError):
    pass


def email_valido(endereco):
    nome, email = parseaddr(endereco or "")
    return bool(
        email
        and not nome
        and len(email) <= 254
        and "@" in email
        and "." in email.rsplit("@", 1)[-1]
        and not any(char.isspace() for char in email)
    )


def _contar_envios_recentemente(orcamento_id, limite_horas=1):
    desde = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=limite_horas)
    return EnvioEmail.query.filter(
        EnvioEmail.orcamento_id == orcamento_id,
        EnvioEmail.criado_em >= desde,
    ).count()


def enfileirar_email(
    app,
    orcamento_id,
    usuario_id,
    destinatario,
    anexar_pdf=True,
    link_interno=None,
    assunto=None,
    mensagem_texto=None,
):
    if not email_valido(destinatario):
        raise ValueError("Informe um endereço de e-mail válido.")
    if bool(assunto) != bool(mensagem_texto):
        raise ValueError("Assunto e conteúdo do e-mail devem ser informados juntos.")
    if orcamento_id is None and not assunto:
        raise ValueError("E-mails sem orçamento precisam de assunto e conteúdo.")
    if assunto and ("\r" in assunto or "\n" in assunto or len(assunto) > 200):
        raise ValueError("O assunto do e-mail é inválido.")
    if mensagem_texto and len(mensagem_texto) > 10000:
        raise ValueError("O conteúdo do e-mail excede o limite permitido.")

    with _fila_lock, app.app_context():
        limite = app.config["ORCAMENTO_MAX_EMAILS_HORA"]
        if _contar_envios_recentemente(orcamento_id) >= limite:
            raise LimiteEnviosAtingido(
                f"Limite de {limite} envios por orçamento por hora atingido."
            )
        envio = EnvioEmail(
            orcamento_id=orcamento_id,
            usuario_id=usuario_id,
            destinatario=destinatario,
            sucesso=None,
            erro="Envio em andamento.",
        )
        db.session.add(envio)
        db.session.commit()
        envio_id = envio.id

    try:
        executor.submit(
            _processar_envio,
            app,
            envio_id,
            orcamento_id,
            anexar_pdf,
            link_interno,
            assunto,
            mensagem_texto,
        )
    except RuntimeError as exc:
        with app.app_context():
            envio = db.session.get(EnvioEmail, envio_id)
            envio.sucesso = False
            envio.erro = "Não foi possível iniciar o processamento do e-mail."
            db.session.commit()
        raise RuntimeError("Não foi possível enfileirar o envio de e-mail.") from exc
    return envio_id


def _url_publica(app, orcamento):
    if (
        not orcamento.share_token
        or orcamento.share_revogado
        or not orcamento.share_expira_em
        or orcamento.share_expira_em <= datetime.now(timezone.utc).replace(tzinfo=None)
    ):
        return None
    return f"{app.config['APP_BASE_URL']}/p/{orcamento.share_token}"


def _montar_mensagem(app, orcamento, destinatario, anexar_pdf, link_interno):
    config = app.config
    host = config["SMTP_HOST"]
    remetente = config["SMTP_FROM"] or config["SMTP_USERNAME"]
    if not host or not email_valido(remetente):
        raise ValueError("Configure SMTP_HOST e SMTP_FROM para enviar e-mails.")
    try:
        porta = int(config["SMTP_PORT"])
    except ValueError as exc:
        raise ValueError("SMTP_PORT deve ser um número inteiro.") from exc
    usuario = config["SMTP_USERNAME"]
    senha = config["SMTP_PASSWORD"]
    if bool(usuario) != bool(senha):
        raise ValueError("SMTP_USERNAME e SMTP_PASSWORD devem ser configurados juntos.")

    mensagem = EmailMessage()
    mensagem["Subject"] = f"Orçamento {orcamento.numero} - OrçaTech"
    mensagem["From"] = remetente
    mensagem["To"] = destinatario
    linhas = [
        f"Orçamento: {orcamento.numero}",
        f"Status: {orcamento.status.replace('_', ' ')}",
        f"Total: R$ {orcamento.total:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
    ]
    link_publico = _url_publica(app, orcamento)
    if link_publico:
        linhas.append(f"Link público: {link_publico}")
    if link_interno:
        linhas.append(f"Acesse o sistema: {link_interno}")
    mensagem.set_content("\n".join(linhas))

    if anexar_pdf:
        from .gerar_pdf_orcamento import gerar_pdf_orcamento

        with tempfile.TemporaryDirectory(prefix="orcamento-email-") as pasta_temp:
            caminho_pdf = gerar_pdf_orcamento(
                orcamento,
                caminho_saida=os.path.join(pasta_temp, f"{orcamento.numero}.pdf"),
            )
            with open(caminho_pdf, "rb") as arquivo:
                mensagem.add_attachment(
                    arquivo.read(),
                    maintype="application",
                    subtype="pdf",
                    filename=f"{orcamento.numero}.pdf",
                )
    return mensagem, host, porta, usuario, senha


def _montar_mensagem_personalizada(app, destinatario, assunto, mensagem_texto):
    config = app.config
    host = config["SMTP_HOST"]
    remetente = config["SMTP_FROM"] or config["SMTP_USERNAME"]
    if not host or not email_valido(remetente):
        raise ValueError("Configure SMTP_HOST e SMTP_FROM para enviar e-mails.")
    try:
        porta = int(config["SMTP_PORT"])
    except ValueError as exc:
        raise ValueError("SMTP_PORT deve ser um número inteiro.") from exc
    usuario = config["SMTP_USERNAME"]
    senha = config["SMTP_PASSWORD"]
    if bool(usuario) != bool(senha):
        raise ValueError("SMTP_USERNAME e SMTP_PASSWORD devem ser configurados juntos.")

    mensagem = EmailMessage()
    mensagem["Subject"] = assunto
    mensagem["From"] = remetente
    mensagem["To"] = destinatario
    mensagem.set_content(mensagem_texto)
    return mensagem, host, porta, usuario, senha


def _processar_envio(
    app,
    envio_id,
    orcamento_id,
    anexar_pdf,
    link_interno,
    assunto,
    mensagem_texto,
):
    with app.app_context():
        envio = db.session.get(EnvioEmail, envio_id)
        orcamento = (
            db.session.get(Orcamento, orcamento_id)
            if orcamento_id is not None
            else None
        )
        try:
            if not envio:
                raise LookupError("O envio não foi encontrado.")
            if orcamento_id is None:
                mensagem, host, porta, usuario, senha = _montar_mensagem_personalizada(
                    app, envio.destinatario, assunto, mensagem_texto
                )
            else:
                if not orcamento:
                    raise LookupError("O orçamento não foi encontrado.")
                mensagem, host, porta, usuario, senha = _montar_mensagem(
                    app, orcamento, envio.destinatario, anexar_pdf, link_interno
                )
            with smtplib.SMTP(host, porta, timeout=20) as servidor:
                if app.config["SMTP_USE_TLS"]:
                    servidor.starttls(context=ssl.create_default_context())
                if usuario:
                    servidor.login(usuario, senha)
                servidor.send_message(mensagem)
            envio.sucesso = True
            envio.erro = None
        except Exception as exc:
            logger.error("Falha no envio de orçamento %s (%s).", orcamento_id, type(exc).__name__)
            if envio:
                envio.sucesso = False
                envio.erro = (
                    "Falha inesperada no processamento do e-mail."
                    if not isinstance(exc, (ValueError, OSError, smtplib.SMTPException, LookupError))
                    else f"Falha no envio ({type(exc).__name__})."
                )
        finally:
            db.session.commit()


def notificar_aprovadores(app, orcamento_id):
    with app.app_context():
        orcamento = db.session.get(Orcamento, orcamento_id)
        if not orcamento:
            return
        destinatarios = (
            Usuario.query.filter(
                Usuario.ativo.is_(True),
                Usuario.papel.in_(("admin", "aprovador")),
                Usuario.id != orcamento.usuario_id,
            )
            .order_by(Usuario.id)
            .all()
        )
        solicitante_id = orcamento.usuario_id
        destinatarios_email = [usuario.email for usuario in destinatarios]
    for email in destinatarios_email:
        try:
            enfileirar_email(
                app,
                orcamento_id,
                solicitante_id,
                email,
                anexar_pdf=False,
                link_interno=f"{app.config['APP_BASE_URL']}/aprovacoes",
            )
        except LimiteEnviosAtingido:
            logger.warning("Limite de notificações atingido para orçamento %s.", orcamento_id)
            break
        except ValueError as exc:
            logger.warning(
                "Notificação do orçamento %s não foi enfileirada (%s).",
                orcamento_id,
                type(exc).__name__,
            )
        except RuntimeError as exc:
            logger.error(
                "Notificação do orçamento %s falhou ao entrar na fila (%s).",
                orcamento_id,
                type(exc).__name__,
            )


def notificar_solicitante(app, orcamento_id, decisor_id):
    with app.app_context():
        orcamento = db.session.get(Orcamento, orcamento_id)
        if not orcamento or not orcamento.usuario:
            return
        destinatario_id = orcamento.usuario.id
        email = orcamento.usuario.email
    try:
        enfileirar_email(
            app,
            orcamento_id,
            decisor_id or destinatario_id,
            email,
            anexar_pdf=False,
            link_interno=(
                f"{app.config['APP_BASE_URL']}/orcamento/{orcamento_id}"
            ),
        )
    except LimiteEnviosAtingido:
        logger.warning("Limite de notificações atingido para orçamento %s.", orcamento_id)
    except ValueError as exc:
        logger.warning(
            "Notificação do orçamento %s não foi enfileirada (%s).",
            orcamento_id,
            type(exc).__name__,
        )
    except RuntimeError as exc:
        logger.error(
            "Notificação do orçamento %s falhou ao entrar na fila (%s).",
            orcamento_id,
            type(exc).__name__,
        )
