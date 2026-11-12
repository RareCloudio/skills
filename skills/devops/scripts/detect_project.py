#!/usr/bin/env python3
"""Describe a project folder for deployment: what runs, what it stores, what it needs.

What it does: walks the folder (bounded in depth and file count, skipping dependency,
version control and build folders), reads manifests, lockfiles, container and compose
files, process files, provider config files and a bounded sample of source files, and
prints one JSON object. Several apps in one folder are counted and listed one by one.
Whatever it cannot tell is written under "not_determined" in plain words.
What it never does: execute, write, move or delete anything in the project; follow a
symbolic link; open anything but regular files; print the value of an environment
variable or of a line in an env file (names only); read wp-config.php; use the network.
Residual: names are printed (program names, flag names, a recognised runner's target such as
server.js or app:app, UPPER_SNAKE assignment and variable names, service names, image names,
mounted paths); a secret used as one of those names would print. Likewise, a secret written
in a target position would print (where a recognised runner expects its script, module or app).

Usage: python detect_project.py <path> [--max-files N] [--max-depth N]
"""
from __future__ import annotations

import argparse
import json
import os
import ipaddress
import re
import shlex
import stat
import sys
from dataclasses import dataclass, field

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.9 and 3.10: TOML files are listed as not read
    tomllib = None

DEFAULT_MAX_FILES = 20000
DEFAULT_MAX_DEPTH = 10
MAX_READ_BYTES = 256 * 1024
MAX_SOURCE_FILES = 3000
MAX_TOTAL_READ = 32 * 1024 * 1024
MAX_ENV_NAMES = 300
MAX_PER_APP = 100       # entries per key and app; the rest are counted, not listed
MAX_MERGED = 200        # entries per key in the combined top-level lists
MAX_APPS_LISTED = 50
MAX_FILE_NOTES = 30
MAX_APP_NOTES = 20
# Skipped by name like dependency folders, but a project's own code can live in them.
NOTED_SKIPS = {"build", "out", "dist", "target", "env"}

SKIP_DIRS = {
    "node_modules", "vendor", ".git", ".hg", ".svn", ".venv", "venv", ".env", "env", "__pycache__",
    ".tox", ".nox", ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build", "out", ".next",
    ".nuxt", ".svelte-kit", ".output", ".astro", ".vercel", ".netlify", "target", "coverage", ".cache",
    ".parcel-cache", ".turbo", ".terraform", "bower_components", ".gradle", ".idea", "site-packages",
    ".bundle", ".yarn", ".pnpm-store", ".expo", ".dart_tool", "Pods", "DerivedData",
}
# Hidden folders are tool settings and caches; only these are read.
HIDDEN_READ = {".github", ".do", ".ebextensions", ".platform", ".circleci", ".devcontainer", ".gitlab", ".kamal"}
NOT_APP_DIRS = {"docs", "doc", "test", "tests", "e2e", "examples", "example", "fixtures", "samples", "spec"}
PRIMARY_MARKERS = {
    "package.json", "composer.json", "pyproject.toml", "requirements.txt", "setup.py", "Pipfile", "Gemfile",
    "go.mod", "Cargo.toml", "pom.xml", "build.gradle", "build.gradle.kts", "manage.py", "artisan",
    "wp-config.php", "deno.json", "deno.jsonc", "mix.exs",
}
LOCKFILES = {
    "package-lock.json": "npm", "npm-shrinkwrap.json": "npm", "yarn.lock": "Yarn", "pnpm-lock.yaml": "pnpm",
    "bun.lockb": "Bun", "bun.lock": "Bun", "composer.lock": "Composer", "poetry.lock": "Poetry",
    "uv.lock": "uv", "Pipfile.lock": "Pipenv", "pdm.lock": "PDM", "Gemfile.lock": "Bundler",
    "Cargo.lock": "Cargo", "go.sum": "Go modules", "mix.lock": "Mix",
}
EXT_LANG = {
    ".py": "Python", ".js": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript", ".jsx": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".mts": "TypeScript", ".php": "PHP", ".rb": "Ruby",
    ".go": "Go", ".rs": "Rust", ".java": "Java", ".kt": "Kotlin", ".cs": "C#", ".ex": "Elixir",
    ".exs": "Elixir", ".html": "HTML", ".htm": "HTML", ".vue": "JavaScript", ".svelte": "JavaScript",
}
SOURCE_EXTS = set(EXT_LANG) - {".html", ".htm"}
MARKER_LANG = {
    "package.json": "JavaScript", "composer.json": "PHP", "artisan": "PHP", "wp-config.php": "PHP",
    "pyproject.toml": "Python", "requirements.txt": "Python", "setup.py": "Python", "Pipfile": "Python",
    "manage.py": "Python", "Gemfile": "Ruby", "go.mod": "Go", "Cargo.toml": "Rust", "pom.xml": "Java",
    "build.gradle": "Java", "build.gradle.kts": "Kotlin", "deno.json": "TypeScript", "deno.jsonc": "TypeScript",
    "mix.exs": "Elixir",
}
KEYS = ["languages", "frameworks", "entry_points", "datastores", "background_work", "state_on_disk", "ports",
        "env_vars", "container_files", "existing_hosting", "runtime_needs", "package_managers"]

# Dependency rules: (ecosystem, name, output key, text). A name ending in "*" matches a prefix.
WS = "WebSocket connections ({d}): long-lived connections, so the process must stay up"
BOT = "chat bot ({d}): a long-running process that keeps a connection open; polling needs no public port"
BROWSER = "headless browser ({d}): needs extra memory and system libraries on the server"
GPU = "GPU library ({d}); whether a GPU is required is not determined"
MODEL = "calls a model API or runs a model ({d})"
RUNS_CODE = "runs code at run time in a sandbox or interpreter ({d}); check how it is isolated"
SQL_VIA = "SQL database through {d} (engine not determined from the dependency)"
RULES: list[tuple[str, str, str, str]] = []


def _rules(eco: str, key: str, text: str, names: str) -> None:
    RULES.extend((eco, n, key, text) for n in names.split())


# JavaScript and TypeScript (npm)
for _n, _t in [("next", "Next.js"), ("nuxt", "Nuxt"), ("astro", "Astro"), ("@sveltejs/kit", "SvelteKit"),
               ("@remix-run/*", "Remix"), ("gatsby", "Gatsby"), ("@angular/core", "Angular"), ("vite", "Vite"),
               ("react-scripts", "Create React App"), ("vue", "Vue"), ("react", "React"), ("svelte", "Svelte"),
               ("express", "Express"), ("fastify", "Fastify"), ("koa", "Koa"), ("@nestjs/core", "NestJS"),
               ("hono", "Hono"), ("@hapi/hapi", "hapi"), ("@adonisjs/core", "AdonisJS"),
               ("@docusaurus/core", "Docusaurus"), ("@11ty/eleventy", "Eleventy")]:
    RULES.append(("npm", _n, "frameworks", _t))
_rules("npm", "datastores", "PostgreSQL client ({d})", "pg postgres @neondatabase/serverless @vercel/postgres")
_rules("npm", "datastores", "MySQL client ({d})", "mysql mysql2 @planetscale/database")
_rules("npm", "datastores", "MongoDB client ({d})", "mongodb mongoose")
_rules("npm", "datastores", "Redis client ({d})", "redis ioredis @upstash/redis @vercel/kv")
_rules("npm", "datastores", "Supabase (hosted Postgres, auth and file storage) through {d}",
       "@supabase/supabase-js @supabase/ssr")
_rules("npm", "datastores", "Firebase ({d})", "firebase firebase-admin")
_rules("npm", "datastores", "SQLite ({d})", "better-sqlite3 sqlite3 sqlite")
_rules("npm", "state_on_disk", "SQLite database file on local disk ({d})", "better-sqlite3 sqlite3 sqlite")
_rules("npm", "datastores", "SQLite or a hosted libSQL database ({d})", "@libsql/client")
_rules("npm", "datastores", "a database through Prisma ({d}); see prisma/schema.prisma", "@prisma/client prisma")
_rules("npm", "datastores", SQL_VIA, "drizzle-orm typeorm sequelize knex kysely @mikro-orm/core")
_rules("npm", "datastores", "Elasticsearch ({d})", "@elastic/elasticsearch")
_rules("npm", "datastores", "RabbitMQ ({d})", "amqplib amqp-connection-manager")
_rules("npm", "datastores", "Kafka ({d})", "kafkajs")
_rules("npm", "datastores", "S3-compatible object storage ({d})", "@aws-sdk/client-s3 aws-sdk")
_rules("npm", "datastores", "vector database ({d})", "@pinecone-database/pinecone @qdrant/js-client-rest chromadb")
_rules("npm", "background_work", "job queue on Redis ({d}): needs a worker process", "bull bullmq bee-queue")
_rules("npm", "background_work", "job queue on MongoDB ({d}): needs a worker process", "agenda")
_rules("npm", "background_work", "job queue on PostgreSQL ({d}): needs a worker process", "pg-boss graphile-worker")
_rules("npm", "background_work", "in-process scheduler ({d}): runs only while the process is up",
       "node-cron cron node-schedule croner")
_rules("npm", "background_work", "Temporal worker ({d})", "@temporalio/worker")
_rules("npm", "runtime_needs", WS, "socket.io ws @fastify/websocket uWebSockets.js @hocuspocus/server y-websocket")
_rules("npm", "runtime_needs", BOT,
       "discord.js telegraf grammy node-telegram-bot-api @slack/bolt whatsapp-web.js @whiskeysockets/baileys")
_rules("npm", "runtime_needs", BROWSER, "puppeteer puppeteer-core playwright playwright-core "
       "selenium-webdriver @sparticuz/chromium")
_rules("npm", "runtime_needs", GPU, "@tensorflow/tfjs-node-gpu")
_rules("npm", "runtime_needs", MODEL, "openai @anthropic-ai/sdk ai @ai-sdk/* langchain @langchain/* ollama "
       "@google/generative-ai @google/genai groq-sdk cohere-ai @mistralai/mistralai")
_rules("npm", "runtime_needs", RUNS_CODE, "e2b @e2b/code-interpreter vm2 isolated-vm")
_rules("npm", "runtime_needs", "native image library ({d}): installs a platform-specific binary", "sharp")
_rules("npm", "state_on_disk", "file uploads through {d}: stored on local disk unless configured otherwise",
       "multer formidable busboy")
_rules("npm", "runtime_needs", "desktop app ({d}): not a web server", "electron")

# PHP (Composer)
for _n, _t in [("laravel/framework", "Laravel"), ("symfony/framework-bundle", "Symfony"), ("slim/slim", "Slim"),
               ("cakephp/cakephp", "CakePHP"), ("drupal/core", "Drupal"), ("drupal/core-recommended", "Drupal"),
               ("roots/wordpress", "WordPress"), ("johnpbloch/wordpress", "WordPress")]:
    RULES.append(("php", _n, "frameworks", _t))
_rules("php", "datastores", "Redis client ({d})", "predis/predis")
_rules("php", "datastores", "MongoDB client ({d})", "mongodb/mongodb mongodb/laravel-mongodb")
_rules("php", "datastores", "S3-compatible object storage ({d})", "league/flysystem-aws-s3-v3 aws/aws-sdk-php")
_rules("php", "background_work", "Laravel Horizon queue workers ({d}): needs Redis and a long-running process",
       "laravel/horizon")
_rules("php", "runtime_needs", WS, "laravel/reverb beyondcode/laravel-websockets cboden/ratchet")
_rules("php", "runtime_needs", BROWSER, "spatie/browsershot")
_rules("php", "runtime_needs", MODEL, "openai-php/client openai-php/laravel")
_rules("php", "runtime_needs", BOT, "irazasyed/telegram-bot-sdk team-reflex/discord-php")

# Python
for _n, _t in [("django", "Django"), ("flask", "Flask"), ("fastapi", "FastAPI"), ("starlette", "Starlette"),
               ("streamlit", "Streamlit"), ("gradio", "Gradio"), ("aiohttp", "aiohttp"), ("tornado", "Tornado"),
               ("sanic", "Sanic"), ("litestar", "Litestar"), ("quart", "Quart"), ("dash", "Dash"),
               ("chainlit", "Chainlit"), ("gunicorn", "gunicorn (WSGI server)"), ("uvicorn", "uvicorn (ASGI server)"),
               ("hypercorn", "hypercorn (ASGI server)"), ("daphne", "daphne (ASGI server)"),
               ("waitress", "waitress (WSGI server)"), ("mkdocs", "MkDocs")]:
    RULES.append(("py", _n, "frameworks", _t))
_rules("py", "datastores", "PostgreSQL client ({d})", "psycopg psycopg2 psycopg2-binary asyncpg")
_rules("py", "datastores", "MySQL client ({d})", "pymysql mysqlclient mysql-connector-python aiomysql")
_rules("py", "datastores", "MongoDB client ({d})", "pymongo motor mongoengine beanie")
_rules("py", "datastores", "Redis client ({d})", "redis aioredis")
_rules("py", "datastores", SQL_VIA, "sqlalchemy sqlmodel peewee tortoise-orm")
_rules("py", "datastores", "Supabase (hosted Postgres, auth and file storage) through {d}", "supabase")
_rules("py", "datastores", "Firebase ({d})", "firebase-admin")
_rules("py", "datastores", "Elasticsearch ({d})", "elasticsearch")
_rules("py", "datastores", "RabbitMQ ({d})", "pika aio-pika")
_rules("py", "datastores", "Kafka ({d})", "kafka-python confluent-kafka aiokafka")
_rules("py", "datastores", "AWS services, possibly S3 storage ({d})", "boto3")
_rules("py", "datastores", "vector database ({d})", "qdrant-client pinecone pinecone-client pymilvus weaviate-client")
_rules("py", "datastores", "vector store on local disk ({d})", "chromadb faiss-cpu faiss-gpu")
_rules("py", "state_on_disk", "vector store files on local disk unless configured otherwise ({d})",
       "chromadb faiss-cpu faiss-gpu")
