# TermiLLM

**[English](README.en.md) | Türkçe**

Terminalde çalışan, Python ile yazılmış açık uçlu bir LLM sohbet ajanıdır. Yerel veya uzak bir **llama.cpp server** (veya herhangi bir OpenAI-compatible API) ile konuşur; akış (streaming) yanıtlar, modelin **düşünme (reasoning)** çıktısı ve ANSI renkleriyle **Markdown** biçimlendirmesi doğrudan terminale render edilir. Sohbetler diskte oturumlar halinde saklanır, context/token kullanımı üst çubukta canlı bir çubukla izlenir ve context dolunca geçmiş otomatik kırpılır.

Diğer önemli yetenekleri:

- **Tam ekran sohbet sayfası** — Program açılınca siyah zeminli, beyaz yazılı alternatif bir "yeni sayfa" açılır; üstte sabit context göstergesi, altta sabit çok satırlı giriş kutusu durur. Fare tekerleği ile geçmişe kaydırma, fare ile seçip panoya kopyalama desteklenir.
- **Web arama ajanı** — Model gerekirse yanıtında `<web_search>sorgu</web_search>` etiketi yazar; program aramayı çalıştırır (SearXNG veya Tavily), sonuçları modele geri besler ve düz cevap gelene dek döngüyü sürdürür (en fazla 6 tur).
- **Dosya, görsel ve ses ekleri** — Giriş kutusunda `@dosya` yazınca bir kutu açılır; metin, resim (`.png` `.jpg` …) veya ses (`.wav` `.mp3` …) seçilir, aynı satırda yazmaya devam edilir. Ses dosyaları Whisper ile yazıya çevrilir. Canlı mikrofon için named pipe (`whisper_dinle.sh`) durur.
- **Satır içi web arama** — `?"sorgu"` aynı mesajda arama yapar; `/ara` sonucu belleğe alır. Model ayrıca gerekirse kendisi `<web_search>` çağırır.
- **Yanıtı kesme** — Üretim sırasında **Ctrl+X** (veya Ctrl+C) turu keser; program kapanmaz, soket kapanır ki llama-server üretmeye devam etmesin.
- **Oturum yönetimi** — Her sohbet `chats/` altında kendi klasöründe tutulur (geçmiş, başlık, token logu); program açılışta en son sohbeti otomatik yükler.

---

## Kurulum

### Gereksinimler

- **Python 3.10+** (tek pip bağımlılığı `openai`; konfigürasyon için stdlib `tomllib` kullanılır — `python-dotenv` kaldırıldı)
- **Linux** (mikrofon kaydı `arecord`/ALSA ve named pipe kullanır; diğer özellikler platformdan bağımsızdır)
- Çalışan bir **llama.cpp server** (veya OpenAI-compatible bir endpoint)
- Kopyalama/seçim ve koyu gri kutular için 256-renk destekli bir terminal (Kitty, Alacritty, WezTerm, GNOME Terminal, Konsole, iTerm2 …)

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

Sağlayıcı ayarları **TOML konfigürasyon dosyasında** tutulur:
`~/.config/termillm/config.toml` (proje dizininde dosya tutulmaz; gizliler
asla repoya girmez).

Eski `.env` dosyanız varsa **ilk açılışta otomatik içe aktarılıp silinir**
(anahtar değerleri + `p<n>_` sağlayıcı kayıtları, `${VAR}` genişletmeleriyle).
İstemezseniz programı ilk kez çalıştırmadan `.env`'i kendiniz silebilirsiniz;
aynı ayarları Ctrl+O menüsünden girmek de mümkündür.

```toml
active = "local"

[providers.local]
base_url = "http://127.0.0.1:8080/v1"   # OpenAI-compatible endpoint
api_key  = "enc1:…"                      # şifreli; llama.cpp'te placeholder yeter
model    = "Bonsai-2"
```

