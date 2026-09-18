# TermiLLM

**[English](README.en.md) | Türkçe**

Terminalde çalışan, Python ile yazılmış açık uçlu bir LLM sohbet ajanıdır. Yerel veya uzak bir **llama.cpp server** (veya herhangi bir OpenAI-compatible API) ile konuşur; akış (streaming) yanıtları, modelin **düşünme (reasoning)** çıktısını ve ANSI renkleriyle **Markdown** biçimlendirmesini doğrudan terminale render eder. Sohbetler diskte oturumlar halinde saklanır, context/token kullanımı canlı bir çubukla izlenir ve context dolunca geçmiş otomatik kırpılır.

Diğer önemli yetenekleri:

- **Web arama ajanı** — Model gerekirse yanıtında `<web_search>sorgu</web_search>` etiketi yazar; program aramayı çalıştırır (SearXNG veya Tavily), sonuçları modele geri besler ve düz cevap gelene dek döngüyü sürdürür (en fazla 6 tur).
- **Dosya, görsel ve ses ekleri** — Prompt satırında `@dosya` yazınca bir kutu açılır; metin, resim (`.png` `.jpg` …) veya ses (`.wav` `.mp3` …) seçilir, aynı satırda yazmaya devam edilir. Ses dosyaları Whisper ile yazıya çevrilir. Canlı mikrofon için named pipe (`whisper_dinle.sh`) durur.
- **Satır içi web arama** — `?"sorgu"` aynı prompt’ta arama yapar; `/ara` sonucu belleğe alır. Model ayrıca gerekirse kendisi `<web_search>` çağırır.
- **Yanıtı kesme** — Üretim sırasında **Ctrl+X** (veya Ctrl+C) turu keser; program kapanmaz, soket kapanır ki llama-server üretmeye devam etmesin.
- **Oturum yönetimi** — Her sohbet `chats/` altında kendi klasöründe tutulur (geçmiş, başlık, token logu); program açılışta en son sohbeti otomatik yükler.

---

## Kurulum

### Gereksinimler

- **Python 3.10+** (yalnızca `openai` ve `python-dotenv` pip bağımlılığı vardır; arama katmanı standart kütüphane ile çalışır)
- **Linux** (mikrofon kaydı `arecord`/ALSA ve named pipe kullanır; diğer özellikler platformdan bağımsızdır)
- Çalışan bir **llama.cpp server** (veya OpenAI-compatible bir endpoint)

İsteğe bağlı bileşenler:

| Bileşen | Ne için gerekli | Not |
|---|---|---|
| `whisper-cli` (whisper.cpp) | Ses transkripsiyonu | CachyOS/Arch: `paru -S whisper.cpp` |
| `arecord` (alsa-utils) | Mikrofon kaydı | CachyOS/Arch: `paru -S alsa-utils` |
| SearXNG örneği veya Tavily API key | Web arama | Kurulum için aşağıya bakın |

### Adımlar

```bash
cd TermiLLM
bash setup.sh          # "libr" adında sanal ortam oluşturur, bağımlılıkları kurar
```

Ardından proje kökünde bir `.env` dosyası oluşturun:

```dotenv
SERVER_BASE=http://127.0.0.1:8080
base_url=http://127.0.0.1:8080/v1
api_key=sk-...
```

- `SERVER_BASE` — yerelde context boyutu keşfi için kullanılır (llama.cpp `/props`).
- `base_url` — OpenAI-compatible chat endpoint'inin tam adresi (ör. `SERVER_BASE/v1`, `https://api.x.ai/v1`, OpenRouter, OrcaRouter).
- `api_key` — llama.cpp server'da yok sayılır; uzak servislerde gerçek anahtardır.

İsteğe bağlı ortam değişkenleri:

