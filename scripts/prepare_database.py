import argparse
import os
from pathlib import Path
import re
import subprocess
import sys
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
PASSWORD_NAMES = ("SCRAPBOOK_DB_APP_PASSWORD", "SCRAPBOOK_DB_MIGRATOR_PASSWORD")
ROLE_PASSWORDS = """
\\getenv app_password SCRAPBOOK_DB_APP_PASSWORD
\\getenv migrator_password SCRAPBOOK_DB_MIGRATOR_PASSWORD
BEGIN;
SELECT format('ALTER ROLE scrapbook_app PASSWORD %L', :'app_password') \\gexec
SELECT format('ALTER ROLE scrapbook_migrator PASSWORD %L', :'migrator_password') \\gexec
COMMIT;
"""


def run(args, *, env=None, stdin=None, cwd=ROOT):
    return subprocess.run(
        args, cwd=cwd, env=env, input=stdin, text=True, capture_output=True, check=True,
    ).stdout.strip()


def prepare(compose, liquibase):
    settings = dict(
        line.split("=", 1) for line in run([*compose, "config", "--environment"]).splitlines() if "=" in line
    )
    passwords = {name: settings.get(name, "") for name in PASSWORD_NAMES}
    if any(not re.fullmatch(r"[a-fA-F0-9]{32,128}", value) for value in passwords.values()):
        raise ValueError("Use senhas locais hexadecimais de 32 a 128 caracteres para aplicação e migração.")

    binding = run([*compose, "port", "postgres", "5432"])
    match = re.fullmatch(r"127\.0\.0\.1:(\d+)", binding)
    if not match:
        raise ValueError("A porta do PostgreSQL deve estar publicada exclusivamente em loopback.")

    bootstrap = (liquibase / "config/bootstrap.sql").read_text(encoding="utf-8")
    run(
        [
            *compose, "exec", "-T",
            "-e", PASSWORD_NAMES[0], "-e", PASSWORD_NAMES[1],
            "postgres", "psql", "-X", "-v", "ON_ERROR_STOP=1", "-U", "postgres", "-d", "scrapbook",
        ],
        env=os.environ | passwords,
        stdin=bootstrap + "\n" + ROLE_PASSWORDS,
    )
    run(
        [sys.executable, "scripts/migrate.py", "update"],
        env=os.environ | {
            "LIQUIBASE_COMMAND_URL": f"jdbc:postgresql://127.0.0.1:{match.group(1)}/scrapbook",
            "LIQUIBASE_COMMAND_PASSWORD": passwords[PASSWORD_NAMES[1]],
        },
        cwd=liquibase,
    )


def main():
    parser = argparse.ArgumentParser(description="Prepara o banco descartável ou persistente do Compose local.")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--project-name")
    parser.add_argument("--liquibase-dir", type=Path, default=ROOT.parent / "scrapbook-liquibase")
    args = parser.parse_args()
    compose = ["docker", "compose", "--file", str(ROOT / "compose.yaml"), "--env-file", str(args.env_file.resolve())]
    if args.project_name:
        compose.extend(("--project-name", args.project_name))

    execution = uuid4()
    try:
        prepare(compose, args.liquibase_dir.resolve())
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"Falha ao aplicar a alteração de banco. execução={execution} ambiente=local", file=sys.stderr)
        if isinstance(error, ValueError):
            print(str(error), file=sys.stderr)
        else:
            print("Confira a configuração local, o estado do PostgreSQL e o histórico do Liquibase.", file=sys.stderr)
        return 1

    print(f"Base PostgreSQL preparada pelo Liquibase. execução={execution} ambiente=local")
    return 0


if __name__ == "__main__":
    sys.exit(main())
