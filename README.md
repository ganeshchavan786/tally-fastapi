# Tally FastAPI Database Loader

Sync Tally ERP data to SQLite database using Python FastAPI.

## Features

- ✅ **Tally Connection** - XML communication with Tally ERP 9/Prime
- ✅ **SQLite Database** - Lightweight, portable database
- ✅ **REST API** - Full API for data access
- ✅ **MVC Architecture** - Clean, maintainable code structure
- ✅ **Debug Mode** - Verbose logging for troubleshooting
- ✅ **Health Checks** - Monitor Tally and database status
- ✅ **Error Recovery** - Automatic retry with circuit breaker

## Quick Start

### 1. Install Dependencies

```bash
cd tally-fastapi
pip install -r requirements.txt
```

### 2. Configure

Edit `config.yaml`:

```yaml
tally:
  server: localhost
  port: 9000
  from_date: "2025-04-01"
  to_date: "2026-03-31"

database:
  path: "./tally.db"
```

### 3. Run

```bash
python run.py
```

Server starts at: http://localhost:8000

## API Endpoints

### Sync
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/sync/full` | POST | Start full sync |
| `/api/sync/status` | GET | Get sync status |
| `/api/sync/cancel` | POST | Cancel sync |

### Data
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/data/groups` | GET | Get all groups |
| `/api/data/ledgers` | GET | Get all ledgers |
| `/api/data/vouchers` | GET | Get vouchers |
| `/api/data/stock-items` | GET | Get stock items |
| `/api/data/query` | POST | Execute SQL query |

### Health
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Full health check |
| `/api/health/tally` | GET | Tally status |
| `/api/health/database` | GET | Database status |

### Debug
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/debug/enable` | POST | Enable debug mode |
| `/api/debug/disable` | POST | Disable debug mode |
| `/api/debug/status` | GET | Get debug status |

### Logs
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/logs` | GET | Get recent logs |
| `/api/logs/download` | GET | Download log file |
| `/api/logs/clear` | DELETE | Clear logs |

## Project Structure (MVC)

```
tally-fastapi/
├── app/
│   ├── controllers/     # API endpoints
│   ├── models/          # Pydantic models
│   ├── views/           # Response formatters
│   ├── services/        # Business logic
│   ├── repositories/    # Data access
│   ├── middleware/      # Error handling
│   └── utils/           # Helpers, logger
├── static/              # CSS, JS
├── templates/           # HTML templates
├── logs/                # Log files
├── config.yaml          # Configuration
├── requirements.txt     # Dependencies
└── run.py               # Entry point
```

## API Documentation

Interactive API docs available at:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## License

MIT License