_rules("py", "background_work", "Celery workers ({d}): need a broker such as Redis or RabbitMQ", "celery")
_rules("py", "background_work", "Celery beat scheduler ({d})", "django-celery-beat")
_rules("py", "background_work", "job queue workers ({d})", "rq dramatiq huey arq taskiq django-q django-q2")
_rules("py", "background_work", "in-process scheduler ({d}): runs only while the process is up",
       "apscheduler schedule")
_rules("py", "background_work", "Temporal worker ({d})", "temporalio")
_rules("py", "runtime_needs", BOT, "python-telegram-bot aiogram pytelegrambotapi telethon pyrogram discord-py "
       "nextcord py-cord disnake slack-bolt matrix-nio")
_rules("py", "runtime_needs", WS, "websockets python-socketio flask-socketio channels")
_rules("py", "runtime_needs", BROWSER, "playwright selenium pyppeteer undetected-chromedriver")
_rules("py", "runtime_needs", GPU, "torch tensorflow jax cupy* vllm xformers bitsandbytes onnxruntime-gpu "
       "diffusers accelerate nvidia-*")
_rules("py", "runtime_needs", MODEL, "openai anthropic langchain* llama-index* litellm ollama google-generativeai "
       "google-genai transformers groq mistralai cohere")
_rules("py", "runtime_needs", RUNS_CODE, "e2b e2b-code-interpreter open-interpreter langchain-experimental")

# Ruby, Go, Rust, Elixir
for _n, _t in [("rails", "Rails"), ("sinatra", "Sinatra"), ("hanami", "Hanami"), ("jekyll", "Jekyll"),
               ("puma", "puma (web server)")]:
    RULES.append(("ruby", _n, "frameworks", _t))
_rules("ruby", "datastores", "PostgreSQL client ({d})", "pg")
_rules("ruby", "datastores", "MySQL client ({d})", "mysql2 trilogy")
_rules("ruby", "datastores", "SQLite ({d})", "sqlite3")
_rules("ruby", "datastores", "Redis client ({d})", "redis")
_rules("ruby", "background_work", "Sidekiq workers ({d}): need Redis and a worker process", "sidekiq")
_rules("ruby", "background_work", "job queue workers ({d})", "resque good_job delayed_job_active_record solid_queue que")
_rules("ruby", "background_work", "cron schedule ({d})", "whenever")
_rules("ruby", "runtime_needs", BOT, "discordrb telegram-bot-ruby slack-ruby-bot")
_rules("ruby", "runtime_needs", BROWSER, "ferrum cuprite grover")
for _n, _t in [("github.com/gin-gonic/gin", "Gin"), ("github.com/labstack/echo*", "Echo"),
               ("github.com/gofiber/fiber*", "Fiber"), ("github.com/go-chi/chi*", "chi")]:
    RULES.append(("go", _n, "frameworks", _t))
_rules("go", "datastores", "PostgreSQL client ({d})", "github.com/jackc/pgx* github.com/lib/pq")
_rules("go", "datastores", "MySQL client ({d})", "github.com/go-sql-driver/mysql")
_rules("go", "datastores", "MongoDB client ({d})", "go.mongodb.org/mongo-driver*")
_rules("go", "datastores", "Redis client ({d})", "github.com/redis/go-redis* github.com/go-redis/redis*")
_rules("go", "datastores", "SQLite ({d})", "github.com/mattn/go-sqlite3 modernc.org/sqlite")
_rules("go", "runtime_needs", WS, "github.com/gorilla/websocket nhooyr.io/websocket github.com/coder/websocket")
_rules("go", "runtime_needs", BOT, "github.com/bwmarrin/discordgo github.com/go-telegram-bot-api* "
       "gopkg.in/telebot* github.com/go-telegram/bot")
_rules("go", "runtime_needs", BROWSER, "github.com/chromedp/chromedp github.com/go-rod/rod")
_rules("go", "background_work", "in-process scheduler ({d})", "github.com/robfig/cron*")
_rules("go", "background_work", "job queue on Redis ({d}): needs a worker process", "github.com/hibiken/asynq")
for _n, _t in [("actix-web", "Actix Web"), ("axum", "Axum"), ("rocket", "Rocket"), ("warp", "warp")]:
    RULES.append(("rust", _n, "frameworks", _t))
_rules("rust", "datastores", SQL_VIA, "sqlx diesel sea-orm")
_rules("rust", "datastores", "PostgreSQL client ({d})", "tokio-postgres postgres")
_rules("rust", "datastores", "Redis client ({d})", "redis")
_rules("rust", "datastores", "SQLite ({d})", "rusqlite")
_rules("rust", "runtime_needs", WS, "tokio-tungstenite tungstenite")
_rules("rust", "runtime_needs", BOT, "serenity teloxide poise")
RULES.append(("elixir", "phoenix", "frameworks", "Phoenix"))
# Java and Kotlin: plain substring search in pom.xml and build.gradle
JAVA_HINTS = [("spring-boot", "frameworks", "Spring Boot"), ("quarkus", "frameworks", "Quarkus"),
              ("micronaut", "frameworks", "Micronaut"), ("io.ktor", "frameworks", "Ktor"),
              ("org.postgresql", "datastores", "PostgreSQL client (org.postgresql)"),
              ("mysql-connector", "datastores", "MySQL client (mysql-connector)"),
              ("spring-boot-starter-data-redis", "datastores", "Redis client (spring-boot-starter-data-redis)"),
              ("spring-boot-starter-websocket", "runtime_needs", WS.format(d="spring-boot-starter-websocket"))]

WEB_FRAMEWORKS = {"Next.js", "Nuxt", "SvelteKit", "Remix", "Express", "Fastify", "Koa", "NestJS", "Hono", "hapi",
                  "AdonisJS", "Laravel", "Symfony", "Slim", "CakePHP", "Drupal", "WordPress", "Django", "Flask",
                  "FastAPI", "Starlette", "Streamlit", "Gradio", "aiohttp", "Tornado", "Sanic", "Litestar", "Quart",
                  "Dash", "Chainlit", "Rails", "Sinatra", "Hanami", "Gin", "Echo", "Fiber", "chi", "Actix Web",
                  "Axum", "Rocket", "warp", "Phoenix", "Spring Boot", "Quarkus", "Micronaut", "Ktor"}
STATIC_GENERATORS = {"Gatsby", "Docusaurus", "Eleventy", "Jekyll", "MkDocs", "Hugo"}
SPA_BUILDERS = {"Vite", "Create React App", "Angular"}
# Served through PHP-FPM or an Apache module behind a web server, so the app has no port of its own.
PHP_FRAMEWORKS = {"Laravel", "Symfony", "Slim", "CakePHP", "Drupal", "WordPress"}

IMAGE_STORES = [
    ({"postgres", "postgresql", "postgis", "timescaledb", "timescaledb-ha", "pgvector"}, "PostgreSQL"),
    ({"mysql", "mysql-server"}, "MySQL"), ({"mariadb"}, "MariaDB"), ({"mongo", "mongodb"}, "MongoDB"),
    ({"redis", "valkey", "redis-stack", "redis-stack-server", "keydb", "dragonfly"}, "Redis"),
    ({"memcached"}, "Memcached"), ({"rabbitmq"}, "RabbitMQ"), ({"elasticsearch", "opensearch"}, "Elasticsearch"),
    ({"clickhouse-server", "clickhouse"}, "ClickHouse"), ({"nats"}, "NATS"),
    ({"kafka", "cp-kafka", "redpanda"}, "Kafka"), ({"meilisearch"}, "Meilisearch"), ({"typesense"}, "Typesense"),
    ({"qdrant", "weaviate", "chroma", "milvus"}, "vector database"), ({"neo4j"}, "Neo4j"),
    ({"couchdb"}, "CouchDB"), ({"cassandra"}, "Cassandra"), ({"influxdb"}, "InfluxDB"),
]
UPLOAD_DIRS = {"uploads", "upload", "user-uploads", "user_uploads", "media"}
PROXY_IMAGES = {"nginx", "caddy", "traefik", "haproxy", "httpd", "apache"}
WORKER_RE = re.compile(r"(?i)(?<![a-z])(worker|workers|celery|sidekiq|queue|horizon|rq|dramatiq|beat|cron|"
                       r"crond|scheduler|schedule|jobs?|consumer)(?![a-z])")

ENV_NAME = r"([A-Z][A-Z0-9_]{1,79})"
ENV_CODE_RES = [re.compile(p) for p in [
    r"process\.env\." + ENV_NAME, r"process\.env\[\s*['\"]" + ENV_NAME, r"import\.meta\.env\." + ENV_NAME,
    r"Deno\.env\.get\(\s*['\"]" + ENV_NAME, r"Bun\.env\." + ENV_NAME,
    r"os\.environ\[\s*['\"]" + ENV_NAME, r"os\.environ\.get\(\s*['\"]" + ENV_NAME,
    r"os\.getenv\(\s*['\"]" + ENV_NAME, r"(?<![\w.])env(?:\.\w+)?\(\s*['\"]" + ENV_NAME,
    r"getenv\(\s*['\"]" + ENV_NAME, r"_ENV\[\s*['\"]" + ENV_NAME, r"ENV\[\s*['\"]" + ENV_NAME,
    r"ENV\.fetch\(\s*['\"]" + ENV_NAME, r"os\.(?:Getenv|LookupEnv)\(\s*\"" + ENV_NAME,
    r"env::var\(\s*\"" + ENV_NAME, r"System\.getenv\(\s*\"" + ENV_NAME,
]]
PORT_LISTEN_RE = re.compile(r"\.listen\(\s*(\d{2,5})\b")
PORT_DEFAULT_RE = re.compile(r"PORT['\"]?\s*\)?\s*(?:\|\||\?\?|or|,)\s*['\"]?(\d{2,5})\b")
PORT_KWARG_RE = re.compile(r"\b(?:uvicorn\.run|app\.run|\.run)\([^)]*\bport\s*=\s*(\d{2,5})")
PORT_ENV_RE = re.compile(r"process\.env\.PORT|os\.environ(?:\.get)?\(?\[?\s*['\"]PORT|getenv\(\s*['\"]PORT|"
                         r"\$\{?PORT\b|env\(\s*['\"]PORT")
MODEL_IMPORT_RE = re.compile(
    r"(?m)^\s*(?:from|import)\s+(?:openai|anthropic|langchain\w*|llama_index|litellm|ollama)\b"
    r"|(?:require\(|from\s+)['\"](?:openai|@anthropic-ai/sdk|ai|@ai-sdk/[\w-]+|langchain|@langchain/[\w-]+)['\"]")
EXEC_PY_RE = re.compile(r"(?<![.\w])(?:exec|eval)\(|subprocess\.|os\.system\(")
EXEC_JS_RE = re.compile(r"child_process|(?<![.\w])eval\(|new Function\(|vm\.runIn")
SQLITE_CODE_RE = re.compile(r"sqlite3\.connect\(\s*['\"]([^'\"]{1,80})['\"]|new\s+Database\(\s*['\"]([^'\"]{1,80})")
DJANGO_ENGINE_RE = re.compile(r"django\.db\.backends\.(postgresql|mysql|sqlite3|oracle)")

# Commands are printed fail closed. The program (its base name), flag names, assignment names and a
# few fixed keywords are printed; every flag value becomes <value> and every other positional
# becomes <arg>. Only for a recognised application runner, the one token that says what runs (the
# script, module or app target) is printed, and only when it is a plain file-like or module-like
# token. A shell's -c script is never printed; it is read only to learn which runner it starts.
SEPARATORS = {"&&", "||", ";", "|", "&"}
REDIRECT_RE = re.compile(r"\d?(?:>>?|<{1,3}|&>)")
REDIRECT_DUP_RE = re.compile(r"\d?>&\d")
WRAPPERS = {"env", "exec", "nohup", "sudo", "time", "nice", "tini", "dumb-init"}
# sudo flags read before the program: True takes a value (a user or group name, never printed).
SUDO_FLAGS = {"-u": True, "--user": True, "-g": True, "--group": True, "-E": False, "-H": False, "-n": False,
              "--preserve-env": False, "--set-home": False, "--non-interactive": False}