```dotenv
WHISPER_BIN=whisper-cli                          # whisper.cpp binary yolu
WHISPER_MODEL=~/whisper.cpp/models/ggml-base.bin # GGML model dosyası
WHISPER_LANG=tr                                  # transkripsiyon dili
LLAMA_PIPE=/tmp/llama_input.pipe                 # named pipe yolu
CONTEXT_PROVIDER=llamacpp                        # zorla: llamacpp | openrouter | orcarouter | xai | openai | anthropic | claude
CONTEXT_FALLBACK=4096                            # keşif başarısızsa
```

Çalıştırma:

```bash
source libr/bin/activate
python main.py
```

### Web arama kurulumu

Arama ayarları `search_config.json` dosyasında tutulur ve program çalışırken `/arama` menüsünden **veya dosyayı elle düzenleyerek** değiştirilebilir (her aramada yeniden okunur).

**SearXNG (self-hosted, önerilen):** Depodaki `searxng/settings.yml` JSON formatını etkinleştirir; Docker ile kendi örneğinizi çalıştırabilirsiniz:

```bash
docker run -d --name searxng -p 9090:8080 \
  -v "$PWD/searxng:/etc/searxng" searxng/searxng
```

`search_config.json` varsayılan olarak `http://localhost:9090`'a bakar. SearXNG 403 dönerse instance'ın `search.formats` listesinde `json` yok demektir — depodaki `settings.yml` bu sorunu çözer.

**Tavily (API key ile):** `/arama` menüsünden (7) API key girin — girdi gizlenir — ve sağlayıcıyı (1) `tavily` yapın. Ek kurulum gerekmez.

---

## Kullanım ve Komutlar

Program bir REPL olarak çalışır: `Sen:` prompt'una mesaj yazarsınız, yanıt `Ajan:` başlığıyla akarken render edilir ve altında token istatistiği gösterilir (`↳ giriş: … tok │ çıkış: … tok │ toplam: … tok │ 24.3 tok/s (server)`).

### Oturum komutları

