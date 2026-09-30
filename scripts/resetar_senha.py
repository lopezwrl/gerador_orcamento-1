"""Redefine a senha de um usuário (por exemplo, o admin).

Uso, na raiz do projeto:
    .\\.venv\\Scripts\\python.exe -m scripts.resetar_senha
"""
import getpass

from orcatech.app import app
from orcatech.models import Usuario


def _aplicar_senha(usuario, senha):
    # 1) usa o método do próprio modelo, se existir (mesmo hash do login)
    for nome in ("definir_senha", "set_password", "set_senha"):
        if hasattr(usuario, nome):
            getattr(usuario, nome)(senha)
            return True
    # 2) senão, grava o hash padrão do Werkzeug no campo encontrado
    from werkzeug.security import generate_password_hash

    for campo in ("senha_hash", "password_hash", "senha"):
        if hasattr(usuario, campo):
            setattr(usuario, campo, generate_password_hash(senha))
            return True
    return False


def main():
    with app.app_context():
        usuarios = Usuario.query.order_by(Usuario.id).all()
        if not usuarios:
            print("Não há usuários no banco. Rode: python -m scripts.init_db")
            return

        print("Usuários cadastrados:")
        for u in usuarios:
            print(f"  - {u.email}  (papel: {getattr(u, 'papel', '?')})")

        email = input("\nE-mail do usuário a redefinir: ").strip().lower()
        usuario = next((u for u in usuarios if (u.email or "").lower() == email), None)
        if usuario is None:
            print("Usuário não encontrado. Nada foi alterado.")
            return

        senha = getpass.getpass("Nova senha (mínimo 12 caracteres): ")
        if len(senha) < 12:
            print("A senha precisa ter pelo menos 12 caracteres. Nada foi alterado.")
            return
        if senha != getpass.getpass("Repita a nova senha: "):
            print("As senhas não conferem. Nada foi alterado.")
            return

        if not _aplicar_senha(usuario, senha):
            print("Não encontrei o campo de senha no modelo Usuario. Nada foi alterado.")
            return

        Usuario.query.session.commit()
        print(f"Senha de {usuario.email} redefinida com sucesso.")


if __name__ == "__main__":
    main()