# Python modules run with -m that are runners themselves: python -m gunicorn app:app reads as gunicorn.
PYTHON_MODULE_RUNNERS = {"gunicorn", "uvicorn", "hypercorn", "daphne", "celery", "flask"}
SHELLS = {"sh", "bash", "zsh", "dash", "ash", "ksh"}
# Single-dash flag names longer than one letter that are printed; any other one becomes -<flag>,
# because a token such as -phunter (a password glued to -p) has the same shape.
KNOWN_SINGLE_DASH = {"-jar", "-cp", "-classpath", "-server", "-client", "-version", "-storepass", "-keystore",
                     "-keypass", "-storetype", "-alias", "-list", "-passin", "-passout", "-in", "-out", "-inkey",
                     "-name", "-type", "-exec", "-race", "-tags", "-mod", "-trimpath", "-ldflags", "-config",
                     "-port", "-host", "-addr", "-listen", "-help", "-verbose", "-debug", "-noout", "-text"}
TARGET_RE = re.compile(r"[A-Za-z0-9._/:-]{1,80}")
PROGRAM_RE = re.compile(r"[a-z]+\d{0,3}(?:[-_.+](?:[a-z]+\d{0,3}|\d+)){0,6}")
# Flag names must read like words: a value that happens to start with dashes is not printed.
LONG_FLAG_RE = re.compile(r"--[a-z]+\d{0,2}(?:[-_.][a-z]+\d{0,2}){0,7}")
JAVA_PROP_RE = re.compile(r"-D[a-z][a-zA-Z]*\d{0,2}(?:\.[a-z][a-zA-Z]*\d{0,2}){0,8}")
CONVENTIONAL_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")
_TOKENISH_RE = re.compile(r"(?=[A-Za-z0-9]*\d)(?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{16,}")
_KEY_SEGMENT_RE = re.compile(r"(?=[A-Za-z0-9]*\d)(?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{12,}")


def _looks_like_token(text: str) -> bool:
    return bool(_TOKENISH_RE.search(text)) or any(len(seg) > 40 for seg in re.split(r"[/.:]", text))


def is_variable_name(name: str) -> bool:
    """A conventional variable name: letters, digits and underscores in one case, at most 64
    characters, and not shaped like a key (a hex or base64 run)."""
    if not CONVENTIONAL_NAME_RE.fullmatch(name):
        return False
    if re.search(r"[0-9a-fA-F]{16,}", name) or re.search(r"[A-Za-z0-9]{24,}", name):
        return False
    # An access key id written where a name belongs: a long run of letters and digits, no underscore.
    if "_" not in name and _looks_like_token(name):
        return False
    # The same inside one part of the name; ordinary parts with digits (OAUTH2, S3) are short.
    if any(_KEY_SEGMENT_RE.fullmatch(segment) for segment in name.split("_")):
        return False
    # Letters only, with no underscore: no ordinary name runs this long without one.
    if re.fullmatch(r"[A-Za-z]{20,}", name):
        return False
    # Conventional names are written in one case (UPPER_SNAKE or lower_snake); a mixed-case word is
    # more likely a piece of a value than a name.
    return not (re.search(r"[a-z]", name) and re.search(r"[A-Z]", name))


UPPER_SNAKE_RE = re.compile(r"[A-Z_][A-Z0-9_]{0,63}")


def is_printable_name(name: str) -> bool:
    """A name that may be printed: UPPER_SNAKE and a conventional variable name."""
    return bool(UPPER_SNAKE_RE.fullmatch(name)) and is_variable_name(name)


class Runner:
    """What a runner prints besides flag names: fixed keywords, and one target token.

    Before the target, a flag the runner does not know closes the positional target (the flag may
    have taken the script as its value), and an inline-code flag (-c, -e, -r) closes every target.
    """

    def __init__(self, first=None, flags=None, keywords=(), after=None, switch=None, booleans=(), values=(),
                 code=()):
        self.first = first                  # kind of the first positional target: file, module, word
        self.flags = dict(flags or {})      # flag -> kind of the target it takes (-m, -A, -jar)
        self.keywords = set(keywords)       # fixed words printed as they are
        self.after = dict(after or {})      # keyword -> kind of the target after it (run, exec)
        self.switch = switch or {}          # target base name -> runner it continues as (php artisan)
        self.booleans = set(booleans)       # flags known to take no value
        self.values = set(values)           # flags known to take a value that is not the target
        self.code = set(code)               # flags whose value is code

    def known(self, flag: str) -> bool:
        return flag in self.flags or flag in self.booleans or flag in self.values or flag in self.code


_PKG_VALUES = {"--prefix", "--cwd", "-C", "--filter", "-F", "--workspace", "-w"}
_NODE = Runner(first="file", booleans={"--inspect", "--inspect-brk", "--watch", "--enable-source-maps",
                                       "--no-warnings", "--trace-warnings", "--no-deprecation", "--trace-deprecation",
                                       "--expose-gc", "--preserve-symlinks", "--experimental-modules"},
               values={"-r", "--require", "--import", "--loader", "--experimental-loader", "--env-file",
                       "--max-old-space-size"},
               code={"-e", "--eval", "-p", "--print"})
_ASGI = Runner(first="module", booleans={"--reload", "--proxy-headers", "--no-access-log", "--factory", "--preload"},
               values={"--host", "--port", "--workers", "--app-dir", "--log-level", "--root-path", "--env-file",
                       "-b", "--bind", "-w", "-k", "--worker-class", "-c", "--config", "-t", "--timeout",
                       "--threads", "--access-logfile", "--error-logfile", "-p"})
RUNNERS = {
    "node": _NODE, "nodejs": _NODE,
    "tsx": Runner(first="file", booleans={"--watch"}, values={"--tsconfig"}),
    "ts-node": Runner(first="file", booleans={"--transpile-only", "-T", "--esm"}, values={"--project", "-P"}),
    "nodemon": Runner(first="file", booleans={"--legacy-watch", "-L"},
                      values={"--exec", "-x", "--watch", "-w", "--ext", "-e", "--ignore", "-i", "--delay"}),
    "deno": Runner(keywords={"run", "task", "serve"}, after={"run": "file", "task": "word", "serve": "file"},
                   booleans={"--watch", "-A", "--allow-all", "--allow-net", "--allow-read", "--allow-write",
                             "--allow-env", "--allow-run", "--allow-sys", "--allow-ffi", "--allow-hrtime",
                             "--allow-import", "--deny-net", "--deny-read", "--deny-write", "--deny-env",
                             "--deny-run", "--deny-sys", "--deny-ffi", "--no-check", "--no-prompt", "-q", "--quiet",
                             "--unstable"},
                   code={"--eval"}),
    "bun": Runner(first="file", keywords={"run", "x"}, after={"run": "word", "x": "word"},
                  booleans={"--hot", "--watch", "--smol", "--bun"}, code={"-e", "--eval", "-p", "--print"}),
    "python": Runner(first="file", flags={"-m": "word"},
                     booleans={"-u", "-B", "-O", "-OO", "-E", "-s", "-S", "-I", "-q", "-v", "-b", "-bb", "-d", "-i",
                               "-P", "-R"},
                     values={"-W", "-X"}, code={"-c"}),
    "ruby": Runner(first="file", booleans={"-w", "-W", "-v", "-d"}, values={"-I", "-r"}, code={"-e"}),
    "php": Runner(first="file", switch={"artisan": "artisan"}, values={"-d", "-c", "-S", "-t"}, code={"-r"}),
    "artisan": Runner(first="word"),
    "php-fpm": Runner(), "gunicorn": _ASGI, "uvicorn": _ASGI, "hypercorn": _ASGI, "daphne": _ASGI,
    "celery": Runner(flags={"-A": "word", "--app": "word"}, keywords={"worker", "beat"}),
    "flask": Runner(flags={"--app": "word", "-A": "word"}, keywords={"run"}, booleans={"--debug"}),
    "django-admin": Runner(first="word"),
    "rails": Runner(keywords={"server", "s", "console", "c", "runner"}),
    "puma": Runner(first="file", booleans={"--preload"},
                   values={"-C", "--config", "-b", "--bind", "-p", "--port", "-w", "--workers", "-t", "-e"}),
    "sidekiq": Runner(), "java": Runner(flags={"-jar": "file"}),
    "dotnet": Runner(first="file", keywords={"run"}),
    "go": Runner(keywords={"run", "build"}, after={"run": "any"}),
    "npm": Runner(keywords={"run", "start", "test", "build", "ci", "install", "exec"},
                  after={"run": "word", "exec": "word"}, booleans={"--silent", "-s"}, values=_PKG_VALUES),
    "yarn": Runner(first="word", keywords={"run", "start", "test", "build", "install", "exec", "dlx"},
                   after={"run": "word", "exec": "word", "dlx": "word"}, booleans={"--silent", "-s"},
                   values=_PKG_VALUES),
    "pnpm": Runner(first="word", keywords={"run", "start", "test", "build", "install", "exec", "dlx"},
                   after={"run": "word", "exec": "word", "dlx": "word"}, booleans={"--silent", "-s"},
                   values=_PKG_VALUES),
    "npx": Runner(first="word", booleans={"-y", "--yes", "--no-install", "-q", "--quiet"},
                  values={"-p", "--package"}),
    "next": Runner(keywords={"start", "dev", "build", "lint"}),
    "pm2": Runner(keywords={"start"}, after={"start": "file"}), "pm2-runtime": Runner(first="file"),
    "caddy": Runner(keywords={"run", "start", "reverse-proxy", "file-server"}), "nginx": Runner(),
    "vite": Runner(keywords={"build", "dev", "preview", "serve"}),
    "bundle": Runner(keywords={"exec"}),
}


def runner_for(program: str) -> Runner | None:
    if re.fullmatch(r"python\d?(?:\.\d+)?", program):
        return RUNNERS["python"]
    return RUNNERS.get(program)


def _program_name(token: str) -> str:
    base = token.rstrip("/").rsplit("/", 1)[-1]
    return base if PROGRAM_RE.fullmatch(base) and len(base) <= 40 else "<program>"


def _flag_name(token: str, program: str) -> str:
    if token.startswith("--"):
        # a value that starts with dashes is read as a flag; one shaped like a key is not printed
        ok = LONG_FLAG_RE.fullmatch(token) and len(token) <= 40
        return token if ok else "--<flag>"
    if re.fullmatch(r"-[A-Za-z0-9]", token) or token in KNOWN_SINGLE_DASH:
        return token
    if program == "java" and JAVA_PROP_RE.fullmatch(token) and len(token) <= 60 and not _looks_like_token(token):
        return token
    if program in SHELLS and re.fullmatch(r"-[a-z]{1,4}", token):
        return token
    return "-<flag>"


def _target(token: str, kind: str = "any", switch=()) -> str:
    """A target is printed only in its plain shape: a file needs a dot or a slash, a module a colon or
    a dot; a word (a module, app, script or package name) may be a single word."""
    ok = TARGET_RE.fullmatch(token) and not token.startswith("-") and not _looks_like_token(token)
    if ok and kind == "file":
        ok = "." in token or "/" in token or token.rsplit("/", 1)[-1] in switch
    elif ok and kind == "module":
        ok = ":" in token or "." in token
    return token if ok else "<arg>"


def _tokens(command) -> list[str]:
    if isinstance(command, list):
        return [str(t) for t in command]
    text = str(command)
    try:
        return shlex.split(text)
    except ValueError:
        return text.split()


def render_command(command, depth: int = 0) -> tuple[str, list[str], set[str]]:
    """(printed text, every raw token including those of -c scripts, runner names found).

    Only the printed text may leave the script; the raw tokens are for classification inside it.
    """
    tokens = _tokens(command)
    raw: list[str] = list(tokens)
    runners: set[str] = set()
    out: list[str] = []
    expect_program, program, runner, pending, target_done, next_is_target = True, "", None, None, False, False
    shell_done, positional_closed, target_kind = False, False, "any"
    i = 0
    while i < len(tokens) and len(out) < 60:
        tok = tokens[i]
        i += 1
        if tok in SEPARATORS:
            out.append(tok)
            expect_program, program, runner, pending, target_done, next_is_target = True, "", None, None, False, False
            shell_done, positional_closed = False, False
            continue
        if REDIRECT_DUP_RE.fullmatch(tok):
            out.append(tok)
            continue
        if REDIRECT_RE.fullmatch(tok):
            out.append(tok)
            if i < len(tokens):
                out.append("<value>")
                i += 1
            continue
        name, eq, _ = tok.partition("=")
        if eq and expect_program and not tok.startswith("-"):
            out.append(f"{name}=<value>" if is_printable_name(name) else "<name>=<value>")
            continue
        if expect_program and tok == "--":  # tini -- program
            out.append(tok)
            continue
        if expect_program and program == "sudo" and tok in SUDO_FLAGS:  # sudo -u <user> program
            out.append(tok)
            if SUDO_FLAGS[tok] and i < len(tokens):
                out.append("<value>")
                i += 1
            continue
        if expect_program:
            program = _program_name(tok)
            out.append(program)
            runner = runner_for(program)
            if runner is not None:
                runners.add(program)
            expect_program = program in WRAPPERS
            pending, target_done, next_is_target, positional_closed = None, False, False, False
            continue
        if pending is not None and not tok.startswith("-"):
            if pending == "script":
                out.append("<script>")
                shell_done = True
                if depth < 3:
                    _, inner_raw, inner_runners = render_command(tok, depth + 1)
                    raw.extend(inner_raw)
                    runners |= inner_runners
            elif pending == "target":
                shown = _target(tok, target_kind)
                out.append(shown)
                target_done = True
                if runner is RUNNERS["python"] and shown in PYTHON_MODULE_RUNNERS:  # python -m gunicorn
                    runner, target_done = RUNNERS[shown], False  # an earlier unknown flag still closes it
                    runners.add(shown)
            else:
                out.append("<value>")
            pending = None
            continue
        pending = None
        if shell_done:  # the script's own parameters: never printed
            out.append("<arg>")
            continue
        if tok.startswith("-") and tok not in ("-", "--"):
            flag, eq, _ = tok.partition("=")
            known = runner is not None and runner.known(flag)
            out.append((flag if known else _flag_name(flag, program)) + ("=<value>" if eq else ""))
            if program in SHELLS and not eq and re.fullmatch(r"-[a-z]{0,3}c[a-z]{0,3}", tok):
                pending = "script"
                continue
            if runner is not None and not target_done:
                if flag in runner.code:
                    target_done = True
                elif flag in runner.flags:
                    if eq:
                        target_done = True
                    else:
                        pending, target_kind = "target", runner.flags[flag]
                        continue
                elif flag in runner.booleans:
                    continue
                elif flag not in runner.values:
                    positional_closed = True  # an unknown flag may have taken the script as its value
            if not eq:
                pending = "value" if not (runner is not None and flag in runner.booleans) else None
            continue
        # a positional
        if runner is not None and program == "bundle" and tok == "exec" and not target_done:
            out.append(tok)
            expect_program = True
            continue
        if (runner is not None and target_done and not positional_closed and tok in runner.keywords
                and tok not in runner.after):
            out.append(tok)  # a fixed word from the runner's own list; it opens no further target
            continue
        if runner is not None and not target_done and not positional_closed:
            if next_is_target:
                out.append(_target(tok, target_kind))
                target_done, next_is_target = True, False
            elif tok in runner.keywords:
                out.append(tok)
                if tok in runner.after:
                    next_is_target, target_kind = True, runner.after[tok]
                else:
                    target_done = True
            elif runner.first:
                shown = _target(tok, runner.first, runner.switch)
                out.append(shown)
                target_done = True
                follow_on = runner.switch.get(tok.rsplit("/", 1)[-1]) if shown != "<arg>" else None
                if follow_on:
                    runner, target_done = RUNNERS[follow_on], False
                    runners.add(follow_on)
            else:
                out.append("<arg>")
                target_done = True
            continue
        out.append("<arg>")
    if i < len(tokens):
        out.append("...")
    text = " ".join(out)
    return (text if len(text) <= 200 else text[:197] + "..."), raw, runners


