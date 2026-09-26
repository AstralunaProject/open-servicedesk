import getpass

import click

from .constants import ROLE_ADMIN, ROLES
from .extensions import db
from .models import User


def _prompt_password() -> str:
    while True:
        password = getpass.getpass("Senha: ")
        if len(password) < 8:
            click.echo("A senha precisa ter pelo menos 8 caracteres.", err=True)
            continue
        if password != getpass.getpass("Confirme a senha: "):
            click.echo("As senhas não conferem.", err=True)
            continue
        return password


def _find_user(email: str) -> User:
    user = db.session.scalar(db.select(User).where(User.email == email.strip().lower()))
    if user is None:
        raise click.ClickException("Usuário não encontrado.")
    return user


def register_cli(app) -> None:
    @app.cli.command("criar-usuario")
    @click.option("--email", prompt="E-mail")
    @click.option("--nome", prompt="Nome")
    @click.option("--perfil", type=click.Choice(list(ROLES)), default=ROLE_ADMIN, show_default=True)
    def create_user(email, nome, perfil):
        """Cria um usuário (por padrão, administrador)."""
        email = email.strip().lower()
        if db.session.scalar(db.select(User).where(User.email == email)):
            raise click.ClickException("Já existe um usuário com este e-mail.")
        user = User(name=nome.strip(), email=email, role=perfil)
        user.set_password(_prompt_password())
        db.session.add(user)
        db.session.commit()
        click.echo(f"Usuário {email} criado como {ROLES[perfil]}.")

    @app.cli.command("redefinir-senha")
    @click.argument("email")
    def reset_password(email):
        """Define uma nova senha e reativa o usuário."""
        user = _find_user(email)
        user.set_password(_prompt_password())
        user.active = True
        db.session.commit()
        click.echo("Senha redefinida.")

    @app.cli.command("backup")
    @click.option("--destino", default=None, help="Pasta de destino (padrão: DATA_DIR/backups)")
    def backup(destino):
        """Gera um .zip com o banco de dados e os anexos."""
        from .backup import create_backup

        try:
            click.echo(create_backup(destino))
        except RuntimeError as exc:
            raise click.ClickException(str(exc)) from exc

    @app.cli.command("manutencao")
    def maintenance():
        """Fecha chamados resolvidos antigos e lê a caixa de e-mail uma vez."""
        from .worker import run_maintenance

        result = run_maintenance(app)
        click.echo(f"Chamados fechados: {result['closed']} · E-mails processados: {result['emails']}")

    @app.cli.command("dados-demo")
    def demo_data():
        """Popula o sistema com dados fictícios para demonstração."""
        from .demo import load_demo_data

        password = load_demo_data()
        click.echo(f"Dados de demonstração criados. Usuários: *@demo.local / senha {password}")
