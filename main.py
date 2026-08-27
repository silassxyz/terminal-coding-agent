import os
import subprocess
import sys
from dotenv import load_dotenv
from google import genai
from google.genai import errors as genai_errors
import click
import time

# Load environment variables (API key, model name, retry settings) from .env
load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.7-flash")
MAX_RETRIES = int(os.getenv("MAX_RETRIES", 3))  # how many code-fix attempts before giving up
API_MAX_RETRIES = int(os.getenv("API_MAX_RETRIES", 5))  # how many times to retry a single API call on 503
API_RETRY_BASE_DELAY = float(os.getenv("API_RETRY_BASE_DELAY", 2))  # base delay (s) for exponential backoff

if not API_KEY:
    print("Fehler: GEMINI_API_KEY nicht gefunden. Prüfe deine .env Datei.")
    sys.exit(1)

client = genai.Client(api_key=API_KEY)


def read_file(filepath):
    """Read the target source file into a string."""
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()


def write_file(filepath, content):
    """Overwrite the target source file with newly generated code."""
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)


def run_tests(test_command):
    """Run the given test command and report pass/fail plus combined output.

    If the command starts with "pytest", it's rerun as `python -m pytest`
    so it works even when pytest isn't a directly callable executable on PATH.
    """
    args = test_command.split()
    if args and args[0] == "pytest":
        args = [sys.executable, "-m", "pytest"] + args[1:]

    result = subprocess.run(
        args,
        capture_output=True,
        text=True
    )
    passed = result.returncode == 0
    output = result.stdout + result.stderr
    return passed, output


def call_llm(task, code, error=None):
    """Ask the LLM to write or fix code for the given task.

    Builds a prompt (a "fix" prompt if a previous test error is passed in,
    otherwise a "write from scratch" prompt), then calls the Gemini API.
    Transient server overload (503) is retried with exponential backoff;
    all other errors (e.g. invalid model, bad request) propagate immediately.
    """
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

    for attempt in range(1, API_MAX_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model=MODEL,
                contents=prompt
            )
            return clean_code_response(response.text)
        except genai_errors.ServerError as e:
            if attempt == API_MAX_RETRIES:
                raise  # give up after the last attempt, let the caller handle it
            delay = API_RETRY_BASE_DELAY * (2 ** (attempt - 1))  # 2s, 4s, 8s, ...
            click.echo(f"API überlastet ({e}). Warte {delay:.0f}s und versuche erneut ({attempt}/{API_MAX_RETRIES})...")
            time.sleep(delay)


def clean_code_response(text):
    """Strip a Markdown code fence (```python ... ```) if the model added one."""
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
    """Agent loop: generate code, run tests, and feed failures back to the
    LLM until the tests pass or MAX_RETRIES is exhausted."""
    click.echo(f"Starte Agent für: {file}")
    click.echo(f"Aufgabe: {task}\n")

    code = read_file(file)
    error = None  # None on the first attempt -> "write" prompt; set to test output on retries -> "fix" prompt

    for attempt in range(1, MAX_RETRIES + 1):
        click.echo(f"--- Versuch {attempt}/{MAX_RETRIES} ---")

        new_code = call_llm(task, code, error)
        write_file(file, new_code)
        click.echo("Code geschrieben. Führe Tests aus...")

        passed, output = run_tests(test_command)

        if passed:
            click.echo("[OK] Tests erfolgreich!")
            return
        else:
            click.echo("[FAIL] Tests fehlgeschlagen.")
            click.echo(output)
            error = output  # feed the failure into the next call_llm() as fix context
            code = new_code

    click.echo(f"\n[WARN] Nach {MAX_RETRIES} Versuchen konnten die Tests nicht bestanden werden.")


if __name__ == "__main__":
    main()