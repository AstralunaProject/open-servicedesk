# T.I Chamados

[English](README.en.md) · **Português**

Central de serviços de T.I para pequenas empresas: abertura e atendimento de chamados, SLA, base de conhecimento e inventário de equipamentos. Roda no seu próprio servidor (ou em qualquer PC da rede), sem mensalidade e sem enviar dados para fora.

Pense em um "ServiceNow" enxuto: tudo o que uma equipe de 1 a 20 técnicos usa no dia a dia, instalado em minutos.

## Funcionalidades

**Portal do usuário**
- Abertura de chamados com categoria, anexos e perguntas simples ("quem é afetado?", "qual a urgência?")
- Acompanhamento, conversa com a T.I, reabertura e avaliação do atendimento (1 a 5 estrelas)
- Base de conhecimento pesquisável para o usuário resolver sozinho

**Atendimento (técnicos)**
- Filas: meus chamados, dos meus grupos, sem responsável, SLA vencido, em espera
- Incidentes e requisições, prioridade automática pela matriz impacto × urgência (padrão ITIL)
- Respostas ao solicitante e **notas internas** (invisíveis ao usuário)
- Grupos de atendimento com roteamento automático pela categoria
- Histórico completo de alterações de cada chamado
- Chamados registrados por telefone, presencial ou chat em nome do usuário
- Exportação para CSV (abre direto no Excel)

**SLA**
- Prazos de primeira resposta e de solução por prioridade
- Contagem em horário comercial (dias e horários configuráveis) ou 24×7
- Pausa automática enquanto o chamado aguarda o solicitante ou um terceiro

**Gestão**
- Painel com indicadores: abertos, atrasados, tempo médio de solução, cumprimento de SLA, satisfação
- Inventário de ativos (computadores, impressoras, licenças…) vinculado aos chamados
- Usuários com perfis Solicitante, Técnico e Administrador

**E-mail e integrações**
- Notificações por e-mail (SMTP): chamado aberto, resposta, atribuição, solução
- Abertura de chamados por e-mail (IMAP): mensagens para `suporte@suaempresa` viram chamados, e respostas voltam para o chamado certo
- API REST com token para integrar bots (WhatsApp, Telegram), monitoramento e scripts

**Operação**
- Banco SQLite embutido (nada para instalar); PostgreSQL opcional via `DATABASE_URL`
- Backup com um clique (banco + anexos em um `.zip`)
- Funciona offline na intranet: sem CDN, sem serviços externos
- Tema claro e escuro automático, funciona no celular

## Instalação

Escolha uma das opções. Em todas, ao abrir o sistema pela primeira vez você cria a conta de administrador e o sistema já vem com grupos e categorias de exemplo.

### Opção 1 — Docker (recomendado)

