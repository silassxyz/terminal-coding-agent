import os
import subprocess
import sys
from dotenv import load_dotenv
from google import genai
import click
import time
# python main.py --file beispiel.py --task "Implementiere eine Funktion add(a, b), die zwei Zahlen addiert" --test-command "pytest test_beispiel.py"
# --- Setup ---
load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.7-flash")
MAX_RETRIES = int(os.getenv("MAX_RETRIES", 3))

if not API_KEY:
    print("Fehler: GEMINI_API_KEY nicht gefunden. Prüfe deine .env Datei.")
    sys.exit(1)

client = genai.Client(api_key=API_KEY)


def read_file(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()


def write_file(filepath, content):
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)


def run_tests(test_command):
    result = subprocess.run(
        test_command.split(),
        capture_output=True,
        text=True
    )
    passed = result.returncode == 0
    output = result.stdout + result.stderr
    return passed, output


def call_llm(task, code, error=None):
    if error:
        prompt = f"""
Task: {task}

Current code:
{code}

Test failed with this error:
{error}

Fix the code so the tests pass. Only output the corrected code, nothing else.

Fixed code:
"""
    else:
        prompt = f"""
Task: {task}

Current code:
{code}

Write the code to complete this task. Only output the code, nothing else.

Code:
"""

    response = client.models.generate_content(
        model=MODEL,
        contents=prompt
    )

    return clean_code_response(response.text)


def clean_code_response(text):
    # Entfernt Markdown-Codeblöcke (```python ... ```), falls das Modell die mitschickt
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]  # erste Zeile (```python) entfernen
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]  # letzte Zeile (```) entfernen
        text = "\n".join(lines)
    return text


@click.command()
@click.option("--file", required=True, help="Pfad zur Datei, die bearbeitet werden soll")
@click.option("--task", required=True, help="Beschreibung der Aufgabe")
@click.option("--test-command", required=True, help="Befehl zum Ausführen der Tests, z.B. 'pytest test_file.py'")
def main(file, task, test_command):
    click.echo(f"Starte Agent für: {file}")
    click.echo(f"Aufgabe: {task}\n")

    code = read_file(file)
    error = None

    for attempt in range(1, MAX_RETRIES + 1):
        click.echo(f"--- Versuch {attempt}/{MAX_RETRIES} ---")

        new_code = call_llm(task, code, error)
        write_file(file, new_code)
        click.echo("Code geschrieben. Führe Tests aus...")

        passed, output = run_tests(test_command)

        if passed:
            click.echo("✅ Tests erfolgreich!")
            return
        else:
            click.echo("❌ Tests fehlgeschlagen.")
            click.echo(output)
            error = output
            code = new_code

    click.echo(f"\n⚠️ Nach {MAX_RETRIES} Versuchen konnten die Tests nicht bestanden werden.")


if __name__ == "__main__":
    main()