"""
init_db.py — cria as tabelas do banco e o primeiro usuário admin.

Rodar UMA VEZ:
    python -m scripts.init_db
"""

import getpass

from orcatech.app import app
from orcatech.models import db, Usuario
from sqlalchemy import inspect


def main():
    with app.app_context():
        if not inspect(db.engine).has_table("usuarios"):
            raise RuntimeError(
                "As tabelas ainda não existem. Execute `flask --app "
                "orcatech.app:app db upgrade` antes deste comando."
            )

        if Usuario.query.filter_by(papel="admin").first():
            print("Já existe um admin cadastrado. Nada a fazer.")
            return

        print("\nVamos criar o primeiro usuário admin.")
        nome = input("Nome: ").strip()
        email = input("Email: ").strip()
        senha = getpass.getpass("Senha: ")
        while len(senha) < 12:
            print("A senha deve ter pelo menos 12 caracteres.")
            senha = getpass.getpass("Senha: ")

        admin = Usuario(nome=nome, email=email, papel="admin")
        admin.set_senha(senha)
        db.session.add(admin)
        db.session.commit()
        print(f"Admin '{nome}' criado com sucesso.")


if __name__ == "__main__":
    main()
