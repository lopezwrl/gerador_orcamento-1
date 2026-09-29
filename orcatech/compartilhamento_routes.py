from datetime import datetime, timezone

from flask import Blueprint, abort, render_template

from .auth_routes import limiter
from .models import Orcamento


compartilhamento_bp = Blueprint("compartilhamento", __name__)

STATUS_COMPARTILHAVEIS = {
    "aguardando_aprovacao",
    "aprovado",
    "reprovado",
    "compra_realizada",
}


@compartilhamento_bp.after_request
def impedir_indexacao_ou_cache(response):
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    response.headers["Cache-Control"] = "no-store, private"
    return response


@compartilhamento_bp.route("/p/<token>")
@limiter.limit("60 per hour")
def publico(token):
    orcamento = Orcamento.query.filter_by(share_token=token).first()
    agora = datetime.now(timezone.utc).replace(tzinfo=None)
    if (
        not orcamento
        or orcamento.share_revogado
        or not orcamento.share_expira_em
        or orcamento.share_expira_em <= agora
        or orcamento.status not in STATUS_COMPARTILHAVEIS
    ):
        abort(404)

    return render_template("orcamento_publico.html", orcamento=orcamento)
