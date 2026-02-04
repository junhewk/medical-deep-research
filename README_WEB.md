# Medical Deep Research - Modern Web Stack

This is the new modern web interface for Medical Deep Research, replacing the Flask-based web UI with a more maintainable and developer-friendly stack.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Next.js Frontend                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │ Lucia Auth  │  │  TanStack   │  │   React Components      │  │
│  │ (SQLite)    │  │   Query     │  │   - Research UI         │  │
│  └─────────────┘  └─────────────┘  │   - Progress Display    │  │
│                                     │   - Settings            │  │
│                                     └─────────────────────────┘  │
├─────────────────────────────────────────────────────────────────┤
│                         API Layer                                │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  Next.js API Routes → Python FastAPI (research engine)      ││
│  └─────────────────────────────────────────────────────────────┘│
├─────────────────────────────────────────────────────────────────┤
│                    Python Research Engine                        │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  DeepAgentResearchSystem + Medical Tools (existing code)    ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

## Tech Stack

| Component | Technology |
|-----------|------------|
| Frontend | Next.js 14 (App Router) |
| UI Components | shadcn/ui + Tailwind CSS |
| Authentication | Lucia Auth |
| Database | SQLite (better-sqlite3 + Drizzle ORM) |
| Data Fetching | TanStack Query |
| Backend API | FastAPI (Python) |
| Research Engine | DeepAgentResearchSystem (existing) |

## Benefits vs Flask Stack

| Aspect | Old (Flask) | New (Next.js) |
|--------|-------------|---------------|
| Installation | Complex Python deps, SQLCipher | `npm install` |
| Auth | Flask-Login, per-user DBs | Lucia Auth, single SQLite |
| Real-time | Flask-SocketIO | TanStack Query + polling |
| UI | Jinja2 templates | React components |
| DX | Template reload | Hot module replacement |
| Hosting | Self-hosted only | Vercel/Netlify possible |

## Quick Start

### Using the Startup Script

```bash
./start-web.sh
```

This will:
1. Install Node.js dependencies
2. Set up Python virtual environment
3. Start both the Next.js frontend and FastAPI backend

### Manual Start

**Terminal 1 - Next.js Frontend:**
```bash
cd web
npm install
npm run dev
# → http://localhost:3000
```

**Terminal 2 - FastAPI Backend:**
```bash
cd api
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload
# → http://localhost:8000
```

## Project Structure

```
medical-deep-research/
├── web/                          # Next.js frontend
│   ├── src/
│   │   ├── app/                  # Next.js App Router pages
│   │   │   ├── page.tsx          # Landing page
│   │   │   ├── auth/             # Login/register
│   │   │   ├── research/         # Research list, new, progress
│   │   │   ├── settings/         # AI provider settings
│   │   │   └── api/              # API routes
│   │   ├── components/
│   │   │   ├── ui/               # shadcn/ui components
│   │   │   └── research/         # Research-specific components
│   │   ├── db/
│   │   │   └── schema.ts         # Drizzle ORM schema
│   │   └── lib/
│   │       ├── auth.ts           # Lucia auth setup
│   │       ├── db.ts             # Database connection
│   │       └── research.ts       # TanStack Query hooks
│   ├── package.json
│   └── tailwind.config.ts
│
├── api/                          # FastAPI backend
│   ├── main.py                   # FastAPI app
│   └── requirements.txt
│
├── src/local_deep_research/      # Research engine (unchanged)
│   ├── deep_agent_system.py
│   ├── tools/
│   └── progress/
│
└── start-web.sh                  # Combined startup script
```

## Configuration

### Environment Variables

**web/.env:**
```env
DATABASE_PATH=./data/medical-research.db
PYTHON_API_URL=http://localhost:8000
NEXT_PUBLIC_API_URL=http://localhost:8000
```

**api/.env:**
```env
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_API_KEY=AIza...
OLLAMA_BASE_URL=http://localhost:11434
NCBI_API_KEY=
```

## Features

### Authentication
- User registration and login
- Session-based authentication via Lucia
- Secure password hashing with Argon2

### Research Interface
- **Research List**: View all past research with status badges
- **New Research**: PICO query builder or free-form input
- **Progress Tracking**: Real-time updates with:
  - Planning steps timeline
  - Agent status card
  - Tool execution log
  - Progress bar

### Settings
- Configure AI providers (OpenAI, Anthropic, Google, Ollama)
- Test API connections
- Set PubMed/NCBI API keys

## Development

### Database Commands

```bash
cd web

# Generate migration
npm run db:generate

# Push schema changes
npm run db:push
```

### Adding UI Components

This project uses shadcn/ui. To add new components:

```bash
cd web
npx shadcn-ui@latest add [component-name]
```

## API Endpoints

### Next.js API Routes

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/register` | Register new user |
| POST | `/api/auth/login` | Login |
| POST | `/api/auth/logout` | Logout |
| GET | `/api/research` | List user's research |
| POST | `/api/research` | Start new research |
| GET | `/api/research/[id]` | Get research progress |
| GET | `/api/settings` | Get user settings |
| POST | `/api/settings` | Save user settings |

### FastAPI Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | API info |
| GET | `/health` | Health check |
| POST | `/research` | Start research job |
| GET | `/research/{id}` | Get research progress |
| DELETE | `/research/{id}` | Cancel research |
| GET | `/research` | List all research jobs |

## Migration from Flask

The new web stack is independent of the Flask code. To migrate:

1. Use `start-web.sh` instead of `start.sh`
2. Register a new account (user data is not migrated)
3. Configure AI providers in Settings

The research engine (`src/local_deep_research/`) remains unchanged and is used by both stacks.

## License

MIT License - see [LICENSE](LICENSE)