def safe_command(command) -> str:
    """The printable form of a command; see render_command."""
    return render_command(command)[0]


def command_text(command) -> str:
    """Every raw token of a command, -c scripts included, for classification only: never printed."""
    return " ".join(render_command(command)[1])


def command_ports(command) -> list[str]:
    """Port numbers given to a recognised runner (--port N, -p N, --bind host:N); digits only."""
    _, raw, runners = render_command(command)
    if not runners:
        return []
    ports = []
    for j, tok in enumerate(raw):
        value = None
        if tok in ("--port", "-p", "--bind", "-b") and j + 1 < len(raw):
            value = raw[j + 1]
        elif tok.startswith(("--port=", "--bind=")):
            value = tok.split("=", 1)[1]
        if value is not None:
            m = re.fullmatch(r"(?:[\w.\[\]:-]*:)?(\d{2,5})", value)
            if m and 1 <= int(m.group(1)) <= 65535:
                ports.append(m.group(1))
    return ports


def _plain(text) -> str:
    """Short descriptive text from a file (an image name, a volume path), whitespace collapsed."""
    text = " ".join(str(text).split())
    return text if len(text) <= 100 else text[:97] + "..."


ENV_START_RE = re.compile(r"^\s*(?:export\s+)?([^\s=#][^\s=]*)\s*=\s*(.*)$")
UNCLEAR_NAMES = "the variable names in {rel} could not all be read safely; unclear lines were skipped"


def _quote_end(text: str, quote: str) -> int | None:
    """Index of the closing quote in text, or None. Raises ValueError when a backslash sits next to a
    quote character: dotenv readers disagree on whether that ends the value, so the file is unclear."""
    for i, ch in enumerate(text):
        if ch == "\\" and i + 1 < len(text) and text[i + 1] in "'\"`":
            raise ValueError("escaped quote")
        if ch == quote:
            return i
    return None


def env_file_names(text: str) -> tuple[list[str], bool]:
    """(names, confident). A quoted value may continue over several lines and a heredoc value runs to
    its end marker; those lines are skipped. A NAME= line counts only after a blank line, a comment or
    another NAME= line, and only a conventional variable name counts. When quotes do not balance, or
    an escaped quote makes the end of a value unclear, no names at all come from the file."""
    names: list[str] = []
    confident = True
    open_quote = None
    heredoc = None
    prev = "start"  # blank, comment, name, other
    text = text.lstrip("\ufeff").replace("\r\n", "\n")
    # Readers split lines on "\n" only; any other line break (a lone CR, form feed, vertical tab,
    # NEL, U+2028) would split a value differently here than there, so the file is unclear.
    if re.search(r"[\r\x0b\x0c\x1c-\x1e\x85\u2028\u2029]", text):
        return [], False
    for line in text.split("\n"):
        stripped = line.strip()
        if heredoc is not None:
            if stripped == heredoc:
                heredoc, prev = None, "name"
            continue
        if open_quote:
            try:
                end = _quote_end(line, open_quote)
            except ValueError:
                return [], False
            if end is not None:
                open_quote, prev = None, "name"
            continue
        if not stripped:
            prev = "blank"
            continue
        if stripped.startswith("#"):
            prev = "comment"
            continue
        m = ENV_START_RE.match(line)
        if not m:
            prev = "other"
            continue
        name, value = m.group(1), m.group(2)
        if prev not in ("start", "blank", "comment", "name"):
            confident = False
            continue  # follows a line that is not NAME=: probably part of a value
        prev = "name"
        if is_variable_name(name):
            names.append(name)
        else:
            confident = False
        here = re.match(r"<<-?\s*['\"]?([A-Za-z_]\w*)['\"]?\s*$", value)
        if here:
            heredoc = here.group(1)
            continue
        if value[:1] in ("'", '"', "`"):
            try:
                end = _quote_end(value[1:], value[0])
            except ValueError:
                return [], False
            if end is None:
                open_quote = value[0]
    if open_quote or heredoc is not None:
        return [], False
    return names, confident


def dockerfile_env_names(arg: str) -> tuple[list[str], bool]:
    """(names, confident) for a Dockerfile ENV or ARG line: NAME=value tokens read with shlex, or the
    legacy 'ENV NAME value' form. A line that does not read cleanly gives no names. Values never leave."""
    try:
        tokens = shlex.split(arg)
    except ValueError:
        return [], False
    if not tokens:
        return [], True
    if "=" not in tokens[0]:
        return ([tokens[0]], True) if is_variable_name(tokens[0]) else ([], False)
    names = []
    for tok in tokens:
        name, sep, _ = tok.partition("=")
        if not sep or not is_variable_name(name):
            return [], False
        names.append(name)
    return names, True


# ------------------------------------------------------------------ a small YAML subset reader

class YamlError(ValueError):
    pass


def _strip_comment(text: str) -> str:
    quote = None
    for i, ch in enumerate(text):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "'\"" and (i == 0 or text[i - 1] in " :[{,-"):
            quote = ch
        elif ch == "#" and (i == 0 or text[i - 1] in " \t"):
            return text[:i].rstrip()
    return text


class Unclear:
    """A flow collection the reader could not split with confidence. It is falsy and not iterable,
    so callers treat it as missing; the environment reader notes it."""

    def __bool__(self):
        return False


def _split_flow(inner: str) -> list[str] | None:
    """Split a flow collection's body on commas outside quotes; None when quotes do not balance or a
    nested collection appears."""
    parts, buf, quote = [], [], None
    for ch in inner:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
            buf.append(ch)
        elif ch in "[]{}":
            return None
        elif ch == ",":
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if quote:
        return None
    parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def _flow_item_ok(item: str) -> bool:
    """A flow key or value with a quote in it must be quoted from end to end."""
    item = item.strip()
    if not any(q in item for q in "'\""):
        return True
    return bool(re.fullmatch(r'"[^"\\]*"', item) or re.fullmatch(r"'(?:[^']|'')*'", item))


def _flow_key(part: str):
    """Split 'key: value' of a flow mapping at the first colon outside quotes."""
    quote = None
    for i, ch in enumerate(part):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
        elif ch == ":" and (i + 1 == len(part) or part[i + 1] == " "):
            return part[:i], part[i + 1:]
    return part, ""


def _scalar(text: str):
    text = text.strip()
    if text in ("", "~", "null", "Null", "NULL"):
        return None
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        return text[1:-1]
    if text.startswith("[") or text.startswith("{"):
        closing = "]" if text[0] == "[" else "}"
        parts = _split_flow(text[1:-1]) if text.endswith(closing) else None
        if parts is None:
            return Unclear()
        if closing == "]":
            if not all(_flow_item_ok(p) for p in parts):
                return Unclear()
            return [_scalar(p) for p in parts]
        out = {}
        for part in parts:
            k, v = _flow_key(part)
            if not (_flow_item_ok(k) and _flow_item_ok(v)):
                return Unclear()
            out[str(_scalar(k))] = _scalar(v)
        return out
    return text


_KEY_RE = re.compile(r"^(\"[^\"]*\"|'[^']*'|[^\s'\"#\-\[\{][^:]*?|-[^\s][^:]*?)\s*:(?:\s+(.*))?$")


def _key(content: str):
    m = _KEY_RE.match(content)
    if not m:
        return None
    return _scalar(m.group(1)), (m.group(2) or "").strip()


def _document_marker(line: str) -> bool:
    """A YAML document start or end marker, alone or followed by a comment (--- # second)."""
    return bool(re.fullmatch(r"(?:---|\.\.\.)(?:\s+#.*)?\s*", line.strip()))


def parse_yaml(text: str):
    """Read block mappings, block sequences, flow lists and scalars; enough for compose and provider files."""
    lines = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        body = raw.lstrip(" ")
        if not body.strip() or body.startswith("#") or _document_marker(body):
            continue
        if body.startswith("\t"):
            raise YamlError("tab indentation")
        lines.append([len(raw) - len(body), _strip_comment(body.rstrip())])
    if not lines:
        return {}
    value, pos = _block(lines, 0, lines[0][0])
    if pos != len(lines):
        raise YamlError(f"stopped at line {pos + 1} of the meaningful lines")
    return value


def _is_item(content: str) -> bool:
    return content == "-" or content.startswith("- ")


def _block(lines, i, indent):
    return _seq(lines, i, indent) if _is_item(lines[i][1]) else _map(lines, i, indent)


def _seq(lines, i, indent):
    out = []
    while i < len(lines) and lines[i][0] == indent and _is_item(lines[i][1]):
        content = lines[i][1][1:].lstrip(" ")
        if not content:
            i += 1
            if i < len(lines) and lines[i][0] > indent:
                value, i = _block(lines, i, lines[i][0])
            else:
                value = None
            out.append(value)
        elif content[:1] in "|>" and content.rstrip("-+0123456789") in ("|", ">"):
            i += 1
            parts = []
            while i < len(lines) and lines[i][0] > indent:
                parts.append(lines[i][1])
                i += 1
            out.append("\n".join(parts))
        elif _key(content) is not None:
            new_indent = indent + len(lines[i][1]) - len(content)
            lines[i] = [new_indent, content]
            value, i = _map(lines, i, new_indent)
            out.append(value)
        else:
            out.append(_scalar(content))
            i += 1
    return out, i


def _map(lines, i, indent):
    out = {}
    while i < len(lines) and lines[i][0] == indent and not _is_item(lines[i][1]):
        parsed = _key(lines[i][1])
        if parsed is None:
            raise YamlError(f"not a key: {lines[i][1][:40]}")
        key, rest = parsed
        i += 1
        if rest.startswith("&") and " " not in rest:
            rest = ""
        if rest == "":
            if i < len(lines) and lines[i][0] > indent:
                value, i = _block(lines, i, lines[i][0])
            elif i < len(lines) and lines[i][0] == indent and _is_item(lines[i][1]):
                value, i = _seq(lines, i, indent)
            else:
                value = None
        elif rest[0] in "|>":
            parts = []
            while i < len(lines) and lines[i][0] > indent:
                parts.append(lines[i][1])
                i += 1
            value = "\n".join(parts)
        else:
            value = _scalar(rest)
            while i < len(lines) and lines[i][0] > indent:
                value = f"{value} {lines[i][1]}"
                i += 1
        out[str(key)] = value
    return out, i


# ------------------------------------------------------------------ the scan

@dataclass
class App:
    path: str
    markers: set = field(default_factory=set)
    deps: dict = field(default_factory=dict)  # ecosystem -> {name: dev_only}
    ext_counts: dict = field(default_factory=dict)
    out: dict = field(default_factory=lambda: {k: {} for k in KEYS})  # key -> ordered set (dict)
    flags: set = field(default_factory=set)
    overflow: dict = field(default_factory=dict)

    def add(self, key: str, text: str) -> None:
        bucket = self.out[key]
        if text in bucket:
            return
        if len(bucket) >= (MAX_ENV_NAMES if key == "env_vars" else MAX_PER_APP):
            self.overflow[key] = self.overflow.get(key, 0) + 1
            return
        bucket[text] = None

    def dep(self, eco: str, name: str, dev: bool = False) -> None:
        bucket = self.deps.setdefault(eco, {})
        bucket[name] = bucket.get(name, True) and dev

    def has(self, eco: str, name: str) -> bool:
        return name in self.deps.get(eco, {})


