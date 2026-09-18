# TermiLLM

**English | [Türkçe](README.md)**

An open-ended LLM chat agent for the terminal, written in Python. It talks to a local or remote **llama.cpp server** (or any OpenAI-compatible API), rendering **streaming** responses, the model's **reasoning/thinking** output, and **Markdown** formatting directly to the terminal in ANSI colors. Conversations are persisted on disk as sessions, context/token usage is tracked with a live bar, and history is automatically trimmed as the context fills up.

Other highlights:

- **Web search agent** — When needed, the model writes a `<web_search>query</web_search>` tag in its answer; the program runs the search (SearXNG or Tavily), feeds the results back to the model, and keeps looping until a plain answer arrives (up to 6 rounds).
- **File, image, and audio attachments** — Typing `@file` on the prompt opens a picker; text, images (`.png` `.jpg` …), or audio (`.wav` `.mp3` …) can be attached while you keep writing on the same line. Audio files are transcribed with Whisper. Live microphone input still goes through the named pipe (`whisper_dinle.sh`).
- **Inline web search** — `?"query"` searches on the same prompt line; `/ara` stores results for the next message. The model can also issue `<web_search>` itself.
- **Abort a reply** — **Ctrl+X** (or Ctrl+C during generation) stops the current turn without quitting; the HTTP socket is shut down so llama-server stops producing tokens.
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

- `SERVER_BASE` — used for local context-size discovery (llama.cpp `/props`).
- `base_url` — full address of the OpenAI-compatible chat endpoint (e.g. `SERVER_BASE/v1`, `https://api.x.ai/v1`, OpenRouter, OrcaRouter).
- `api_key` — ignored by llama.cpp server; a real key for remote services.

Optional environment variables:

```dotenv
WHISPER_BIN=whisper-cli                          # path to the whisper.cpp binary
WHISPER_MODEL=~/whisper.cpp/models/ggml-base.bin # GGML model file
WHISPER_LANG=tr                                  # transcription language
LLAMA_PIPE=/tmp/llama_input.pipe                 # named pipe path
CONTEXT_PROVIDER=llamacpp                        # force: llamacpp | openrouter | orcarouter | xai | openai | anthropic | claude
CONTEXT_FALLBACK=4096                            # used if discovery fails
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
| `Ctrl+X` | Abort the reply (app stays open; Ctrl+C during generation does the same) |
| `q` / `quit` | Exit |

### Media — `@` (inline)

`/read`, `/dosya`, `/ses`, and `/resim` are gone. Typing `@` on the prompt opens a file box; after picking a file you **keep writing on the same line**.

```text
Sen: @readme.md summarize this
Sen: @photo.png describe this image
Sen: @speech.wav transcribe this
Sen: @main.py @config.py compare these
```

| Key | Action |
|---|---|
| ↑ ↓ / Tab | move the selection |
| Enter | attach a file; enter a directory |
| `../` | go up one directory |
| Esc | close the box |
| + / − | grow / shrink the box |

Paths: `@src/`, `@../`, `@~/`, `@/abs/path/`. Names with spaces: `@"my file.txt"`.

- **images** `.png` `.jpg` `.jpeg` `.gif` `.webp` `.bmp` — vision model required
- **audio** `.wav` `.mp3` `.flac` `.ogg` `.m4a` `.opus` — transcribed with Whisper
- **other** — loaded as text

**Attachment flow:** Selected content stays in memory (`📎 N ek bellekte bekliyor`) and is sent with the prompt. Empty Enter sends it with “please examine the attached content.” Images travel as base64 only to the model; history stores `[Resim: filename]`.

### Search

| Command | Description |
|---|---|
| `?"query"` | Search inline; the rest of the line is the prompt (`?"python 3.14" summarize this`) |
| `/ara <query>` or `/search <query>` | Search the web and store results (sent with the next message) |
| `/arama` | Search settings: SearXNG / Tavily, language, result count, connection test |
| *(automatic)* | The model issues `<web_search>` itself when it needs up-to-date information |

**Agent loop:** When a `<web_search>query</web_search>` tag appears in the model's answer, the stream is cut off at that point, the query runs, and the results are fed back to the model as a `"--- Web Arama Sonuçları ---"` (web search results) block; the model's reply is streamed again. This continues until the model answers plainly or the 6-round limit (`MAX_SEARCH_ROUNDS`) is reached. The model is instructed to cite source URLs when relying on search results.

---

## Details

### Context management

- At startup the context size is read from the provider behind `base_url`: llama.cpp (`n_ctx` in `/props`), OpenRouter / OrcaRouter / xAI (`context_length`), Anthropic (`max_input_tokens`). Official OpenAI `/v1/models` does not expose context; the OpenRouter catalog is used as a fallback. If all fail, `CONTEXT_FALLBACK` (default 4096) is used.
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
- A named pipe at `LLAMA_PIPE` (default `/tmp/llama_input.pipe`) is watched: if an external script (e.g. your own Whisper listening script) writes text to the pipe, it is inserted into the prompt — press Enter to send. Example external script:

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
│   ├── search_commands.py   # /ara /search /arama
│   └── system_commands.py   # /stats /debug /help
├── chat/
│   ├── service.py           # message flow + agent search loop
│   ├── context.py           # token estimation, trimming, message building
│   ├── attachments.py       # pending text/image attachments
│   └── mentions.py          # @file and ?"query" parsing
├── llm/
│   ├── client.py            # OpenAI-compatible stream call
│   ├── stream.py            # <think>/<web_search> parser, StreamResult
│   ├── server_info.py       # context discovery (llamacpp, openrouter, xai, …)
│   ├── cancel.py            # abort turn with Ctrl+X / SIGINT
│   └── abort.py             # socket shutdown + llama-server /abort
├── sessions/
│   ├── manager.py           # application-level session behavior
│   └── storage.py           # disk operations (history/metadata/token log)
├── media/
│   ├── audio.py             # whisper.cpp transcription + arecord recording
│   ├── files.py             # text file loading
│   ├── images.py            # base64 data URI preparation
│   └── pipe.py              # named pipe listener
├── search/
│   ├── service.py           # search coordination + result formatting
│   ├── config.py            # search_config.json load/save
│   └── providers.py         # SearXNG and Tavily providers
├── ui/
│   ├── terminal.py          # prompt, context bar, help, stats, colors
│   ├── markdown.py          # Markdown → ANSI converter (streaming)
│   ├── stream_renderer.py   # draws thinking/response stream to the terminal
│   ├── line_edit.py         # line editor (box on @)
│   ├── picker.py            # file box (directory browsing)
│   ├── completer.py         # path matching
│   └── keys.py              # raw key reader
├── searxng/settings.yml     # for a local SearXNG instance (JSON format enabled)
├── search_config.json       # search settings (editable at runtime)
├── setup.sh                 # virtualenv + dependency setup
```

Dependencies flow one way (`ui` ← `commands/chat` ← `sessions/llm/media`, etc.): the LLM layer knows nothing about session files, and storage knows nothing about the terminal. For the design document and the refactoring report (Turkish), see `readme.md` and `rapor.md` under `~/Desktop/ai/v7/`.
