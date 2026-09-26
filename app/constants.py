ROLE_ADMIN = "admin"
ROLE_AGENT = "agent"
ROLE_USER = "user"
ROLES = {
    ROLE_ADMIN: "Administrador",
    ROLE_AGENT: "Técnico",
    ROLE_USER: "Solicitante",
}

STATUS_NEW = "new"
STATUS_IN_PROGRESS = "in_progress"
STATUS_WAITING_USER = "waiting_user"
STATUS_WAITING_VENDOR = "waiting_vendor"
STATUS_RESOLVED = "resolved"
STATUS_CLOSED = "closed"
STATUS_CANCELLED = "cancelled"

STATUSES = {
    STATUS_NEW: "Novo",
    STATUS_IN_PROGRESS: "Em atendimento",
    STATUS_WAITING_USER: "Aguardando solicitante",
    STATUS_WAITING_VENDOR: "Aguardando terceiro",
    STATUS_RESOLVED: "Resolvido",
    STATUS_CLOSED: "Fechado",
    STATUS_CANCELLED: "Cancelado",
}
OPEN_STATUSES = (STATUS_NEW, STATUS_IN_PROGRESS, STATUS_WAITING_USER, STATUS_WAITING_VENDOR)
PAUSED_STATUSES = (STATUS_WAITING_USER, STATUS_WAITING_VENDOR)
DONE_STATUSES = (STATUS_RESOLVED, STATUS_CLOSED, STATUS_CANCELLED)

TYPES = {
    "incident": "Incidente",
    "request": "Requisição",
}

CHANNELS = {
    "portal": "Portal",
    "email": "E-mail",
    "phone": "Telefone",
    "chat": "Chat / WhatsApp",
    "walkin": "Presencial",
    "api": "API",
}

# Impacto e urgência: 1 = alto, 2 = médio, 3 = baixo (mesma escala do ITIL/ServiceNow)
IMPACTS = {1: "Alto", 2: "Médio", 3: "Baixo"}
URGENCIES = {1: "Alta", 2: "Média", 3: "Baixa"}
# Rótulos amigáveis mostrados ao solicitante no portal
IMPACTS_FRIENDLY = {3: "Só eu", 2: "Meu setor / várias pessoas", 1: "A empresa inteira"}
URGENCIES_FRIENDLY = {3: "Posso aguardar", 2: "Atrapalha meu trabalho", 1: "Estou parado(a)"}

PRIORITIES = {1: "Crítica", 2: "Alta", 3: "Média", 4: "Baixa"}

RESOLUTION_CODES = {
    "solved": "Solucionado",
    "workaround": "Solução de contorno",
    "no_action": "Sem necessidade de ação",
    "duplicate": "Duplicado",
    "not_reproducible": "Não reproduzível",
    "user_error": "Orientação ao usuário",
}

ASSET_TYPES = [
    "Desktop",
    "Notebook",
    "Monitor",
    "Impressora",
    "Servidor",
    "Rede",
    "Celular",
    "Tablet",
    "Telefone",
    "Software / Licença",
    "Periférico",
    "Outro",
]
ASSET_STATUSES = {
    "in_use": "Em uso",
    "stock": "Em estoque",
    "maintenance": "Em manutenção",
    "retired": "Descartado",
}


def calc_priority(impact: int, urgency: int) -> int:
    """Matriz impacto x urgência → prioridade 1 (crítica) a 4 (baixa)."""
    total = int(impact) + int(urgency)
    return {2: 1, 3: 2, 4: 3}.get(total, 4)