Requer [Docker](https://docs.docker.com/get-docker/) com o plugin Compose.

```bash
git clone https://github.com/AstralunaProject/T.I-Chamados.git
cd T.I-Chamados
docker compose up -d
```

Acesse `http://IP-DO-SERVIDOR:8080`. Os dados ficam no volume `chamados-dados`.

Ajuste `BASE_URL` em `docker-compose.yml` para o endereço que os usuários vão usar (é o link enviado nos e-mails).

### Opção 2 — Servidor Linux (Ubuntu, Debian…)

Requer Python 3.10+.

```bash
sudo apt install -y python3 python3-venv git
git clone https://github.com/AstralunaProject/T.I-Chamados.git
cd T.I-Chamados
sudo ./scripts/instalar-linux.sh        # porta padrão 8080; ex.: sudo ./scripts/instalar-linux.sh 80
```

O script instala em `/opt/ti-chamados`, cria o serviço `ti-chamados` (inicia junto com o servidor) e agenda um backup diário às 02h.

```bash
sudo systemctl status ti-chamados     # situação
sudo journalctl -u ti-chamados -f     # logs
```

### Opção 3 — Windows

1. Instale o [Python 3.10+](https://www.python.org/downloads/) marcando **"Add python.exe to PATH"**.
2. Baixe o projeto (botão *Code → Download ZIP*) e extraia em uma pasta, ex.: `C:\TI-Chamados`.
3. Para testar, dê dois cliques em `iniciar.bat`.
4. Para deixar rodando como serviço (inicia com o Windows), abra o PowerShell **como administrador** na pasta e execute:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\instalar-windows.ps1
```

### Opção 4 — Manual (qualquer sistema)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python run.py
```

## Configuração

O essencial é feito pela própria interface, em **Administração → Configurações** e **SLA e horários**. Parâmetros de infraestrutura ficam em variáveis de ambiente ou no arquivo `.env` (veja `.env.example`):

| Variável | Padrão | Descrição |
|---|---|---|
| `PORT` | `8080` | Porta HTTP |
| `BASE_URL` | — | Endereço público usado nos links dos e-mails |
| `CHAMADOS_DATA_DIR` | `./data` | Banco, anexos, backups e chave secreta |
| `DATABASE_URL` | SQLite em `DATA_DIR` | Ex.: `postgresql+psycopg://user:senha@host/chamados` (instale `psycopg`) |
| `MAX_UPLOAD_MB` | `20` | Tamanho máximo de anexos |
| `PROXY_FIX` | `0` | `1` quando atrás de nginx/IIS/Caddy |
| `SESSION_COOKIE_SECURE` | `0` | `1` quando o acesso for somente HTTPS |

### E-mail

- **Microsoft 365:** SMTP `smtp.office365.com`, porta 587, STARTTLS · IMAP `outlook.office365.com`, porta 993. A caixa precisa ter SMTP AUTH habilitado.
- **Google Workspace / Gmail:** SMTP `smtp.gmail.com`, porta 587 · IMAP `imap.gmail.com`, porta 993. Use uma *senha de app*.

Use os botões **Enviar e-mail de teste** e **Testar conexão** para validar.

### HTTPS

Para acesso fora da rede local, coloque um proxy reverso na frente (Caddy, nginx, IIS) e defina `PROXY_FIX=1` e `SESSION_COOKIE_SECURE=1`. Exemplo com Caddy, que emite o certificado sozinho:

```
chamados.suaempresa.com.br {
    reverse_proxy localhost:8080
}
```

## Backup e restauração

- **Pela interface:** Administração → Sistema e backup → *Baixar backup agora*.
- **Pela linha de comando:** `flask --app wsgi backup` (grava em `data/backups/`).
  No Docker: `docker compose exec chamados flask --app wsgi backup`.

Para restaurar, pare o sistema, extraia o `.zip` dentro da pasta de dados (substituindo `chamados.db` e `anexos/`) e inicie novamente.

## Comandos úteis

```bash
flask --app wsgi criar-usuario            # cria um usuário (padrão: administrador)
flask --app wsgi redefinir-senha EMAIL    # redefine a senha de alguém
flask --app wsgi backup                   # gera backup .zip
flask --app wsgi manutencao               # fecha resolvidos antigos e lê a caixa de e-mail
flask --app wsgi dados-demo               # popula com dados fictícios para conhecer o sistema
```

Use o Python do ambiente virtual (`.venv/bin/flask` no Linux, `.venv\Scripts\flask` no Windows).

## API

Gere um token em **Meu perfil → Token de API**. Ele tem as mesmas permissões do seu usuário.

```bash
# Listar chamados
curl -H "Authorization: Bearer SEU_TOKEN" http://servidor:8080/api/v1/tickets?view=abertos

# Abrir chamado em nome de um usuário (token de técnico)
curl -X POST http://servidor:8080/api/v1/tickets \
  -H "Authorization: Bearer SEU_TOKEN" -H "Content-Type: application/json" \
  -d '{"title": "Sem internet", "description": "Loja 2", "category": "Internet e rede",
       "requester_email": "gerente@empresa.com", "channel": "chat", "urgency": 1}'
```

| Método | Rota | Descrição |
|---|---|---|
| `GET` | `/api/v1/me` | Usuário do token |
| `GET` | `/api/v1/tickets` | Lista (filtros: `view`, `q`, `status`, `priority`, `group`, `category`, `page`, `per_page`) |
| `POST` | `/api/v1/tickets` | Abre chamado (`title`, `description`, `category`, `type`, `impact`, `urgency`, `channel`, `requester_email`) |
| `GET` | `/api/v1/tickets/<id>` | Detalhes com comentários |
| `PATCH` | `/api/v1/tickets/<id>` | Atualiza (técnicos): `status`, `assignee_id`, `group_id`, `impact`, `urgency`, `resolution_notes`… |
| `POST` | `/api/v1/tickets/<id>/comments` | Comenta (`body`, `internal`) |

## Desenvolvimento

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

Estrutura:

```
app/
  models.py         tabelas (SQLAlchemy)
  constants.py      status, prioridades, perfis e demais valores de domínio
  services.py       regras de negócio dos chamados (web, API e e-mail usam as mesmas)
  sla.py            prazos e horário comercial
  mail_inbound.py   leitura da caixa IMAP
  notifications.py  e-mails de saída
  views/            rotas web e API
  templates/        páginas (Jinja2)
  static/           CSS e JS, sem dependências externas
run.py              servidor de produção (Waitress)
```

## Licença

[MIT](LICENSE) © AstralunaProject
