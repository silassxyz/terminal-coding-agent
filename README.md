# terminal-coding-agent
A terminal based coding agent that reads files, writes code, runs tests, and self-corrects on failure.

## Dependencies

- **google-genai** - Gemini API client, generates/fixes code
- **python-dotenv** - loads `GEMINI_API_KEY` & config from `.env`
- **click** - CLI arguments (`--file`, `--task`, `--test-command`)
- **pytest** - test runner invoked on the generated code
- **gitpython** *(unused yet)* - for programmatic git commit/rollback
- **rich** *(unused yet)* - nicer terminal output (colors, tables, progress bars)
- **tenacity** *(unused yet)* - retry handling for API errors

## Gemini API Connection

**How it works in code** (`main.py`):
- `.env` holds `GEMINI_API_KEY` and `GEMINI_MODEL`, loaded via `load_dotenv()`
- `client = genai.Client(api_key=API_KEY)` creates the client once at startup
- `call_llm()` sends the prompt with `client.models.generate_content(model=MODEL, contents=prompt)` and reads `response.text`
- Transient `503` (API overloaded) errors are retried automatically with exponential backoff, controlled by `API_MAX_RETRIES` / `API_RETRY_BASE_DELAY` in `.env`

**Testing the connection**

These reuse `main.py`'s own `client`/`MODEL` setup (via `import main`), so they test the exact config the script actually uses - not a separate copy:
- Quick check, no agent loop involved:
  ```bash
  python -c "import main; print(main.client.models.generate_content(model=main.MODEL, contents='Say hi').text)"
  ```
- List models available to your API key (also confirms `GEMINI_MODEL` in `.env` is valid):
  ```bash
  python -c "import main; [print(m.name) for m in main.client.models.list()]"
  ```
- Full end-to-end smoke test: point `main.py` at a throwaway file and test to confirm the whole loop (generate → write → test) works. `--file` must already exist (`read_file()` doesn't create it), so first create an empty `scratch_target.py` in the project root, plus a matching `test_scratch_target.py`:

  `scratch_target.py` (empty file):
  ```python
  ```

  `test_scratch_target.py`:
  ```python
  from scratch_target import add

  def test_add():
      assert add(2, 3) == 5
  ```

  Then run:
  ```bash
  python main.py --file scratch_target.py --task "Implement add(a, b)" --test-command "pytest test_scratch_target.py"
  ```
