# TermiLLM

**English | [Türkçe](README.md)**

An open-ended LLM chat agent for the terminal, written in Python. It talks to a local or remote **llama.cpp server** (or any OpenAI-compatible API), rendering **streaming** responses, the model's **reasoning/thinking** output, and **Markdown** formatting directly to the terminal in ANSI colors. Conversations are persisted on disk as sessions, context/token usage is tracked with a live bar, and history is automatically trimmed as the context fills up.

Other highlights:

- **Web search agent** — When needed, the model writes a `<web_search>query</web_search>` tag in its answer; the program runs the search (SearXNG or Tavily), feeds the results back to the model, and keeps looping until a plain answer arrives (up to 6 rounds).
- **Voice input** — `/ses` records the microphone (arecord) and transcribes it with whisper.cpp; `/ses <file>` transcribes an audio file. Text can also be injected from an external script through a named pipe.
- **File and image attachments** — Text files can be attached; with `/resim`, an image is sent multimodally (vision) along with your next message.
- **Session management** — Each conversation lives in its own folder under `chats/` (history, title, token log); on startup the most recent session is loaded automatically.

---

## Installation

### Requirements

- **Python 3.10+** (only `openai` and `python-dotenv` as pip dependencies; the search layer uses only the standard library)
- **Linux** (microphone recording uses `arecord`/ALSA and named pipes; other features are platform-independent)
- A running **llama.cpp server** (or an OpenAI-compatible endpoint)

Optional components:

| Component | Needed for | Note |
|---|---|---|
| `whisper-cli` (whisper.cpp) | Audio transcription | CachyOS/Arch: `paru -S whisper.cpp` |
| `arecord` (alsa-utils) | Microphone recording | CachyOS/Arch: `paru -S alsa-utils` |
| SearXNG instance or Tavily API key | Web search | See setup below |

### Steps

```bash
cd TermiLLM
bash setup.sh          # creates a virtualenv named "libr" and installs dependencies
```

Then create a `.env` file in the project root:

```dotenv
SERVER_BASE=http://127.0.0.1:8080
base_url=http://127.0.0.1:8080/v1
api_key=sk-...
```

- `SERVER_BASE` — used to discover the context size via the `/props` and `/slots` endpoints.
- `base_url` — full address of the OpenAI-compatible chat endpoint (e.g. `SERVER_BASE/v1`).
- `api_key` — ignored by llama.cpp server; a real key for remote services.

Optional environment variables:

```dotenv
WHISPER_BIN=whisper-cli                          # path to the whisper.cpp binary
WHISPER_MODEL=~/whisper.cpp/models/ggml-base.bin # GGML model file
WHISPER_LANG=tr                                  # transcription language
LLAMA_PIPE=/tmp/llama_input.pipe                 # named pipe path
```

Run:

```bash
source libr/bin/activate
python main.py
```

### Web search setup

Search settings live in `search_config.json` and can be changed while the program is running, either through the `/arama` menu or by editing the file directly (it is re-read on every search).

**SearXNG (self-hosted, recommended):** The bundled `searxng/settings.yml` enables the JSON format; run your own instance with Docker:

```bash
docker run -d --name searxng -p 9090:8080 \
  -v "$PWD/searxng:/etc/searxng" searxng/searxng
```

`search_config.json` points to `http://localhost:9090` by default. If SearXNG returns 403, the instance's `search.formats` list is missing `json` — the bundled `settings.yml` fixes that.

**Tavily (API key):** Enter your API key via the `/arama` menu (7) — input is hidden — and switch the provider (1) to `tavily`. No further setup needed.

---

## Usage & Commands

The program runs as a REPL: you type a message at the `Sen:` prompt (Turkish for "You"), and the answer streams in under the `Ajan:` ("Agent") header, followed by token statistics (`↳ input: … tok │ output: … tok │ total: … tok │ 24.3 tok/s (server)`).

### Session commands

| Command | Description |
|---|---|
| `/new` | Create a new conversation |
| `/chats` | List conversations (title, session ID, first 80 chars of the last message) |
| `/open N` | Open conversation N from the list |
| `/rename <new title>` | Rename the active conversation |
| `/delete N` | Delete conversation N (if the active one is deleted, the newest opens) |
| `/clear` | Reset the active conversation's history and pending attachments |
| `/stats` | Message count, context tokens, total input/output tokens |
| `/debug` | Toggle debug mode (raw stream chunks are written to `debug.log`) |
| `/help` | Command list |
| `q` / `quit` | Exit |

### Media commands

| Command | Description |
|---|---|
| `/ses` | Record the microphone (stop with **Enter**), transcribe with Whisper, attach |
| `/ses <file>` | Transcribe an audio file (`.wav`) and attach it |
| `/read <file>` or `/dosya <file>` | Read a text file and attach it |
| `/resim <file>` | Attach an image (requires a vision-capable model) |

**Attachment flow:** `/ses`, `/read`, and `/resim` do not send anything immediately; content is held in memory and the prompt shows `📎 N ek bellekte bekliyor` ("N attachments pending"). It is sent together with your next message; pressing Enter on an empty line sends it with the request "Please examine the attached content in detail." Images travel as base64 only on their way to the model; the persistent history keeps a textual `[Resim: filename]` representation (so history.json stays small).

### Search commands