- `base_url` — OpenAI-compatible chat endpoint'inin tam adresi (ör. `http://127.0.0.1:8080/v1`, `https://api.x.ai/v1`, OpenRouter).
- `api_key` — llama.cpp server'da yok sayılır (`sk-local` placeholder yeterlidir); uzak servislerde gerçek anahtardır ve **şifreli** saklanır (`enc1:` öneki, makineye bağlı gizli ile: `~/.termillm_salt`).
- Aktif kayıt `active =` ile seçilir; sağlayıcı eklemek ve model seçmek için program içinden **Ctrl+O** menüsü önerilir (model listesini `GET /models`'ten çeker).

İsteğe bağlı ortam değişkenleri (kabuk ortamında):

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

## Sohbet sayfası

`python main.py` çalışınca terminal alternatif bir ekrana geçer ve siyah zeminli bir **sohbet sayfası** açılır; çıkışta (q/quit veya Ctrl+D) ana terminal birebir geri yüklenir.

```text
                                                                 %25 ████████────────── 16.384 / 65.536
 ┌──────────────────────────────────────────────────────────────────────────────────────────────┐
 │                                                                                              │
 │      merhaba, bu dosyayı inceleyebilir misin?                                                │
 │                                                                                              │
 └──────────────────────────────────────────────────────────────────────────────────────────────┘
 saat 14:32

Ajan: Tabii, bakıyorum…

…model cevabı buraya akar…

↳ giriş: 263 tok │ çıkış: 41 tok │ toplam: 304 tok │ 15.8 tok/s (server)
saat 14:33

 ┌──────────────────────────────────────────────────────────────────────────────────────────────┐
 │                                                                                              │
 │  Sen: …yazmaya buradan devam edersin…                                                        │
 │                                                                                              │
 └──────────────────────────────────────────────────────────────────────────────────────────────┘
```

### Ekran öğeleri

| Öğe | Davranış |
|---|---|
| **Üst çubuk (sabit)** | En sağda: yüzde + **beyaz** doluluk barı + `harcanan / context size` (her turdan sonra güncellenir) |
| **İçerik alanı** | Mesajlar klasik terminal akışıyla **yukarıdan aşağıya** yazılır; ekran dolunca en eski satır tepeden kayar |
| **Giriş kutusu (sabit, altta)** | Koyu gri zemin, beyaz çizgiler; metin kutunun ortasında, her taraftan boşluklu; içeriğe göre büyür (5–16 satır) |
| **Kullanıcı balonu** | Gönderilen her mesaj çizgisiz koyu gri kutuda, `>` ile başlar; altında `saat HH:MM` damgası |
| **Model cevabı** | Canlı akar. Satır ekrana sığmayınca alt satıra **hemen** geçer; satır sonu beklenmez. Bittiğinde altında token istatistiği (`↳ … tok/s`) ve `saat HH:MM` damgası basılır |
| **Kod blokları / alıntılar** | Markdown formatter, kod bloklarını ve `>` alıntılarını satırı sonuna kadar dolduran **koyu gri zeminle** çizer |
| **Overlay'ler** | `/help`, `/stats`, `/chats` çıktısı kutunun üstünde açılır; **herhangi bir tuşta** kapanır (uzunsa tuş tuş sayfalama) |

### Tuşlar

| Tuş | İş |
|---|---|
| `Enter` | Mesajı gönder |
| `Shift+Enter` / `Ctrl+J` | Giriş kutusunda yeni satır |
| `↑ ↓ ← →` `Home` `End` | İmleç gezinme (çok satırlı) |
| `Ctrl+U` `Ctrl+K` `Ctrl+W` | Satır başına kadar sil / satır sonuna kadar sil / kelime sil |
| `@` yaz | Dosya seçme kutusunu aç (aynı satırda yazmaya devam) |
| `Tab` | Dosya kutusunu aç / kutuda gezin |
| **Fare tekerleği ↑↓** (veya `↑ ↓`/`PgUp PgDn`, boş girdi kutusunda) | Geçmişe kaydırma (sağ üstte `↑N` göstergesi); en alta dönünce canlı akış sürer |
| **Fare sol tuş + sürükleme** | Terminalin **kendi native seçimi** — normal metin gibi seç, kopyala, yapıştır |
| `Ctrl+O` | **Providers menüsü** (İngilizce): Select Provider (`/` REGEX arama, `d` silme) / Enter API / **Quick Add Provider** — model listesi `GET /models`'ten çekilir; kayıtlar `~/.config/termillm/config.toml`'a yazılır, seçim anında etkinleşir. Sonrasında effort sorulur. Quick Add: 15 hazır sağlayıcı (OpenRouter, Cerebras, Groq, Together, Mistral, DeepSeek, xAI, Fireworks, OpenAI, Gemini, Claude, OpenCode Zen/Go, Ollama, LM Studio) — yalnızca API key girilir (model seçimi Select Provider'dan). API key'ler **şifreli** saklanır (`enc1:`, makineye bağlı gizli ile; `~/.termillm_salt`) |
| `Ctrl+P` | **Effort seçimi.** Açılış `auto`: explicit effort gitmez. Seçenekler `auto · none · minimal · low · medium · high · xhigh · max`. `auto` ile `none` farklıdır. Seçim (auto dahil) sağlayıcı değişince korunur |
| `q` / `quit` | Çıkış |

> **Seçim notu:** Uygulama fare olaylarını yakalamaz (mouse tracking modu açılmaz); metin seçimi ve kopyalama tamamen terminalin native davranışıdır — hangi tuş kombinasyonunu kullanıyorsan normal terminal metninde nasıl çalışıyorsa burada da öyle çalışır.

> **Saat damgası:** Açılışta arka planda internete bakılır — varsa IP'ye göre **bölgesel saat** (worldtimeapi, olmazsa bir sunucunun HTTP `Date` başlığı) çekilir ve bilgisayar saatiyle farkı önbelleğe alınır (10 dk'da bir tazelenir). İnternet yoksa bilgisayar saati kullanılır. Mesaj damgaları ağ beklemeden basılır.

---

## Reasoning Effort (Ctrl+P)

Varsayılan **`auto`**. TermiLLM explicit reasoning effort **göndermez**;
provider/model kendi varsayılanını kullanır. İç temsil `None`'dır.
İstek gövdesine `reasoning_effort`, `reasoning.effort` veya
`output_config.effort` konmaz. `reasoning_effort="auto"` diye bir API
değeri de gönderilmez. `auto` seçildiği için `enable_thinking=false`
eklenmez. İpucu yalnız `Efor: auto` der; sağlayıcının varsayılan
seviyesi tahmin edilmez.

`none` bundan farklıdır: reasoning'i **explicit kapatma** isteğidir ve
yalnız provider/model destekliyorsa uygulanır (ör. llama.cpp'de
`enable_thinking=false`).

`minimal` / `low` / `medium` / `high` / `xhigh` / `max` explicit
canonical seviyelerdir. Adapter (`llm/reasoning.py`) bunları ilgili API
formatına çevirir. Ctrl+P menüsü:

`auto · none · minimal · low · medium · high · xhigh · max`

Kullanıcı tekrar `auto` seçebilir. Seçim, `auto` dahil, sağlayıcı
değişince korunur; adapter yalnız request biçimini değiştirir.
Web arama döngüsü ve reasoning kaynaklı 400 retry bu tercihi değiştirmez
(retry effortsüz gider, state `high` olarak kalır).

İpucu: `Efor: high`. Seviye indirildiyse `Efor: xhigh → high`.
Parametre reddedildiyse `Efor: high → unsupported`.

| Sağlayıcı (model destekliyorsa) | Request alanı |
|---|---|
| llama.cpp / yerel sunucular | `chat_template_kwargs: {reasoning_effort, enable_thinking}` (`none` → `enable_thinking=false`). `reasoning_format` gönderilmez; sunucu `reasoning_content` üretirse okunur |
| OpenAI (o-serisi, gpt-5+) | `reasoning_effort: <seviye>` (üst seviye) |
| Gemini (OpenAI-compatible) | `reasoning_effort: <seviye>` — Gemini bunu `thinking_level`/`thinking_budget`'a çevirir |
| Groq | `reasoning_effort`. Qwen için ayrıca `reasoning_format=parsed` (çıktı biçimi; effort'tan ayrı). GPT-OSS bu biçim alanını kabul etmez |
| xAI (Grok 4+) | `reasoning_effort: <seviye>` |
| DeepSeek (reasoner) | `reasoning_effort: <seviye>` |
| OpenRouter | `reasoning: {"effort": <seviye>}` |
| Claude (native Messages API) | `output_config: {"effort": <seviye>}` — native transport; OpenAI uyumluluk yolu bu alanı yok sayar |
| Fireworks (Qwen, GLM, DeepSeek, MiniMax) | `reasoning_effort`: `none` … `max`. Düşünme `reasoning_content` alanında okunur |
| Cerebras | Modele göre `none/low/medium/high` (GPT-OSS: `low/medium/high`). Qwen, GPT-OSS ve Kimi için `reasoning_format=parsed` |
| Mistral Small / Medium | Yalnız `none` ve `high`. `medium` aşağı iner (`none`). Magistral'a effort parametresi gitmez |
| Together | GPT-OSS: `low/medium/high`. DeepSeek V4 kullanıcının değerini alır (sunucu eşler). Diğer model adları atlanır |
| OpenCode Zen/Go ve bilinmeyen uç | **omit** — istenirse `config.toml`'da `reasoning_api = "llamacpp\|openai\|openrouter\|anthropic\|none"` |

**Normalleştirme kuralları:** exact değer destekleniyorsa exact gönderilir; desteklenmeyen değer resmi kümedeki en yakın **aşağı** seviyeye iner (`xhigh`→`high`); kullanıcı istemeden seviye **yükseltilmez** (eksikse omit); aynı request'te birden fazla effort formatı bulunmaz.

**400 güvenlik ağı:** Sağlayıcı reasoning alanını reddederse (`unknown field` vb.) istek effortsüz **bir kez** yeniden denenir, bu `sağlayıcı+model` kombinasyonu process boyunca "unsupported" önbelleğe alınır ve debug.log'a yazılır. Kimlik/rate-limit gibi ilgisiz hatalarda retry yapılmaz.

## Düşünme ve cevap

Ham akış önce ortak olaylara indirgenir (`llm/normalize.py`), sonra ekrana gelir. Sıra: `reasoning_details`, `reasoning`, `reasoning_content`, Ollama `thinking`, Claude `thinking_delta`, Gemini `thought_summary`, Mistral `ThinkChunk`. Aynı parçada alias'lar ikinci kez yazılmaz. `signature_delta` ve `thought_signature` ekrana basılmaz.

Structured alan yoksa ve cevap henüz görünür metin üretmeden bir açılış etiketiyle başlıyorsa yedek ayrıştırıcı çalışır (`llm/reasoning_text.py`):

- `<think>…</think>` ve `<thought>…</thought>` (Gemini'nin OpenAI uyumlu ucunda görülen biçim)
- Ministral: `[THINK]…[/THINK]`
- Cohere: `<|START_THINKING|>` … `<|END_THINKING|>` / `<|START_RESPONSE|>`

`<analysis>`, `<reasoning>`, `<thinking>` ve cümlenin ortasındaki etiketler olduğu gibi kalır. Yalnız kapanış etiketi (`</think>`) önceki metni düşünmeye çevirmez; bu yalnız doğrulanmış forced-open profilde olur. Ham GPT-OSS Harmony (`analysis` / `final`) kendiliğinden açılmaz; Groq, Cerebras, Ollama, LM Studio ve llama.cpp bu biçimi kendileri ayırır.

`<web_search>` yalnız nihai cevapta aranır. Düşünme metnindeki etiket arama turu başlatmaz.

Ekranda düşünme `💭 Düşünüyor...` altındadır; sağlayıcı özet verdiğinde başlık `💭 Düşünme özeti...` olur. Metin soluk sarı (turuncu) akar. Kalın, italik ve satır içi kod bu rengin üstüne biner; stil kapanınca renk terminal varsayılanına değil yeniden turuncuya döner. Sayfa her satırı beyaz önekle boyadığı için renk, parçanın başında değil satırın kendi ANSI taban stilinde durur (`ui/markdown.py` `base_style`).

Oturum geçmişine yazılan assistant metni nihai cevaptır; `<think>` / `<thought>` içeriğe karışmaz. İmza, OpenRouter `reasoning_details`, DeepSeek `reasoning_content` ve Mistral parça listesi `provider_state` olarak saklanır ve sonraki istekte yalnız o sağlayıcının beklediği alan geri konur.

---

## Kullanım ve Komutlar

Program bir REPL'dir: mesajı üstteki giriş kutusuna yazarsınız, yanıt `Ajan:` başlığıyla akarken render edilir ve altında token istatistiği gösterilir (`↳ giriş: … │ çıkış: … │ toplam: … │ 24.3 tok/s (server)`).

### Oturum komutları

| Komut | Açıklama |
|---|---|
| `/new` | Yeni sohbet oluştur |
| `/chats` | Sohbetleri listele (başlık, session ID, son mesajın ilk 80 karakteri) |
| `/open N` | Listeden N numaralı sohbeti aç |
| `/rename <yeni başlık>` | Aktif sohbetin başlığını değiştir |
| `/delete N` | N numaralı sohbeti sil (aktif sohbet silinirse en yenisi açılır) |
| `/clear` | Aktif sohbetin geçmişini ve bekleyen ekleri sıfırla (sayfa içeriğini de temizler) |
| `/stats` | Mesaj sayısı, context token'ı, toplam giriş/çıkış token'ı |
| `/debug` | Debug modunu aç/kapat (ham stream parçaları `debug.log`'a yazılır) |
| `/help` | Komut listesi (overlay; tuşla kapanır) |
| `Ctrl+X` | Yanıtı kes (program açık kalır; üretim sırasında Ctrl+C de aynı) |
| `q` / `quit` | Çıkış |

### Medya — `@` (satır içi)

`/read`, `/dosya`, `/ses` ve `/resim` yoktur. Giriş kutusunda `@` yazınca dosya kutusu açılır; seçimden sonra **aynı satırda yazmaya devam edilir**.

```text
@readme.md şunu özetle
@foto.png bu resmi açıkla
@konusma.wav bunu yazıya dök
@main.py @config.py karşılaştır
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

**Ek akışı:** Seçilen içerik bellekte bekler (`📎 N ek bellekte bekliyor`) ve mesajla birlikte gider. Boş Enter, eki "ekteki içeriği incele" talebiyle gönderir. Görsel yalnızca modele giderken base64 taşınır; geçmişte `[Resim: dosyaadı]` kalır. `@dosya` / `?arama` işlemleri sayfayı geçici askıya alıp düz terminalde yürütür; sonuçları sohbet balonlarına karışmaz.

### Arama

| Komut | Açıklama |
|---|---|
| `?"sorgu"` | Satır içinde web ara; kalan metin mesajdır (`?"python 3.14" bunu özetle`) |
| `/ara <sorgu>` veya `/search <sorgu>` | Web ara, sonucu belleğe al (sonraki mesajla gider) |
| `/arama` | Arama ayar menüsü: SearXNG / Tavily, dil, sonuç sayısı, bağlantı testi (sayfa askıya alınıp düz terminalde çalışır) |
| *(otomatik)* | Model, güncel bilgi gerektiren sorularda kendisi `<web_search>` çağrısı yapar |

**Ajan döngüsü:** Model yanıtı içinde `<web_search>sorgu</web_search>` görüldüğünde stream o noktada durdurulur, sorgu çalıştırılır, sonuçlar `"--- Web Arama Sonuçları ---"` bloğu halinde modele geri verilir ve model yanıtı yeniden akıtılır. Model düz cevap verene veya 6 tur limitine (`MAX_SEARCH_ROUNDS`) ulaşana dek devam eder. Arama sonuçlarına dayanırken kaynak URL'ler modele istenir.

---

## Ayrıntılar

### Context yönetimi

- Açılışta context boyutu `base_url` üzerinden sağlayıcıdan okunur: llama.cpp (`/props` içindeki `n_ctx`), OpenRouter / OrcaRouter / xAI (`context_length`), Anthropic (`max_input_tokens`). Resmi OpenAI `/v1/models` context vermez; OpenRouter kataloğu yedek kaynaktır. Hepsi başarısızsa `CONTEXT_FALLBACK` (varsayılan 4096) kullanılır. Keşif sessizdir; sonuç yalnızca üst çubukta görünür.
- Kullanılabilir bütçe `n_ctx × 0.85` (güvenlik payı) olarak hesaplanır; üst çubukta yüzde + beyaz bar + `harcanan / toplam` gösterilir.
- Bütçe aşılırsa geçmiş **user/assistant çiftleri halinde** (en eskiden) kırpılır; konuşma sıralaması bozulmaz.
- Token istatistikleri server gerçek usage değerlerini kullanır; server bildirmezse `~` işaretiyle yaklaşık değer (karakter/4) gösterilir.

### Sohbet sayfası teknisi

- Sayfa, terminalin **alternate screen buffer'ında** çizilir (`?1049h/l`); ana ekran korunur, imleç DECSC/DECRC ile saklanır/geri yüklenir.
- Tüm program çıktısı `sys.stdout` sayfaya yönlendirilmiş bir yazıcıdan akar: herhangi bir `print()` otomatik olarak sayfaya düşer; sayfanın kendi çizimleri ise gerçek stdout üzerinden yapılır (iç ANSI dizileri içerik sanılmaz).
- Terminal `cbreak` moduna alınır; ICRNL kapatılarak `Enter` CR olarak okunur (gönder), `Ctrl+J` LF kalır (yeni satır). OPOST ve ISIG açık kalır: `\n` çıktısı bozulmaz, Ctrl+C/SIGINT çalışır.
- Mouse tracking **hiç açılır** (uygulama fare olaylarını yakalamaz): metin seçimi terminalin native davranışıdır. Tekerlek için `?1007h` (alternate scroll) açılır — alt ekranda tekerlek `↑`/`↓` ok tuşlarına çevrilir ve sohbet kaydırmasına bağlanır.
- Geçmiş tamponu 5000 satır tutar; fare ile geçmişe bakarken canlı akış görünümü kaydırmaz.
- Model satır sonu göndermeden uzun yazarsa, ekran genişliğini aşan kısım o anda alt satıra alınır. Taşan metin tamponda birikip satır sonunda toplu görünmez.

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
- `LLAMA_PIPE` (varsayılan `/tmp/llama_input.pipe`) üzerindeki bir named pipe dinlenir: harici bir betik pipe'a metin yazarsa (ör. kendi Whisper dinleme betiğiniz) metin giriş kutusuna doldurulur — Enter'a basıp gönderirsiniz. Örnek harici betik:

```bash
#!/usr/bin/env bash
# whisper_dinle.sh — basit örnek
arecord -f S16_LE -r 16000 -c 1 -q /tmp/kayit.wav
whisper-cli -m ~/whisper.cpp/models/ggml-base.bin -f /tmp/kayit.wav -l tr -nt \
  -otxt -of /tmp/cikti
cat /tmp/cikti.txt > /tmp/llama_input.pipe
```

### Model iletişimi

- İstekler `chat.completions` streaming ucuna gider. Effort alanı yalnız Ctrl+P ile bir seviye seçildiyse ve model onu destekliyorsa eklenir. Claude `api.anthropic.com` için native Messages API kullanılır (`output_config.effort`).
- Düşünme ve nihai cevap ayrı kanallardadır (yukarıdaki "Düşünme ve cevap"). Düşünme metni turuncu taban renkte, Markdown stilleri bu rengin üstünde akar.
- Markdown formatter kod blokları (koyu gri zemin), satır içi kod (turkuaz), kalın yazı, italik (reasoning kanalında), başlıklar ve alıntıları ANSI'ye çevirir; hepsi stream sırasında (harf harf) işlenir. Reasoning kanalında geçici stil kapanınca taban turuncu geri gelir.
- Model adı alanı sabittir (`"agent_model"`); llama.cpp server bu alanı yok sayar ve sunucuda yüklü model kullanılır.

### Mesaj saatleri

- `ui/clock.py` açılışta arka planda saat kaynağını keşfeder: **internet varsa** önce `worldtimeapi.org/api/ip` (IP'ye göre bölgesel saat), olmazsa bir sunucunun HTTP `Date` başlığı (GMT); **internet yoksa** bilgisayar saati.
- Bulunan fark (internet saati − bilgisayar saati) önbelleğe alınır ve 10 dakikada bir tazelenir; damgalar (`saat HH:MM`) ağ beklemeden basılır.

### Proje yapısı

```text
TermiLLM/
├── main.py                  # composition root — nesneleri kurar, başlatır
├── application.py           # AgentApplication: başlangıç akışı + REPL döngüsü
├── config.py                # TOML konfig (~/.config/termillm/) + key şifreleme
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
│   ├── client.py            # stream çağrısı, effort ve reasoning normalizasyonu
│   ├── reasoning.py         # Ctrl+P effort → sağlayıcı alanı
│   ├── normalize.py         # structured delta → reasoning/content
│   ├── reasoning_text.py    # <think>/<thought> ve diğer inline yedekler
│   ├── anthropic_transport.py  # Claude native Messages SSE
│   ├── stream.py            # içerikte <web_search>, StreamResult
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
│   ├── page.py              # tam ekran sohbet sayfası (siyah zemin, üst çubuk,
│   │                        #   giriş kutusu, balonlar, overlay, scroll)
│   ├── terminal.py          # renk paleti, show_* sunumları, üst çubuk köprüsü
│   ├── clock.py             # mesaj saatleri (internet → bölgesel saat keşfi)
│   ├── markdown.py          # Markdown → ANSI; reasoning için turuncu taban stil
│   ├── stream_renderer.py   # düşünme/yanıt akışını çizer + saat damgası
│   ├── keys.py              # ham tuş okuma (Shift+Enter, ok tuşları; fare yakalanmaz)
│   ├── provider_menu.py     # Ctrl+O provider/model menüsü (Select Provider / Enter API)
│   ├── line_edit.py         # girişi sayfa kutusuna veya düz satıra yönlendirir
│   ├── picker.py            # dosya kutusu (dizin gezme, sayfada alta demirli)
│   └── completer.py         # yol eşleştirme
├── tests/                   # birim testler (unittest)
├── searxng/settings.yml     # yerel SearXNG örneği için (json formatı etkin)
├── search_config.json       # arama ayarları (çalışırken düzenlenebilir)
└── setup.sh                 # sanal ortam + bağımlılık kurulumu
```

Katmanlar tek yönlü bağımlıdır: `ui` ← `commands/chat` ← `sessions/llm/media` gibi; LLM katmanı oturum dosyalarından, storage ise terminal'den habersizdir. Mimariyi detaylandıran tasarım belgesi ve refactor raporu için `~/Desktop/ai/v7/` altındaki `readme.md` ve `rapor.md` dosyalarına bakabilirsiniz.

---

## Testler

```bash
python -m unittest discover -s tests   # veya: python -m pytest tests/
```

Testler `chat/mentions`, `ui/completer`, `ui/picker`, `llm/cancel`, `llm/server_info`, `llm/abort`, effort zinciri (`test_ctrlp_chain`, `test_reasoning`), reasoning akışı (`test_reasoning_stream`), reasoning rengini (`test_reasoning_color`) ve canlı satır sarmayı (`test_page_wrap`) kapsar; ağ ve tty gerektirmez.
