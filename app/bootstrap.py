from .extensions import db
from .models import Category, Group
from .sla import ensure_policies

DEFAULT_GROUPS = [
    ("Service Desk (N1)", "Primeiro atendimento: dúvidas, acessos, configurações simples."),
    ("Infraestrutura", "Servidores, rede, internet, backup e telefonia."),
    ("Sistemas", "ERP, sistemas internos e aplicativos corporativos."),
]

DEFAULT_CATEGORIES = [
    ("Acesso e senhas", "Criação de usuário, bloqueio, troca de senha", "Service Desk (N1)"),
    ("Computador / Notebook", "Lentidão, defeito, formatação, periféricos", "Service Desk (N1)"),
    ("E-mail", "Caixa de e-mail, Outlook, listas", "Service Desk (N1)"),
    ("Impressoras", "Impressão, digitalização, toner", "Service Desk (N1)"),
    ("Internet e rede", "Wi-Fi, cabo, VPN, lentidão da rede", "Infraestrutura"),
    ("Servidores e backup", "Pastas compartilhadas, restauração de arquivos", "Infraestrutura"),
    ("Telefonia", "Ramal, telefone IP, celular corporativo", "Infraestrutura"),
    ("Sistemas / ERP", "Erros e dúvidas em sistemas corporativos", "Sistemas"),
    ("Software", "Instalação e licenças de programas", "Service Desk (N1)"),
    ("Outros", "Assuntos que não se encaixam nas demais categorias", "Service Desk (N1)"),
]


def ensure_defaults() -> None:
    ensure_policies()
    db.session.commit()


def seed_catalog() -> None:
    """Cria grupos e categorias padrão (apenas se ainda não houver nenhum)."""
    if db.session.scalar(db.select(db.func.count(Group.id))) == 0:
        for name, description in DEFAULT_GROUPS:
            db.session.add(Group(name=name, description=description))
        db.session.flush()
    if db.session.scalar(db.select(db.func.count(Category.id))) == 0:
        groups = {g.name: g for g in db.session.scalars(db.select(Group))}
        for name, description, group in DEFAULT_CATEGORIES:
            db.session.add(Category(name=name, description=description, default_group=groups.get(group)))
    db.session.commit()