| Command | Description |
|---|---|
| `/ara <query>` or `/search <query>` | Forced search: search the web first, then send results + query to the model |
| `/arama` | Search settings menu: provider selection, SearXNG URL/language/safesearch/categories, Tavily base URL and API key, result count, connection test |
| *(automatic)* | The model issues `<web_search>` calls itself on questions that need up-to-date information |

**Agent loop:** When a `<web_search>query</web_search>` tag appears in the model's answer, the stream is cut off at that point, the query runs, and the results are fed back to the model as a `"--- Web Arama Sonuçları ---"` (web search results) block; the model's reply is streamed again. This continues until the model answers plainly or the 6-round limit (`MAX_SEARCH_ROUNDS`) is reached. The model is instructed to cite source URLs when relying on search results.

---

## Details

### Context management

- At startup the context size is read from `SERVER_BASE/props`, then `SERVER_BASE/slots` (`n_ctx`); if both fail it falls back to 4096 with a warning.
- The usable budget is `n_ctx × 0.85` (safety margin); a colored context bar is shown each turn in the REPL (green < 60%, yellow < 85%, red above).
- When the budget is exceeded, history is trimmed in **user/assistant pairs** (oldest first); conversation ordering is never broken.
- Token statistics use the server's real usage values; if the server reports none, an approximate value (characters/4) is shown with a `~` marker.

### Session storage

```text
chats/
└── 2026-08-14_14-49-02/     # session ID = creation timestamp
    ├── history.json           # full conversation history
    ├── metadata.json          # title, creation time
    └── token_log.txt          # one "input,output" line per turn
```

The newest session loads automatically on startup. The formats are plain JSON/text; sessions can be moved around by hand.

### Audio and pipe integration

- Microphone audio is captured as 16 kHz mono WAV via `arecord`, passed to Whisper, and the temp file is deleted.
- A named pipe at `LLAMA_PIPE` (default `/tmp/llama_input.pipe`) is watched: if an external script (e.g. your own Whisper listening script) writes text to the pipe, it is auto-inserted into the prompt as a readline prefill — press Enter to send. Example external script:

```bash
#!/usr/bin/env bash
# whisper_dinle.sh — a simple example
arecord -f S16_LE -r 16000 -c 1 -q /tmp/recording.wav
whisper-cli -m ~/whisper.cpp/models/ggml-base.bin -f /tmp/recording.wav -l tr -nt \
  -otxt -of /tmp/output
cat /tmp/output.txt > /tmp/llama_input.pipe
```

### Model communication

- Requests go to the `chat.completions` streaming endpoint with `reasoning_effort: xhigh` and `enable_thinking` chat template kwargs (enables thinking mode on llama.cpp server).
- The thinking stream is captured two ways: OpenAI-style `reasoning_content` deltas and a `<think>…</think>` tag fallback. Thinking text is shown dimmed yellow under a `💭 Düşünüyor...` ("Thinking...") header.
- The Markdown formatter converts code blocks, inline code, bold text, headings, and blockquotes to ANSI colors — all processed on the fly (character by character) during streaming.
- The model name field is fixed (`"agent_model"`); llama.cpp server ignores it and serves whatever model it has loaded.

### Project structure

```text
TermiLLM/
├── main.py                  # composition root — wires objects, starts the app
├── application.py           # AgentApplication: startup flow + REPL loop
├── config.py                # .env + constants (Config dataclass)
├── state.py                 # runtime state (Application/Session/AttachmentState)
├── commands/
│   ├── router.py            # routes input to command classes
│   ├── session_commands.py  # /new /chats /open /rename /delete /clear
│   ├── media_commands.py    # /ses /read /dosya /resim
│   ├── search_commands.py   # /ara /search /arama
│   └── system_commands.py   # /stats /debug /help
├── chat/
│   ├── service.py           # message flow + agent search loop
│   ├── context.py           # token estimation, trimming, message building
│   └── attachments.py       # pending text/image attachments
├── llm/
│   ├── client.py            # OpenAI-compatible stream call
│   ├── stream.py            # <think>/<web_search> parser, StreamResult
│   └── server_info.py       # n_ctx discovery (/props, /slots)
├── sessions/
│   ├── manager.py           # application-level session behavior
│   └── storage.py           # disk operations (history/metadata/token log)
├── media/
│   ├── audio.py             # whisper.cpp transcription + arecord recording
│   ├── files.py             # text file loading
│   ├── images.py            # base64 data URI preparation
│   └── pipe.py              # named pipe listener + readline prefill
├── search/
│   ├── service.py           # search coordination + result formatting
│   ├── config.py            # search_config.json load/save
│   └── providers.py         # SearXNG and Tavily providers
├── ui/
│   ├── terminal.py          # prompt, context bar, help, stats, colors
│   ├── markdown.py          # Markdown → ANSI converter (streaming)
│   └── stream_renderer.py   # draws thinking/response stream to the terminal
├── searxng/settings.yml     # for a local SearXNG instance (JSON format enabled)
├── search_config.json       # search settings (editable at runtime)
├── setup.sh                 # virtualenv + dependency setup
└── save/main.py             # pre-refactor single-file version (reference)
```

Dependencies flow one way (`ui` ← `commands/chat` ← `sessions/llm/media`, etc.): the LLM layer knows nothing about session files, and storage knows nothing about the terminal. For the design document and the refactoring report (Turkish), see `readme.md` and `rapor.md` under `~/Desktop/ai/v7/`.
