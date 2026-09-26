# T.I Chamados

**English** · [Português](README.md)

Self-hosted IT service desk for small businesses: ticket submission and handling, SLAs, a knowledge base and an asset inventory. Runs on your own server (or any PC on the network), with no subscription and no data leaving your premises.

Think of it as a lean "ServiceNow": everything a team of 1 to 20 technicians needs day to day, installed in minutes.

> The user interface is in Brazilian Portuguese.

## Features

**User portal**
- Submit tickets with a category, attachments and simple questions ("who is affected?", "how urgent is it?")
- Follow up, chat with IT, reopen tickets and rate the service (1 to 5 stars)
- Searchable knowledge base so users can solve issues on their own

**Service desk (technicians)**
- Queues: my tickets, my groups' tickets, unassigned, SLA breached, on hold
- Incidents and requests, with automatic priority from the impact × urgency matrix (ITIL standard)
- Replies to the requester and **internal notes** (hidden from the user)
- Support groups with automatic routing by category
- Full change history for every ticket
- Tickets logged on behalf of a user (phone, walk-in or chat)
- CSV export (opens straight in Excel)

**SLA**
- First-response and resolution targets per priority
- Business-hours counting (configurable days and hours) or 24×7
- Automatic pause while the ticket is waiting on the requester or a third party

**Management**
- Dashboard with KPIs: open, overdue, average resolution time, SLA compliance, satisfaction
- Asset inventory (computers, printers, licenses…) linked to tickets
- User roles: Requester, Technician and Administrator

**E-mail and integrations**
- E-mail notifications (SMTP): ticket opened, reply, assignment, resolution
- Ticket creation by e-mail (IMAP): messages sent to `support@yourcompany` become tickets, and replies are threaded back into the right ticket
- Token-based REST API for bots (WhatsApp, Telegram), monitoring tools and scripts

**Operations**
- Built-in SQLite database (nothing to install); optional PostgreSQL via `DATABASE_URL`
- One-click backup (database + attachments in a `.zip`)
- Works offline on the intranet: no CDN, no external services
- Automatic light and dark themes, mobile friendly

## Installation

Pick one of the options below. In all of them, the first time you open the system you create the administrator account, and it comes preloaded with sample groups and categories.

### Option 1 — Docker (recommended)