class Scan:
    def __init__(self, root: str, max_files: int, max_depth: int):
        self.root = root
        self.max_files = max_files
        self.max_depth = max_depth
        self.files: dict[str, int] = {}  # relative path -> size
        self.dirs: set[str] = {""}
        self.notes: dict[str, None] = {}
        self.notes_dropped = 0
        self.children: dict[str, list[str]] = {}  # folder -> regular file names in it
        self.skipped_build: list[str] = []
        self.files_of: dict[int, list[str]] = {}  # id(app) -> its files
        self.dirs_of: dict[int, list[str]] = {}   # id(app) -> its folders
        self.symlinks: list[str] = []
        self.special: list[str] = []
        self.unreadable: list[str] = []
        self.too_deep: list[str] = []
        self.hidden: list[str] = []
        self.truncated: list[str] = []
        self.file_limit_hit = False
        self.bytes_read = 0
        self.files_read = 0
        self.source_skipped = 0
        self.apps: dict[str, App] = {}
        self.project = App("")

    def add_names(self, app: App, rel: str, names: list[str]) -> None:
        """Add variable names; only UPPER_SNAKE ones are printed, the others are counted in a note."""
        hidden = [n for n in names if not is_printable_name(n)]
        for name in names:
            if is_printable_name(name):
                app.add("env_vars", name)
        if hidden:
            self.note(f"some variable names in {rel} are not written in capitals and were not listed")

    def note(self, text: str) -> None:
        if text in self.notes:
            return
        if len(self.notes) >= MAX_FILE_NOTES:
            self.notes_dropped += 1
            return
        self.notes[text] = None

    # -- walking and reading

    def walk(self) -> None:
        def onerror(err):
            self.unreadable.append(self.rel(getattr(err, "filename", "") or ""))

        for dirpath, dirnames, filenames in os.walk(self.root, topdown=True, onerror=onerror, followlinks=False):
            rel_dir = self.rel(dirpath)
            depth = 0 if rel_dir == "" else rel_dir.count("/") + 1
            if "pyvenv.cfg" in filenames and rel_dir:
                dirnames[:] = []
                continue
            keep = []
            for d in sorted(dirnames):
                rel = self.join(rel_dir, d)
                if os.path.islink(os.path.join(dirpath, d)):
                    self.symlinks.append(rel)
                elif d in SKIP_DIRS or d.endswith(".egg-info"):
                    self.dirs.add(rel)  # seen, not entered
                    if d in NOTED_SKIPS:
                        self.skipped_build.append(rel)
                elif d.startswith(".") and d not in HIDDEN_READ:
                    self.dirs.add(rel)
                    self.hidden.append(rel)
                elif depth + 1 > self.max_depth:
                    self.too_deep.append(rel)
                else:
                    keep.append(d)
                    self.dirs.add(rel)
            dirnames[:] = keep
            for name in sorted(filenames):
                rel = self.join(rel_dir, name)
                try:
                    st = os.lstat(os.path.join(dirpath, name))
                except OSError:
                    self.unreadable.append(rel)
                    continue
                if stat.S_ISLNK(st.st_mode):
                    self.symlinks.append(rel)
                    continue
                if not stat.S_ISREG(st.st_mode):
                    self.special.append(rel)
                    continue
                if len(self.files) >= self.max_files:
                    self.file_limit_hit = True
                    return
                self.files[rel] = st.st_size
                self.children.setdefault(rel_dir, []).append(name)

    def rel(self, path: str) -> str:
        rel = os.path.relpath(path, self.root) if path else ""
        return "" if rel == "." else rel.replace(os.sep, "/")

    @staticmethod
    def join(a: str, b: str) -> str:
        return f"{a}/{b}" if a else b

    def read(self, rel: str, limit: int = MAX_READ_BYTES, whole: bool = True) -> str | None:
        """Read a regular file without following links or blocking on pipes; None when not possible."""
        if rel not in self.files or self.bytes_read >= MAX_TOTAL_READ:
            return None
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        try:
            fd = os.open(os.path.join(self.root, *rel.split("/")), flags)
        except OSError:
            self.unreadable.append(rel)
            return None
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                return None
            data = os.read(fd, limit + 1)
        except OSError:
            self.unreadable.append(rel)
            return None
        finally:
            os.close(fd)
        if data.startswith(b"\xef\xbb\xbf"):
            data = data[3:]
        if len(data) > limit and whole:
            self.truncated.append(rel)
            data = data[:limit]
        self.bytes_read += len(data)
        self.files_read += 1
        return data.decode("utf-8", errors="replace")

    # -- apps

    def find_apps(self) -> None:
        by_dir: dict[str, set] = {}
        for rel in self.files:
            d, _, name = rel.rpartition("/")
            if name in PRIMARY_MARKERS or name.endswith(".csproj"):
                by_dir.setdefault(d, set()).add(name)
            elif name in ("Dockerfile", "Containerfile"):
                by_dir.setdefault(d, set()).add(name)
        roots: dict[str, App] = {}
        for d in sorted(by_dir, key=lambda p: (p.count("/"), p)):
            markers = by_dir[d]
            parent = self.owner_of(d, roots)
            if parent is not None:
                below = d.split("/")[len(parent.split("/")) if parent else 0:]
                # Tests, docs and examples inside an app, or a lone Dockerfile, belong to that app.
                if set(below) & NOT_APP_DIRS or markers <= {"Dockerfile", "Containerfile"}:
                    continue
            roots[d] = App(d, markers=markers)
        # A workspace root (npm, Yarn or pnpm workspaces) that only groups other apps is not an app itself.
        above = self.ancestors(roots)
        for d in list(roots):
            if d in above and roots[d].markers == {"package.json"} and self.is_workspace_root(d):
                del roots[d]
        above = self.ancestors(roots)
        # A folder of HTML pages with no app around it is a static site. Next to other apps, HTML under
        # docs or tests is not counted; generated reports never are.
        other_apps = bool(roots)
        for rel in self.files:
            d, _, name = rel.rpartition("/")
            parts = d.split("/") if d else []
            if any("report" in part.lower() or part in ("htmlcov", "storybook-static") or
                   (other_apps and part in NOT_APP_DIRS) for part in parts):
                continue
            if name in ("index.html", "index.htm") and self.owner_of(d, roots) is None:
                if d not in above and not (d == "" and roots):
                    roots[d] = App(d, markers={name})
                    roots[d].flags.add("static-root")
                    above |= self.ancestors({d: None})
        self.apps = roots
        for rel in self.files:
            self.files_of.setdefault(id(self.app_for(rel)), []).append(rel)
        for d in self.dirs:
            self.dirs_of.setdefault(id(self.app_for(self.join(d, "x"))), []).append(d)

    @staticmethod
    def ancestors(roots) -> set:
        """Every folder that has an app root strictly below it."""
        out = set()
        for d in roots:
            probe = d
            while probe:
                probe = probe.rpartition("/")[0]
                out.add(probe)
        return out

    def is_workspace_root(self, d: str) -> bool:
        if self.join(d, "pnpm-workspace.yaml") in self.files or self.join(d, "lerna.json") in self.files:
            return True
        data = self.json(self.join(d, "package.json"))
        return isinstance(data, dict) and "workspaces" in data

    @staticmethod
    def owner_of(d: str, roots: dict) -> str | None:
        probe = d
        while True:
            if probe in roots:
                return probe
            if probe == "":
                return None
            probe = probe.rpartition("/")[0]

    def app_for(self, rel: str) -> App:
        owner = self.owner_of(rel.rpartition("/")[0], self.apps)
        return self.project if owner is None else self.apps[owner]

    def json(self, rel: str):
        text = self.read(rel)
        if text is None:
            return None
        try:
            return json.loads(text)
        except ValueError:
            self.note(f"{rel} is not valid JSON, so it was not understood")
        except RecursionError:
            self.note(f"{rel} is nested too deeply to read, so it was not understood")
        return None

    def toml(self, rel: str):
        if tomllib is None:
            self.note(f"{rel} was not read because this Python has no TOML reader (3.11 or newer has one)")
            return None
        text = self.read(rel)
        if text is None:
            return None
        try:
            return tomllib.loads(text)
        except (tomllib.TOMLDecodeError, ValueError, RecursionError):
            self.note(f"{rel} is not valid TOML, so it was not understood")
            return None

    def yaml(self, rel: str):
        text = self.read(rel)
        if text is None:
            return None
        try:
            return parse_yaml(text)
        except (YamlError, RecursionError, ValueError, IndexError):
            self.note(f"{rel} uses YAML this script does not read; it was only partly understood")
            return None

    # -- analysis

    def run(self) -> dict:
        self.walk()
        self.find_apps()
        for rel in sorted(self.files):
            self.guarded(rel, self.inspect, rel)
        for app in list(self.apps.values()) + [self.project]:
            self.apply_dependency_rules(app)
            self.guarded(app.path or ".", self.framework_facts, app)
        self.scan_sources()
        for app in self.apps.values():
            self.languages(app)
            self.static_verdict(app)
        return self.report()

    def guarded(self, where: str, fn, *args) -> None:
        """Run one analysis step; a file with a shape this script did not expect is noted, not fatal."""
        try:
            fn(*args)
        except (TypeError, AttributeError, KeyError, ValueError, IndexError, RecursionError):
            self.note(f"{where} has a shape this script did not expect, so it was only partly read")

    def inspect(self, rel: str) -> None:
        app = self.app_for(rel)
        d, _, name = rel.rpartition("/")
        lower = name.lower()
        ext = os.path.splitext(lower)[1]
        if ext in EXT_LANG:
            app.ext_counts[EXT_LANG[ext]] = app.ext_counts.get(EXT_LANG[ext], 0) + 1
        if name in MARKER_LANG:
            app.add("languages", MARKER_LANG[name])
        if name in LOCKFILES:
            app.add("package_managers", f"{LOCKFILES[name]} ({rel})")
        handler = HANDLERS.get(name)
        if handler:
            handler(self, app, rel)
        if lower.endswith(".txt") and (lower.startswith("requirements") or d.endswith("requirements")):
            self.requirements(app, rel)
        if name == "Dockerfile" or name == "Containerfile" or lower.startswith("dockerfile.") or \
                lower.endswith(".dockerfile"):
            self.dockerfile(app, rel)
        elif re.fullmatch(r"(docker-)?compose(\.[\w-]+)?\.ya?ml", lower):
            self.compose(app, rel)
        elif name == ".env" or name.startswith(".env.") or name == ".envrc" or lower.endswith(".env"):
            self.env_file(app, rel)
        elif re.fullmatch(r"next\.config\.(js|mjs|cjs|ts)", lower):
            app.add("frameworks", "Next.js")
            text = self.read(rel) or ""
            if re.search(r"output\s*:\s*['\"]export['\"]", text):
                app.flags.add("static-export")
                app.add("runtime_needs", f"Next.js static export ({rel}): builds to static files")
        elif re.fullmatch(r"astro\.config\.(js|mjs|cjs|ts|mts)", lower):
            app.add("frameworks", "Astro")
            text = self.read(rel) or ""
            m = re.search(r"@astrojs/(node|vercel|netlify|cloudflare|deno)", text)
            if m:
                app.add("runtime_needs", f"Astro with the {m.group(1)} server adapter ({rel}): needs a server")
            else:
                app.flags.add("static-export")
                app.add("runtime_needs", f"Astro without a server adapter ({rel}): builds to static files")
        elif re.fullmatch(r"nuxt\.config\.(js|mjs|ts)", lower):
            app.add("frameworks", "Nuxt")
        elif re.fullmatch(r"svelte\.config\.(js|mjs|ts)", lower):
            text = self.read(rel) or ""
            if "adapter-static" in text:
                app.flags.add("static-export")
                app.add("runtime_needs", f"SvelteKit static adapter ({rel}): builds to static files")
        elif re.fullmatch(r"vite\.config\.(js|mjs|cjs|ts|mts)", lower):
            app.add("frameworks", "Vite")
        elif lower in ("hugo.toml", "hugo.yaml", "hugo.json"):
            app.add("frameworks", "Hugo")
        elif name == "schema.prisma":
            m = re.search(r"provider\s*=\s*\"(postgresql|mysql|sqlite|mongodb|sqlserver|cockroachdb)\"",
                          self.read(rel) or "")
            if m:
                app.add("datastores", f"{m.group(1)} through Prisma ({rel})")
                if m.group(1) == "sqlite":
                    app.add("state_on_disk", f"SQLite database file through Prisma ({rel})")
        elif ext in (".sqlite", ".sqlite3", ".db"):
            head = self.read(rel, 16, whole=False) if ext == ".db" else "SQLite format 3"
            if head and head.startswith("SQLite format 3"):
                app.add("state_on_disk", f"SQLite database file {rel}")
                app.add("datastores", f"SQLite (file {rel})")
        elif ext in (".yml", ".yaml") and d == ".github/workflows":
            self.workflow(app, rel)
        elif ext == ".tf":
            app.add("existing_hosting", f"Terraform configuration ({rel})")
        elif ext in (".yml", ".yaml") and lower not in ("pnpm-lock.yaml",):
            self.maybe_kubernetes(app, rel)
        elif lower.endswith(".service") and d.count("/") < 3:
            text = self.read(rel) or ""
            if "[Service]" in text and "ExecStart" in text:
                app.add("existing_hosting", f"systemd unit ({rel})")
        if lower in ("caddyfile", "nginx.conf") or (lower.endswith(".conf") and "nginx" in d.lower()):
            app.add("existing_hosting", f"web server config ({rel})")

    def apply_dependency_rules(self, app: App) -> None:
        for eco, name, key, text in RULES:
            bucket = app.deps.get(eco)
            if not bucket:
                continue
            if name.endswith("*"):
                hits = [n for n in bucket if n.startswith(name[:-1])]
            else:
                hits = [name] if name in bucket else []
            for hit in hits:
                if key == "frameworks":
                    app.add(key, text)
                    continue
                entry = text.format(d=hit)
                if bucket[hit]:
                    entry += " [development dependency only]"
                app.add(key, entry)

    def framework_facts(self, app: App) -> None:
        p = app.path
        frameworks = set(app.out["frameworks"])

        def has(rel: str) -> bool:
            return self.join(p, rel) in self.files

        def under(folder: str) -> bool:
            return self.join(p, folder) in self.dirs

        if "artisan" in app.markers or "Laravel" in frameworks:
            app.add("frameworks", "Laravel")
            jobs = [n for n in self.children.get(self.join(p, "app/Jobs"), []) if n.endswith(".php")]
            if jobs or app.has("php", "laravel/horizon"):
                app.add("background_work", f"Laravel queue worker (php artisan queue:work) for {len(jobs)} job "
                        f"class(es) in {self.join(p, 'app/Jobs')}")
            for rel, needle in [("routes/console.php", "Schedule::"), ("app/Console/Kernel.php", "$schedule->"),
                                ("bootstrap/app.php", "withSchedule")]:
                if has(rel) and needle in (self.read(self.join(p, rel)) or ""):
                    app.add("background_work", "Laravel scheduler: cron must run php artisan schedule:run every "
                            f"minute ({self.join(p, rel)})")
            if self.children.get(self.join(p, "database/migrations")):
                app.add("datastores", "SQL database (Laravel migrations in "
                        f"{self.join(p, 'database/migrations')}; the engine is set by DB_CONNECTION)")
                app.flags.add("db-engine-in-env")
            if self.join(p, "storage") in self.dirs:
                app.add("state_on_disk", f"Laravel {self.join(p, 'storage')}/ folder: uploaded files, logs, "
                        "sessions and cache live on local disk unless configured otherwise")
            if has("public/index.php"):
                app.add("entry_points", f"{self.join(p, 'public/index.php')} (front controller, served through "
                        "PHP-FPM or Apache)")
        if "wp-config.php" in app.markers or under("wp-content") or under("wp-includes"):
            app.add("frameworks", "WordPress")
            app.add("languages", "PHP")
            app.add("datastores", "a MariaDB or MySQL compatible database (WordPress needs one)")
            app.add("state_on_disk", f"{self.join(p, 'wp-content/uploads')} (media uploads on local disk)")
            app.add("background_work", "WP-Cron (runs on page visits unless a system cron is set up)")
            if "wp-config.php" in app.markers:
                self.note(f"{self.join(p, 'wp-config.php')} holds credentials and was not read")
        if "manage.py" in app.markers:
            app.add("frameworks", "Django")
            app.add("entry_points", f"python {self.join(p, 'manage.py')} (Django; production usually runs "
                    "gunicorn or uvicorn)")
            for rel in [r for r in self.files_of.get(id(app), [])
                        if re.search(r"(^|/)settings(/[^/]+|[^/]*)\.py$", r)][:10]:
                text = self.read(rel) or ""
                for engine in DJANGO_ENGINE_RE.findall(text):
                    name = {"postgresql": "PostgreSQL", "mysql": "MySQL", "sqlite3": "SQLite",
                            "oracle": "Oracle"}[engine]
                    app.add("datastores", f"{name} (Django settings {rel})")
                    if engine == "sqlite3":
                        app.add("state_on_disk", f"SQLite database file (Django settings {rel})")
                if "MEDIA_ROOT" in text:
                    app.add("state_on_disk", f"uploaded media in MEDIA_ROOT (Django settings {rel})")
                if "ASGI_APPLICATION" in text or "CHANNEL_LAYERS" in text:
                    app.add("runtime_needs", WS.format(d=f"Django Channels, {rel}"))
                if "CELERY" in text:
                    app.add("background_work", f"Celery configured in Django settings ({rel})")
        if "Rails" in frameworks or has("config/application.rb"):
            app.add("frameworks", "Rails")
            text = self.read(self.join(p, "config/database.yml")) or ""
            for adapter in sorted(set(re.findall(r"(?m)^\s*adapter:\s*(postgresql|mysql2|sqlite3|trilogy)\s*$",
                                                 text))):
                app.add("datastores", f"{adapter} (adapter in {self.join(p, 'config/database.yml')})")
            if self.join(p, "storage") in self.dirs:
                app.add("state_on_disk", f"{self.join(p, 'storage')}/ (Active Storage files on local disk by "
                        "default)")
            if has("config/recurring.yml") or has("config/sidekiq.yml"):
                app.add("background_work", "Rails background jobs configured in config/")
            app.add("ports", "3000 (default of the Rails server)")
        if "Next.js" in frameworks and "static-export" not in app.flags:
            if any("next start" in e for e in app.out["entry_points"]) or not app.out["ports"]:
                app.add("ports", "3000 (default of next start)")
        for d in sorted(self.dirs_of.get(id(app), [])):
            base = d.rpartition("/")[2]
            if base in (".vercel", ".netlify"):
                app.add("existing_hosting", f"{base[1:].capitalize()} (linked {d} folder)")
            if base.lower() in UPLOAD_DIRS:
                app.add("state_on_disk", f"possible uploads folder {d}/ (files written at run time live on "
                        "local disk)")

    def scan_sources(self) -> None:
        sources = [r for r in sorted(self.files) if os.path.splitext(r)[1].lower() in SOURCE_EXTS]
        # Short paths first: entry files and config sit near the top of an app.
        sources.sort(key=lambda r: (r.count("/"), r))
        for i, rel in enumerate(sources):
            if i >= MAX_SOURCE_FILES or self.bytes_read >= MAX_TOTAL_READ:
                self.source_skipped = len(sources) - i
                break
            text = self.read(rel, 128 * 1024)
            if text is None:
                continue
            self.guarded(rel, self.source_file, self.app_for(rel), rel, text)

    def source_file(self, app: App, rel: str, text: str) -> None:
        ext = os.path.splitext(rel)[1].lower()
        for rx in ENV_CODE_RES:
            for name in rx.findall(text):
                if is_printable_name(name):
                    app.add("env_vars", name)
        if PORT_ENV_RE.search(text):
            app.add("ports", f"reads the PORT variable ({rel})")
        for m in PORT_DEFAULT_RE.finditer(text):
            app.add("ports", f"{m.group(1)} (default when PORT is not set, {rel})")
        for rx in (PORT_LISTEN_RE, PORT_KWARG_RE):
            for m in rx.finditer(text):
                app.add("ports", f"{m.group(1)} ({rel})")
        if MODEL_IMPORT_RE.search(text):
            exec_re = EXEC_PY_RE if ext == ".py" else EXEC_JS_RE if ext in (".js", ".mjs", ".cjs", ".ts", ".tsx",
                                                                             ".jsx", ".mts") else None
            if exec_re and exec_re.search(text):
                app.add("runtime_needs", f"may run code produced by a model: {rel} calls a model API and also "
                        "evaluates code or starts processes; check this before exposing it")
        for m in SQLITE_CODE_RE.finditer(text):
            target = m.group(1) or m.group(2)
            if target != ":memory:":
                app.add("state_on_disk", f"SQLite file {target} opened in {rel}")
        if ext == ".php" and "ShouldQueue" in text and not any(
                w.startswith("Laravel queue worker") for w in app.out["background_work"]):
            app.add("background_work", f"queued job ({rel}): needs a queue worker")
        d, _, name = rel.rpartition("/")
        if d == app.path or d == self.join(app.path, "src") or d == self.join(app.path, "app"):
            self.entry_file(app, rel, name, ext, text)

    def entry_file(self, app: App, rel: str, name: str, ext: str, text: str) -> None:
        if ext == ".py":
            if re.search(r"__name__\s*==\s*['\"]__main__['\"]", text):
                app.add("entry_points", f"python {rel} (runs as a script)")
            m = re.search(r"(?m)^(\w+)\s*=\s*(Flask|FastAPI|Starlette|Quart|Sanic|Litestar)\(", text)
            if m:
                module = rel[len(app.path) + 1 if app.path else 0:-3].replace("/", ".")
                app.add("entry_points", f"{module}:{m.group(1)} ({m.group(2)} app object in {rel})")
            if name in ("wsgi.py", "asgi.py"):
                app.add("entry_points", f"{rel} ({name[:4].upper()} entry)")
        elif ext in (".js", ".mjs", ".cjs", ".ts") and name.split(".")[0] in ("server", "index", "app", "main"):
            if ".listen(" in text and not any(e.startswith("start command") for e in app.out["entry_points"]):
                app.add("entry_points", f"{rel} (calls listen)")
        elif ext == ".go" and name == "main.go":
            app.add("entry_points", f"go run ./{rel.rpartition('/')[0] or '.'} (main.go)")
        elif ext == ".rs" and rel.endswith("src/main.rs"):
            app.add("entry_points", f"cargo run ({rel})")

    # -- per-file readers

    def package_json(self, app: App, rel: str) -> None:
        data = self.json(rel)
        if not isinstance(data, dict):
            return
        for section, dev in [("dependencies", False), ("optionalDependencies", False),
                             ("peerDependencies", False), ("devDependencies", True)]:
            deps = data.get(section)
            if isinstance(deps, dict):
                for name in deps:
                    app.dep("npm", str(name).lower(), dev)
        if app.has("npm", "typescript"):
            app.add("languages", "TypeScript")
        scripts = data.get("scripts") if isinstance(data.get("scripts"), dict) else {}
        for key in ("start", "serve", "build"):
            cmd = scripts.get(key)
            if isinstance(cmd, str) and cmd.strip():
                label = "build command" if key == "build" else f"{key} command"
                app.add("entry_points", f"{label}: {safe_command(cmd)} ({rel})")
                for port in command_ports(cmd):
                    app.add("ports", f"{port} ({rel} script {key})")
        for key, cmd in scripts.items():
            if isinstance(cmd, str) and WORKER_RE.search(str(key)):
                app.add("background_work", f"script {key}: {safe_command(cmd)} ({rel})")

    def composer_json(self, app: App, rel: str) -> None:
        data = self.json(rel)
        if not isinstance(data, dict):
            return
        for section, dev in [("require", False), ("require-dev", True)]:
            deps = data.get(section)
            if isinstance(deps, dict):
                for name in deps:
                    app.dep("php", str(name).lower(), dev)

    @staticmethod
    def py_name(spec: str) -> str | None:
        m = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", spec)
        return re.sub(r"[-_.]+", "-", m.group(1)).lower() if m else None

    def requirements(self, app: App, rel: str) -> None:
        dev = bool(re.search(r"dev|test|lint|doc", rel.rpartition("/")[2].lower()))
        for line in (self.read(rel) or "").splitlines():
            line = line.split("#", 1)[0].strip()
            if not line or line.startswith("-"):
                continue
            name = self.py_name(line)
            if name:
                app.dep("py", name, dev)
        app.add("languages", "Python")

    def pyproject(self, app: App, rel: str) -> None:
        data = self.toml(rel)
        if not isinstance(data, dict):
            return
        project = data.get("project") or {}
        deps = project.get("dependencies")
        for spec in deps if isinstance(deps, list) else []:
            if isinstance(spec, str) and self.py_name(spec):
                app.dep("py", self.py_name(spec))
        for group in (project.get("optional-dependencies") or {}).values():
            for spec in group if isinstance(group, list) else []:
                if isinstance(spec, str) and self.py_name(spec):
                    app.dep("py", self.py_name(spec), True)
        for group in (data.get("dependency-groups") or {}).values():
            for spec in group if isinstance(group, list) else []:
                if isinstance(spec, str) and self.py_name(spec):
                    app.dep("py", self.py_name(spec), True)
        poetry = (data.get("tool") or {}).get("poetry") or {}
        for name in (poetry.get("dependencies") or {}):
            if name.lower() != "python":
                app.dep("py", self.py_name(name) or name.lower())
        for group in (poetry.get("group") or {}).values():
            for name in (group.get("dependencies") or {}) if isinstance(group, dict) else {}:
                app.dep("py", self.py_name(name) or name.lower(), True)
        for name, target in (project.get("scripts") or {}).items():
            app.add("entry_points", f"console script {_target(str(name))} -> {_target(str(target))} ({rel})")

    def pipfile(self, app: App, rel: str) -> None:
        data = self.toml(rel)
        if isinstance(data, dict):
            for section, dev in [("packages", False), ("dev-packages", True)]:
                for name in data.get(section) or {}:
                    app.dep("py", self.py_name(name) or name.lower(), dev)

    def gemfile(self, app: App, rel: str) -> None:
        for name in re.findall(r"(?m)^\s*gem\s+['\"]([^'\"]+)['\"]", self.read(rel) or ""):
            app.dep("ruby", name.lower())

    def go_mod(self, app: App, rel: str) -> None:
        for mod in re.findall(r"(?m)^\s*(?:require\s+)?([a-z0-9][\w.\-]*\.[a-z]{2,}/[^\s]+)\s+v\d", self.read(rel) or ""):
            app.dep("go", mod.lower())

    def cargo(self, app: App, rel: str) -> None:
        data = self.toml(rel)
        if isinstance(data, dict):
            for section, dev in [("dependencies", False), ("dev-dependencies", True)]:
                for name in data.get(section) or {}:
                    app.dep("rust", name.lower(), dev)

    def java(self, app: App, rel: str) -> None:
        text = self.read(rel) or ""
        for needle, key, label in JAVA_HINTS:
            if needle in text:
                app.add(key, label)
        if "kotlin" in text:
            app.add("languages", "Kotlin")

    def mix(self, app: App, rel: str) -> None:
        if ":phoenix" in (self.read(rel) or ""):
            app.dep("elixir", "phoenix")

    def deno(self, app: App, rel: str) -> None:
        app.add("frameworks", "Deno runtime")

    def env_file(self, app: App, rel: str) -> None:
        text = self.read(rel)
        if text is None:
            return
        names, confident = env_file_names(text)
        self.add_names(app, rel, names)
        if not confident:
            self.note(UNCLEAR_NAMES.format(rel=rel))
        name = rel.rpartition("/")[2]
        if name == ".env" or (name.startswith(".env.") and not re.search(r"example|sample|template|dist", name)):
            ignore = self.read(self.join(rel.rpartition("/")[0], ".gitignore")) or self.read(".gitignore") or ""
            if ".env" not in ignore:
                app.add("runtime_needs", f"{rel} holds settings, possibly secrets, and no .gitignore next to it or "
                        "at the top mentions .env; check it is not committed (its values were not printed)")

    def dockerfile(self, app: App, rel: str) -> None:
        app.add("container_files", rel)
        text = (self.read(rel) or "").replace("\\\r\n", " ").replace("\\\n", " ")
        for line in text.splitlines():
            parts = line.strip().split(None, 1)
            if len(parts) < 2:
                continue
            op, arg = parts[0].upper(), parts[1].strip()
            if op == "FROM":
                image = next((t for t in arg.split() if not t.startswith("--")), "").lower()
                base = image.rsplit("/", 1)[-1].split(":")[0]
                lang = {"node": "JavaScript", "python": "Python", "php": "PHP", "ruby": "Ruby", "golang": "Go",
                        "rust": "Rust", "openjdk": "Java", "eclipse-temurin": "Java", "deno": "TypeScript",
                        "bun": "JavaScript", "elixir": "Elixir"}.get(base)
                if lang:
                    app.add("languages", lang)
                if base in PROXY_IMAGES:
                    app.add("runtime_needs", f"serves through {base} inside the container ({rel})")
            elif op == "EXPOSE":
                for port in re.findall(r"\b(\d{2,5})\b", arg):
                    app.add("ports", f"{port} (EXPOSE in {rel})")
            elif op in ("CMD", "ENTRYPOINT"):
                try:
                    value = json.loads(arg) if arg.startswith("[") else arg
                except ValueError:
                    value = arg
                app.add("entry_points", f"{op} in {rel}: {safe_command(value)}")
                for port in command_ports(value):
                    app.add("ports", f"{port} ({op} in {rel})")
            elif op in ("ENV", "ARG"):
                names, confident = dockerfile_env_names(arg)
                self.add_names(app, rel, names)
                if not confident:
                    self.note(UNCLEAR_NAMES.format(rel=rel))
            elif op == "VOLUME":
                app.add("state_on_disk", f"container volume {_plain(arg)} ({rel})")

    def compose(self, app: App, rel: str) -> None:
        app.add("container_files", rel)
        text = self.read(rel) or ""
        lines = [line.rstrip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
        if any(_document_marker(line) and line.strip().startswith("---") for line in lines[1:]):
            self.note(f"{rel} holds several YAML documents; it was not read")
            return
        data = self.yaml(rel)
        if not isinstance(data, dict):
            return
        services = data.get("services")
        if not isinstance(services, dict):
            services = {k: v for k, v in data.items() if isinstance(v, dict) and ("image" in v or "build" in v)}
        for name, svc in services.items():
            if not isinstance(svc, dict):
                self.note(f"service {_plain(name)} in {rel} could not be read")
                continue
            where = f"{rel}, service {name}"
            image = str(svc.get("image") or "")
            base = image.lower().rsplit("/", 1)[-1].split(":")[0].split("@")[0]
            store = next((label for names, label in IMAGE_STORES if base in names), None)
            if store:
                app.add("datastores", f"{store} ({where}, image {_plain(image)})")
            elif base in PROXY_IMAGES:
                app.add("runtime_needs", f"reverse proxy {base} ({where})")
            command = svc.get("command") or svc.get("entrypoint")
            if not store and (WORKER_RE.search(str(name)) or (command and WORKER_RE.search(command_text(command)))):
                app.add("background_work", f"service {name}: {safe_command(command) if command else 'no command given'} "
                        f"({rel})")
            elif command and not store:
                app.add("entry_points", f"service {name}: {safe_command(command)} ({rel})")
            for port in svc.get("ports") or []:
                published, target = self.compose_port(port)
                if target:
                    app.add("ports", f"{target} ({where})")
                if store and published and not published.startswith(("127.0.0.1", "localhost", "[::1]")):
                    app.add("runtime_needs", f"{store} port published on every address ({where}); a database "
                            "should not be reachable from the internet")
            for vol in svc.get("volumes") or []:
                src, dst = self.compose_volume(vol)
                if dst is None:
                    continue
                if src and src.startswith((".", "/", "~")):
                    app.add("state_on_disk", f"bind mount {src} -> {dst} ({where})")
                elif src:
                    app.add("state_on_disk", f"named volume {src} at {dst} ({where})")
                else:
                    app.add("state_on_disk", f"anonymous volume at {dst} ({where})")
            env = svc.get("environment")
            if isinstance(env, dict):
                names = [str(k) for k in env]
            elif isinstance(env, list) and all(isinstance(e, str) for e in env):
                names = [e.split("=", 1)[0] for e in env]
            elif env is None:
                names = []
            else:
                names = None
            if names is None or not all(is_variable_name(n) for n in names):
                self.note(UNCLEAR_NAMES.format(rel=rel))
                continue
            self.add_names(app, rel, names)

    @staticmethod
    def compose_port(port) -> tuple[str | None, str | None]:
        if isinstance(port, dict):
            return (str(port.get("published")) if port.get("published") else None,
                    str(port.get("target")) if port.get("target") else None)
        text = str(port).split("/")[0]
        pieces = text.rsplit(":", 1)
        target = pieces[-1]
        published = pieces[0] if len(pieces) == 2 else None
        return published, target if re.fullmatch(r"\d{1,5}(-\d{1,5})?", target) else None

    @staticmethod
    def compose_volume(vol) -> tuple[str | None, str | None]:
        if isinstance(vol, dict):
            return (str(vol["source"]) if vol.get("source") else None,
                    str(vol["target"]) if vol.get("target") else None)
        pieces = str(vol).split(":")
        if len(pieces) == 1:
            return None, pieces[0]
        return pieces[0], pieces[1]

    def procfile(self, app: App, rel: str) -> None:
        app.add("existing_hosting", f"Procfile ({rel}): process file read by Heroku, Dokku and similar platforms")
        for line in (self.read(rel) or "").splitlines():
            m = re.match(r"^\s*([A-Za-z0-9_-]+)\s*:\s*(.+)$", line)
            if not m:
                continue
            kind, cmd = m.group(1), safe_command(m.group(2))
            if kind == "web":
                app.add("entry_points", f"Procfile web: {cmd}")
                if re.search(r"\$(?:PORT\b|\{PORT\})", m.group(2)):  # raw text, only tested
                    app.add("ports", f"reads the PORT variable ({rel})")
            elif kind == "release":
                app.add("entry_points", f"Procfile release step: {cmd}")
            else:
                app.add("background_work", f"Procfile process {kind}: {cmd}")

    def vercel(self, app: App, rel: str) -> None:
        app.add("existing_hosting", f"Vercel ({rel})")
        data = self.json(rel)
        crons = data.get("crons") if isinstance(data, dict) else None
        for cron in crons if isinstance(crons, list) else []:
            if isinstance(cron, dict):
                app.add("background_work", f"Vercel cron job {cron.get('path')} on schedule "
                        f"'{cron.get('schedule')}' ({rel})")

    def fly(self, app: App, rel: str) -> None:
        app.add("existing_hosting", f"Fly.io ({rel})")
        data = self.toml(rel)
        if not isinstance(data, dict):
            return
        services = [data.get("http_service")] + list(data.get("services") or [])
        for svc in services:
            if isinstance(svc, dict) and svc.get("internal_port"):
                app.add("ports", f"{svc['internal_port']} (internal_port in {rel})")
        mounts = data.get("mounts")
        for mount in [mounts] if isinstance(mounts, dict) else mounts or []:
            if isinstance(mount, dict) and mount.get("destination"):
                app.add("state_on_disk", f"Fly volume {mount.get('source')} mounted at {mount['destination']} ({rel})")
        processes = data.get("processes")
        if isinstance(processes, dict):
            for name, cmd in processes.items():
                if name in ("app", "web"):
                    app.add("entry_points", f"Fly process {name}: {safe_command(cmd)} ({rel})")
                else:
                    app.add("background_work", f"Fly process {name}: {safe_command(cmd)} ({rel})")

    def render(self, app: App, rel: str) -> None:
        app.add("existing_hosting", f"Render ({rel})")
        data = self.yaml(rel)
        if not isinstance(data, dict):
            return
        for svc in data.get("services") or []:
            if not isinstance(svc, dict):
                continue
            kind, name = svc.get("type"), svc.get("name")
            cmd = safe_command(svc.get("startCommand") or "")
            if kind in ("web", "pserv"):
                if cmd:
                    app.add("entry_points", f"Render {kind} service {name}: {cmd} ({rel})")
            elif kind in ("worker", "cron"):
                extra = f" on schedule '{svc.get('schedule')}'" if kind == "cron" else ""
                app.add("background_work", f"Render {kind} {name}{extra}: {cmd or 'no command given'} ({rel})")
            elif kind in ("redis", "keyvalue"):
                app.add("datastores", f"Redis on Render, {name} ({rel})")
            if isinstance(svc.get("disk"), dict):
                app.add("state_on_disk", f"Render disk at {svc['disk'].get('mountPath')} ({rel})")
        for db in data.get("databases") or []:
            if isinstance(db, dict):
                app.add("datastores", f"PostgreSQL on Render, {db.get('name')} ({rel})")

    def railway(self, app: App, rel: str) -> None:
        app.add("existing_hosting", f"Railway ({rel})")
        data = self.json(rel) if rel.endswith(".json") else self.toml(rel)
        deploy = data.get("deploy") if isinstance(data, dict) else None
        if isinstance(deploy, dict):
            if deploy.get("startCommand"):
                app.add("entry_points", f"Railway start command: {safe_command(deploy['startCommand'])} ({rel})")
            if deploy.get("cronSchedule"):
                app.add("background_work", f"Railway cron schedule '{deploy['cronSchedule']}' ({rel})")

    def workflow(self, app: App, rel: str) -> None:
        text = self.read(rel) or ""
        hits = sorted(set(m.lower() for m in re.findall(
            r"(?i)\b(flyctl|vercel|netlify|railway|render|heroku|rsync|scp|ssh|kubectl|helm|docker push|"
            r"wrangler|gcloud|terraform|ansible|deploy)\b", text)))
        if hits:
            app.add("existing_hosting", f"GitHub Actions workflow {rel} mentions: {', '.join(hits)}")
        else:
            app.add("existing_hosting", f"GitHub Actions workflow {rel} (no deploy step recognised)")
        if re.search(r"(?m)^\s*schedule:\s*$", text) and "cron" in text:
            app.add("background_work", f"scheduled GitHub Actions workflow ({rel})")

    def maybe_kubernetes(self, app: App, rel: str) -> None:
        if self.files.get(rel, 0) > MAX_READ_BYTES:
            return
        text = self.read(rel) or ""
        if re.search(r"(?m)^apiVersion:", text) and re.search(
                r"(?m)^kind:\s*(Deployment|StatefulSet|DaemonSet|CronJob|Service|Ingress)\b", text):
            app.add("existing_hosting", f"Kubernetes manifest ({rel})")
            if re.search(r"(?m)^kind:\s*CronJob\b", text):
                app.add("background_work", f"Kubernetes CronJob ({rel})")
        elif rel.endswith("config/deploy.yml") and "servers:" in text and "image:" in text:
            app.add("existing_hosting", f"Kamal deploy config ({rel})")
        elif rel.rpartition("/")[2] in ("app.yaml", "app.yml") and re.search(r"(?m)^runtime:", text):
            app.add("existing_hosting", f"Google App Engine ({rel})")
        elif rel.endswith(".do/app.yaml"):
            app.add("existing_hosting", f"DigitalOcean App Platform ({rel})")

    # -- summary

    def languages(self, app: App) -> None:
        for lang, _ in sorted(app.ext_counts.items(), key=lambda kv: -kv[1]):
            app.add("languages", lang)
        if app.has("npm", "typescript") and "TypeScript" not in app.out["languages"]:
            app.add("languages", "TypeScript")

    def static_verdict(self, app: App) -> None:
        if "static-root" in app.flags:
            server_code = {k for k in app.ext_counts if k not in ("HTML", "JavaScript", "TypeScript")}
            if not server_code:
                app.flags.add("static")
                app.add("runtime_needs", "static files only: no server process, database or background work "
                        "found; any static host or a web server can serve the folder")
        frameworks = set(app.out["frameworks"])
        generators = STATIC_GENERATORS & frameworks
        if generators and not WEB_FRAMEWORKS & frameworks:
            app.flags.add("static-export")
            app.add("runtime_needs", f"builds to static files ({', '.join(sorted(generators))})")
        builders = SPA_BUILDERS & frameworks
        has_start = any(e.startswith(("start command", "serve command")) for e in app.out["entry_points"])
        if builders and not WEB_FRAMEWORKS & frameworks and not has_start:
            app.flags.add("static-export")
            app.add("runtime_needs", f"single-page app built with {', '.join(sorted(builders))}: the build "
                    "output is static files; any API it calls runs elsewhere")

    def report(self) -> dict:
        everything = sorted(list(self.apps.values()) + [self.project], key=lambda a: (a.path != "", a.path))
        merged: dict[str, dict] = {k: {} for k in KEYS}
        merged_over: dict[str, int] = {}
        for app in everything:
            for key in KEYS:
                cap = MAX_ENV_NAMES if key == "env_vars" else MAX_MERGED
                for item in app.out[key]:
                    if item in merged[key]:
                        continue
                    if len(merged[key]) >= cap:
                        merged_over[key] = merged_over.get(key, 0) + 1
                    else:
                        merged[key][item] = None
        lists = {k: (sorted(v) if k == "env_vars" else list(v)) for k, v in merged.items()}
        out = {k: lists[k] for k in KEYS[:10]}
        out["apps_found"] = len(self.apps)
        out["not_determined"] = self.not_determined(lists, merged_over)
        out["runtime_needs"] = lists["runtime_needs"]
        out["package_managers"] = lists["package_managers"]
        out["apps"] = [dict({"path": a.path or "."}, **{k: (sorted(a.out[k]) if k == "env_vars" else list(a.out[k]))
                                                          for k in KEYS})
                       for a in sorted(self.apps.values(), key=lambda a: a.path)[:MAX_APPS_LISTED]]
        out["scan"] = {"files_seen": len(self.files), "files_read": self.files_read,
                       "max_files": self.max_files, "max_depth": self.max_depth}
        return out

    def not_determined(self, merged: dict, merged_over: dict) -> list[str]:
        out: list[str] = []
        if not self.files:
            out.append("no files were found in the folder, so nothing about the app could be determined")
            out.extend(self.limits())
            return out
        if not self.apps:
            out.append("no app was recognised: no manifest (package.json, requirements.txt, composer.json, "
                       "go.mod and similar), Dockerfile or index.html was found; language, framework and "
                       "start command are not determined")
        if len(self.apps) > 1:
            out.append(f"how the {len(self.apps)} apps relate to each other (deployed together or apart, which "
                       "one faces the public) is not determined")
        if len(self.apps) > MAX_APPS_LISTED:
            out.append(f"only the first {MAX_APPS_LISTED} of the {len(self.apps)} apps are listed under apps")
        servers = [a for a in self.apps.values() if not {"static", "static-export"} & a.flags]
        if servers and not merged["datastores"]:
            out.append("whether a database is needed: none was found in dependencies, compose files or settings")
        if any("db-engine-in-env" in a.flags for a in self.apps.values()):
            out.append("which database engine Laravel uses: it is set by DB_CONNECTION, whose value is not read")
        if "DATABASE_URL" in merged["env_vars"]:
            out.append("which database DATABASE_URL points to: its value is not read")
        if any(i.startswith("GPU library") for i in merged["runtime_needs"]):
            out.append("whether a GPU is really required: these libraries also run on a CPU, more slowly")
        if merged["env_vars"]:
            out.append("the values of the environment variables: only names are listed, values were not printed")
        out.append("how many people will use the app, when the load peaks and how long an outage may last: "
                   "these come from the owner, not from the code")
        out.extend(self.notes)
        if self.notes_dropped:
            out.append(f"{self.notes_dropped} more notes about single files were not listed")
        out.extend(self.limits())
        for key, count in merged_over.items():
            cap = MAX_ENV_NAMES if key == "env_vars" else MAX_MERGED
            out.append(f"{count} more {key.replace('_', ' ')} entries were not listed in the combined lists "
                       f"(limit {cap})")
        over_apps = [a for a in everything_sorted(self) if a.overflow]
        for app in over_apps[:MAX_APP_NOTES]:
            label = f"app at {app.path}" if app.path else ("the app" if app is not self.project else "the project")
            for key, count in app.overflow.items():
                out.append(f"{count} more {key.replace('_', ' ')} entries for {label} were not listed")
        if len(over_apps) > MAX_APP_NOTES:
            out.append(f"{len(over_apps) - MAX_APP_NOTES} more apps had entries that were not listed")
        app_notes = []
        for app in sorted(self.apps.values(), key=lambda a: a.path):
            label = f"app at {app.path}" if app.path else "the app"
            if "static" in app.flags:
                continue
            frameworks = set(app.out["frameworks"])
            if not app.out["entry_points"] and "static-export" not in app.flags:
                app_notes.append(f"how {label} is started: no start command or entry file was found")
            if frameworks & WEB_FRAMEWORKS and not frameworks & PHP_FRAMEWORKS and not app.out["ports"] \
                    and "static-export" not in app.flags:
                app_notes.append(f"which port {label} listens on")
        out.extend(app_notes[:MAX_APP_NOTES])
        if len(app_notes) > MAX_APP_NOTES:
            out.append(f"{len(app_notes) - MAX_APP_NOTES} more notes like these about single apps were not listed")
        return list(dict.fromkeys(out))

    def limits(self) -> list[str]:
        out = []

        def examples(items):
            shown = ", ".join(items[:3])
            return shown + (", ..." if len(items) > 3 else "")

        if self.file_limit_hit:
            out.append(f"the scan stopped after {self.max_files} files (--max-files); the rest of the project "
                       "was not read")
        if self.skipped_build:
            out.append(f"{len(self.skipped_build)} folder(s) skipped as build output or environments were not "
                       f"read, for example {examples(self.skipped_build)}; if the app's own code lives there, it "
                       "was not seen")
        if self.too_deep:
            out.append(f"folders deeper than {self.max_depth} levels were not read (--max-depth), for example "
                       f"{examples(self.too_deep)}")
        if self.hidden:
            out.append(f"{len(self.hidden)} hidden folder(s) were not read (tool settings and caches), for "
                       f"example {examples(self.hidden)}")
        if self.symlinks:
            out.append(f"{len(self.symlinks)} symbolic link(s) were not followed, for example "
                       f"{examples(self.symlinks)}")
        if self.special:
            out.append(f"{len(self.special)} special file(s) (pipes, sockets, devices) were not read, for example "
                       f"{examples(self.special)}")
        unreadable = list(dict.fromkeys(u for u in self.unreadable if u))
        if unreadable:
            out.append(f"{len(unreadable)} file(s) or folder(s) could not be read, for example {examples(unreadable)}")
        if self.truncated:
            out.append(f"{len(self.truncated)} large file(s) were read only in part, for example "
                       f"{examples(self.truncated)}")
        if self.source_skipped:
            out.append(f"{self.source_skipped} source file(s) were not read because the read budget ran out")
        return out


def everything_sorted(scan: Scan) -> list:
    return sorted(list(scan.apps.values()) + [scan.project], key=lambda a: (a is not scan.project, a.path))


def _host_handler(label: str):
    def handler(scan: Scan, app: App, rel: str) -> None:
        app.add("existing_hosting", f"{label} ({rel})")
    return handler


HANDLERS = {
    "package.json": Scan.package_json,
    "composer.json": Scan.composer_json,
    "pyproject.toml": Scan.pyproject,
    "Pipfile": Scan.pipfile,
    "Gemfile": Scan.gemfile,
    "go.mod": Scan.go_mod,
    "Cargo.toml": Scan.cargo,
    "pom.xml": Scan.java,
    "build.gradle": Scan.java,
    "build.gradle.kts": Scan.java,
    "mix.exs": Scan.mix,
    "deno.json": Scan.deno,
    "deno.jsonc": Scan.deno,
    "Procfile": Scan.procfile,
    "vercel.json": Scan.vercel,
    "fly.toml": Scan.fly,
    "render.yaml": Scan.render,
    "railway.json": Scan.railway,
    "railway.toml": Scan.railway,
}
for _name, _label in [("netlify.toml", "Netlify"), ("app.json", "Heroku app manifest"), ("heroku.yml", "Heroku"),
                      ("firebase.json", "Firebase Hosting"), ("wrangler.toml", "Cloudflare Workers"),
                      ("wrangler.json", "Cloudflare Workers"), ("wrangler.jsonc", "Cloudflare Workers"),
                      ("amplify.yml", "AWS Amplify"), ("serverless.yml", "Serverless Framework"),
                      ("serverless.ts", "Serverless Framework"), (".platform.app.yaml", "Platform.sh"),
                      ("Dockerrun.aws.json", "AWS Elastic Beanstalk"), ("captain-definition", "CapRover"),
                      ("nixpacks.toml", "Nixpacks build config"), ("Chart.yaml", "Helm chart"),
                      ("ecosystem.config.js", "PM2 process manager"), ("ecosystem.config.cjs", "PM2 process manager"),
                      ("now.json", "Vercel (legacy now.json)")]:
    HANDLERS[_name] = _host_handler(_label)


def _supabase_handler(scan: Scan, app: App, rel: str) -> None:
    if rel.endswith("supabase/config.toml"):
        app.add("existing_hosting", f"Supabase project ({rel})")
        base = rel.rpartition("/")[0]
        if any(r.startswith(base + "/migrations/") for r in scan.files):
            app.add("datastores", f"PostgreSQL schema in {base}/migrations (Supabase)")
        if any(r.startswith(base + "/functions/") for r in scan.files):
            app.add("existing_hosting", f"Supabase Edge Functions ({base}/functions)")


HANDLERS["config.toml"] = _supabase_handler


class Parser(argparse.ArgumentParser):
    """argparse that reports a usage error as one line on stderr and exits 2."""

    def error(self, message):
        print(f"usage error: {message} (see --help)", file=sys.stderr)
        sys.exit(2)


def _positive(text: str) -> int:
    if not text.isdigit() or int(text) < 1:
        raise argparse.ArgumentTypeError(f"'{text}' is not a whole number of 1 or more")
    return int(text)


def _depth(text: str) -> int:
    if not text.isdigit():
        raise argparse.ArgumentTypeError(f"'{text}' is not a whole number of 0 or more")
    return int(text)


def main(argv: list[str] | None = None) -> int:
    parser = Parser(prog="detect_project.py", formatter_class=argparse.RawDescriptionHelpFormatter,
                    description="Describe a project folder for deployment and print one JSON object.",
                    epilog="Output keys: languages, frameworks, entry_points, datastores, background_work, "
                           "state_on_disk, ports, env_vars, container_files, existing_hosting, apps_found, "
                           "not_determined, runtime_needs, package_managers, apps (one entry per app found) "
                           "and scan (counts). Exit codes: 0 printed, 2 bad usage.\n\n"
                           "Commands are printed fail closed: <value> stands for a flag's value, <arg> for an "
                           "argument, <script> for a shell -c script, -<flag> for a flag name that is not on the "
                           "known list, <program> for a program name that does not read like one, and "
                           "<name>=<value> for an inline assignment whose name is not in capitals. Only the target "
                           "of a known runner (node server.js, gunicorn app:app) is shown; a secret written in a target position "
                           "would print. When the exact command "
                           "is needed, open the file itself.\n\n"
                           "Needs Python 3.9 or newer, standard library only. On Python 3.9 and 3.10 TOML "
                           "files (pyproject.toml, Cargo.toml and others) are listed under not_determined as "
                           "not read.")
    parser.add_argument("path", help="the project folder to describe")
    parser.add_argument("--max-files", type=_positive, default=DEFAULT_MAX_FILES, metavar="N",
                        help=f"stop after this many files (default {DEFAULT_MAX_FILES})")
    parser.add_argument("--max-depth", type=_depth, default=DEFAULT_MAX_DEPTH, metavar="N",
                        help=f"do not enter folders deeper than this (default {DEFAULT_MAX_DEPTH})")
    args = parser.parse_args(argv)
    root = os.path.realpath(args.path)
    if not os.path.isdir(root):
        parser.error(f"{args.path} is not a folder")
    try:
        report = Scan(root, args.max_files, args.max_depth).run()
    except RecursionError:
        print("error: a file was nested too deeply to read", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))  # ASCII only: any file name keeps the output one valid JSON object
    return 0


if __name__ == "__main__":
    sys.exit(main())