| Komut | Açıklama |
|---|---|
| `/new` | Yeni sohbet oluştur |
| `/chats` | Sohbetleri listele (başlık, session ID, son mesajın ilk 80 karakteri) |
| `/open N` | Listeden N numaralı sohbeti aç |
| `/rename <yeni başlık>` | Aktif sohbetin başlığını değiştir |
| `/delete N` | N numaralı sohbeti sil (aktif sohbet silinirse en yenisi açılır) |
| `/clear` | Aktif sohbetin geçmişini ve bekleyen ekleri sıfırla |
| `/stats` | Mesaj sayısı, context token'ı, toplam giriş/çıkış token'ı |
| `/debug` | Debug modunu aç/kapat (ham stream parçaları `debug.log`'a yazılır) |
| `/help` | Komut listesi |
| `Ctrl+X` | Yanıtı kes (program açık kalır; üretim sırasında Ctrl+C de aynı) |
| `q` / `quit` | Çıkış |

### Medya — `@` (satır içi)

`/read`, `/dosya`, `/ses` ve `/resim` yoktur. Prompt’ta `@` yazınca dosya kutusu açılır; seçimden sonra **aynı satırda yazmaya devam edilir**.

```text
Sen: @readme.md şunu özetle
Sen: @foto.png bu resmi açıkla
Sen: @konusma.wav bunu yazıya dök
Sen: @main.py @config.py karşılaştır
```

| Tuş | İş |
|---|---|
| ↑ ↓ / Tab | seçimi gez |
| Enter | dosyayı ekle; klasörse içine gir |
| `../` | üst dizine çık |
| Esc | kutuyu kapat |
| + / − | kutuyu büyüt / küçült |

Yollar: `@src/`, `@../`, `@~/`, `@/abs/yol/`. Boşluklu ad: `@"benim dosya.txt"`.

- **resim** `.png` `.jpg` `.jpeg` `.gif` `.webp` `.bmp` — vision model gerekir
- **ses** `.wav` `.mp3` `.flac` `.ogg` `.m4a` `.opus` — Whisper ile yazıya çevrilir
- **diğer** — metin olarak okunur

**Ek akışı:** Seçilen içerik bellekte bekler (`📎 N ek bellekte bekliyor`) ve prompt ile birlikte gider. Boş Enter, eki “ekteki içeriği incele” talebiyle gönderir. Görsel yalnızca modele giderken base64 taşınır; geçmişte `[Resim: dosyaadı]` kalır.

### Arama

| Komut | Açıklama |
|---|---|
| `?"sorgu"` | Satır içinde web ara; kalan metin prompt’tur (`?"python 3.14" bunu özetle`) |
| `/ara <sorgu>` veya `/search <sorgu>` | Web ara, sonucu belleğe al (sonraki mesajla gider) |
| `/arama` | Arama ayar menüsü: SearXNG / Tavily, dil, sonuç sayısı, bağlantı testi |
| *(otomatik)* | Model, güncel bilgi gerektiren sorularda kendisi `<web_search>` çağrısı yapar |

**Ajan döngüsü:** Model yanıtı içinde `<web_search>sorgu</web_search>` görüldüğünde stream o noktada durdurulur, sorgu çalıştırılır, sonuçlar `"--- Web Arama Sonuçları ---"` bloğu halinde modele geri verilir ve model yanıtı yeniden akıtılır. Model düz cevap verene veya 6 tur limitine (`MAX_SEARCH_ROUNDS`) ulaşana dek devam eder. Arama sonuçlarına dayanırken kaynak URL'ler modele istenir.

---

## Ayrıntılar

### Context yönetimi

- Açılışta context boyutu `base_url` üzerinden sağlayıcıdan okunur: llama.cpp (`/props` içindeki `n_ctx`), OpenRouter / OrcaRouter / xAI (`context_length`), Anthropic (`max_input_tokens`). Resmi OpenAI `/v1/models` context vermez; OpenRouter kataloğu yedek kaynaktır. Hepsi başarısızsa `CONTEXT_FALLBACK` (varsayılan 4096) kullanılır.
- Kullanılabilir bütçe `n_ctx × 0.85` (güvenlik payı) olarak hesaplanır; REPL'de her turda renkli bir context çubuğu gösterilir (yeşil < %60, sarı < %85, kırmızı üstü).
- Bütçe aşılırsa geçmiş **user/assistant çiftleri halinde** (en eskiden) kırpılır; konuşma sıralaması bozulmaz.
- Token istatistikleri server gerçek usage değerlerini kullanır; server bildirmezse `~` işaretiyle yaklaşık değer (karakter/4) gösterilir.

### Oturum deposu

```text
chats/
└── 2026-08-14_14-49-02/     # session ID = oluşturulma zamanı
    ├── history.json           # tüm konuşma geçmişi
    ├── metadata.json          # başlık, oluşturulma zamanı
    └── token_log.txt          # her tur için "giriş,çıkış" satırları
```

Açılışta en yeni oturum otomatik yüklenir. Format düz JSON/metindir; oturumlar elle de taşınabilir.

### Ses ve pipe entegrasyonu

- Mikrofon kaydı 16 kHz mono WAV olarak `arecord` ile alınır, Whisper'a verilir, geçici dosya silinir.
- `LLAMA_PIPE` (varsayılan `/tmp/llama_input.pipe`) üzerindeki bir named pipe dinlenir: harici bir betik pipe'a metin yazarsa (ör. kendi Whisper dinleme betiğiniz) metin prompt'a doldurulur — Enter'a basıp gönderirsiniz. Örnek harici betik:

```bash
#!/usr/bin/env bash
# whisper_dinle.sh — basit örnek
arecord -f S16_LE -r 16000 -c 1 -q /tmp/kayit.wav
whisper-cli -m ~/whisper.cpp/models/ggml-base.bin -f /tmp/kayit.wav -l tr -nt \
  -otxt -of /tmp/cikti
cat /tmp/cikti.txt > /tmp/llama_input.pipe
```

### Model iletişimi

- İstekler `chat.completions` streaming uçuna yapılır; `reasoning_effort: xhigh` ve `enable_thinking` chat template parametreleri gönderilir (llama.cpp server'da düşünme modunu açar).
- Düşünme akışı iki yoldan yakalanır: OpenAI tarzı `reasoning_content` delta'ları ve `<think>…</think>` etiket fallback'i. Düşünme metni soluk sarı, `💭 Düşünüyor...` başlığıyla gösterilir.
- Markdown formatter kod blokları, satır içi kod, kalın yazı, başlıklar ve alıntıları ANSI renklerine çevirir; hepsi stream sırasında (harf harf) işlenir.
- Model adı alanı sabittir (`"agent_model"`); llama.cpp server bu alanı yok sayar ve sunucuda yüklü model kullanılır.

### Proje yapısı

```text
TermiLLM/
├── main.py                  # composition root — nesneleri kurar, başlatır
├── application.py           # AgentApplication: başlangıç akışı + REPL döngüsü
├── config.py                # .env + sabitler (Config dataclass)
├── state.py                 # runtime state (Application/Session/AttachmentState)
├── commands/
│   ├── router.py            # girdiyi komut sınıflarına yönlendirir
│   ├── session_commands.py  # /new /chats /open /rename /delete /clear
│   ├── search_commands.py   # /ara /search /arama
│   └── system_commands.py   # /stats /debug /help
├── chat/
│   ├── service.py           # mesaj akışı + ajan arama döngüsü
│   ├── context.py           # token tahmini, kırpma, mesaj oluşturma
│   ├── attachments.py       # bekleyen metin/görsel ekleri
│   └── mentions.py          # @dosya ve ?"sorgu" ayrıştırma
├── llm/
│   ├── client.py            # OpenAI-compatible stream çağrısı
│   ├── stream.py            # <think>/<web_search> ayrıştırıcı, StreamResult
│   ├── server_info.py       # context keşfi (llamacpp, openrouter, xai, …)
│   ├── cancel.py            # Ctrl+X / SIGINT ile tur iptali
│   └── abort.py             # soket kapatma + llama-server /abort
├── sessions/
│   ├── manager.py           # uygulama seviyesi oturum davranışı
│   └── storage.py           # disk işlemleri (history/metadata/token log)
├── media/
│   ├── audio.py             # whisper.cpp transkripsiyonu + arecord kaydı
│   ├── files.py             # metin dosyası yükleme
│   ├── images.py            # base64 data URI hazırlama
│   └── pipe.py              # named pipe dinleyici
├── search/
│   ├── service.py           # arama koordinasyonu + sonuç biçimlendirme
│   ├── config.py            # search_config.json yükleme/kaydetme
│   └── providers.py         # SearXNG ve Tavily sağlayıcıları
├── ui/
│   ├── terminal.py          # prompt, context bar, yardım, istatistik, renkler
│   ├── markdown.py          # Markdown → ANSI dönüştürücü (streaming)
│   ├── stream_renderer.py   # düşünme/yanıt akışını terminale çizer
│   ├── line_edit.py         # satır editörü (@ yazınca kutu)
│   ├── picker.py            # dosya kutusu (dizin gezme)
│   ├── completer.py         # yol eşleştirme
│   └── keys.py              # ham tuş okuma
├── searxng/settings.yml     # yerel SearXNG örneği için (json formatı etkin)
├── search_config.json       # arama ayarları (çalışırken düzenlenebilir)
├── setup.sh                 # sanal ortam + bağımlılık kurulumu
```

Katmanlar tek yönlü bağımlıdır: `ui` ← `commands/chat` ← `sessions/llm/media` gibi; LLM katmanı oturum dosyalarından, storage ise terminal'den habersizdir. Mimariyi detaylandıran tasarım belgesi ve refactor raporu için `~/Desktop/ai/v7/` altındaki `readme.md` ve `rapor.md` dosyalarına bakabilirsiniz.