Requires [Docker](https://docs.docker.com/get-docker/) with the Compose plugin.

```bash
git clone https://github.com/AstralunaProject/T.I-Chamados.git
cd T.I-Chamados
docker compose up -d
```

Open `http://SERVER-IP:8080`. Data is stored in the `chamados-dados` volume.

Set `BASE_URL` in `docker-compose.yml` to the address your users will use (it is the link sent in e-mails).

### Option 2 — Linux server (Ubuntu, Debian…)

Requires Python 3.10+.

```bash
sudo apt install -y python3 python3-venv git
git clone https://github.com/AstralunaProject/T.I-Chamados.git
cd T.I-Chamados
sudo ./scripts/instalar-linux.sh        # default port 8080; e.g.: sudo ./scripts/instalar-linux.sh 80
```

The script installs to `/opt/ti-chamados`, creates the `ti-chamados` service (starts on boot) and schedules a daily backup at 2 AM.

```bash
sudo systemctl status ti-chamados     # status
sudo journalctl -u ti-chamados -f     # logs
```

### Option 3 — Windows

1. Install [Python 3.10+](https://www.python.org/downloads/), checking **"Add python.exe to PATH"**.
2. Download the project (*Code → Download ZIP*) and extract it to a folder, e.g. `C:\TI-Chamados`.
3. To try it out, double-click `iniciar.bat`.
4. To keep it running as a service (starts with Windows), open PowerShell **as administrator** in the folder and run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\instalar-windows.ps1
```

### Option 4 — Manual (any OS)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python run.py
```

## Configuration

Most settings are managed in the web interface, under **Administração → Configurações** (Administration → Settings) and **SLA e horários** (SLA and business hours). Infrastructure parameters are set through environment variables or a `.env` file (see `.env.example`):

| Variable | Default | Description |
|---|---|---|
| `PORT` | `8080` | HTTP port |
| `BASE_URL` | — | Public address used in e-mail links |
| `CHAMADOS_DATA_DIR` | `./data` | Database, attachments, backups and secret key |
| `DATABASE_URL` | SQLite in `DATA_DIR` | e.g. `postgresql+psycopg://user:password@host/chamados` (install `psycopg`) |
| `MAX_UPLOAD_MB` | `20` | Maximum attachment size |
| `PROXY_FIX` | `0` | `1` when behind nginx/IIS/Caddy |
| `SESSION_COOKIE_SECURE` | `0` | `1` when access is HTTPS-only |

### E-mail

- **Microsoft 365:** SMTP `smtp.office365.com`, port 587, STARTTLS · IMAP `outlook.office365.com`, port 993. The mailbox must have SMTP AUTH enabled.
- **Google Workspace / Gmail:** SMTP `smtp.gmail.com`, port 587 · IMAP `imap.gmail.com`, port 993. Use an *app password*.

Use the **Enviar e-mail de teste** (send test e-mail) and **Testar conexão** (test connection) buttons to validate.

### HTTPS

For access from outside the local network, put a reverse proxy in front (Caddy, nginx, IIS) and set `PROXY_FIX=1` and `SESSION_COOKIE_SECURE=1`. Example with Caddy, which issues the certificate on its own:

```
helpdesk.yourcompany.com {
    reverse_proxy localhost:8080
}
```

## Backup and restore

- **From the interface:** Administração → Sistema e backup → *Baixar backup agora* (download backup now).
- **From the command line:** `flask --app wsgi backup` (saved to `data/backups/`).
  With Docker: `docker compose exec chamados flask --app wsgi backup`.

To restore, stop the system, extract the `.zip` into the data folder (replacing `chamados.db` and `anexos/`) and start it again.

## Useful commands

```bash
flask --app wsgi criar-usuario            # create a user (default: administrator)
flask --app wsgi redefinir-senha EMAIL    # reset someone's password
flask --app wsgi backup                   # create a .zip backup
flask --app wsgi manutencao               # close old resolved tickets and read the mailbox
flask --app wsgi dados-demo               # load fake data to explore the system
```

Use the virtual environment's Python (`.venv/bin/flask` on Linux, `.venv\Scripts\flask` on Windows).

## API

Generate a token under **Meu perfil → Token de API** (My profile → API token). It has the same permissions as your user.

```bash
# List tickets
curl -H "Authorization: Bearer YOUR_TOKEN" http://server:8080/api/v1/tickets?view=abertos

# Open a ticket on behalf of a user (technician token)
curl -X POST http://server:8080/api/v1/tickets \
  -H "Authorization: Bearer YOUR_TOKEN" -H "Content-Type: application/json" \
  -d '{"title": "No internet", "description": "Store 2", "category": "Internet e rede",
       "requester_email": "manager@company.com", "channel": "chat", "urgency": 1}'
```

| Method | Route | Description |
|---|---|---|
| `GET` | `/api/v1/me` | Token's user |
| `GET` | `/api/v1/tickets` | List (filters: `view`, `q`, `status`, `priority`, `group`, `category`, `page`, `per_page`) |
| `POST` | `/api/v1/tickets` | Open a ticket (`title`, `description`, `category`, `type`, `impact`, `urgency`, `channel`, `requester_email`) |
| `GET` | `/api/v1/tickets/<id>` | Details with comments |
| `PATCH` | `/api/v1/tickets/<id>` | Update (technicians): `status`, `assignee_id`, `group_id`, `impact`, `urgency`, `resolution_notes`… |
| `POST` | `/api/v1/tickets/<id>/comments` | Comment (`body`, `internal`) |

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

Layout:

```
app/
  models.py         tables (SQLAlchemy)
  constants.py      statuses, priorities, roles and other domain values
  services.py       ticket business rules (shared by web, API and e-mail)
  sla.py            deadlines and business hours
  mail_inbound.py   IMAP mailbox reader
  notifications.py  outgoing e-mails
  views/            web and API routes
  templates/        pages (Jinja2)
  static/           CSS and JS, no external dependencies
run.py              production server (Waitress)
```

## License

[MIT](LICENSE) © AstralunaProject
