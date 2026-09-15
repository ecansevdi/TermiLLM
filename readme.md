# Görev: `main.py` Kod Tabanını Modüler Bir Mimariye Refactor Et

Elimde yaklaşık 1243 satırlık tek dosyadan oluşan bir Python uygulaması var: `main.py`.

Bu uygulama:

- OpenAI-compatible API üzerinden yerel/uzak LLM ile konuşuyor.
- Streaming yanıt destekliyor.
- Modelin thinking/reasoning çıktısını işliyor.
- Markdown çıktısını terminal ANSI biçimine dönüştürüyor.
- Sohbet oturumlarını diskte saklıyor.
- Context/token yönetimi yapıyor.
- Whisper.cpp ile ses transkripsiyonu yapıyor.
- Mikrofon kaydı yapabiliyor.
- Text dosyası yükleyebiliyor.
- Vision modeller için görsel yükleyebiliyor.
- Named pipe üzerinden harici Whisper çıktısı alabiliyor.
- Terminal üzerinden `/new`, `/open`, `/ses`, `/read`, `/resim` vb. komutları destekliyor.

Kod şu anda işlevsel durumda.

## Temel hedef

Kodu **davranışını değiştirmeden**, daha modüler, sürdürülebilir ve genişletilebilir bir mimariye dönüştür.

Bu görev bir yeniden yazım değildir.

Mevcut çalışan davranışı mümkün olduğunca koru ve kodu sorumluluklarına göre parçala.

Özellikle:

- Kullanıcı davranışını değiştirme.
- Mevcut komutları kaldırma veya yeniden adlandırma.
- Mevcut session dosya formatlarını gereksiz yere değiştirme.
- Yeni framework ekleme.
- Gereksiz abstraction oluşturma.
- Projeyi aşırı karmaşık bir enterprise mimariye dönüştürme.

Amaç basit ve anlaşılır bir modüler Python uygulaması elde etmektir.

---

# 1. Önce mevcut kodu tamamen incele

Refactor işlemine başlamadan önce `main.py` dosyasını **baştan sona oku**.

Özellikle aşağıdaki sistemlerin birbirleriyle nasıl bağlantılı olduğunu belirle:

- configuration/environment variables
- OpenAI client
- server context discovery
- session sistemi
- history persistence
- token logging
- context trimming
- Whisper
- microphone recording
- file loading
- image loading
- named pipe
- readline integration
- Markdown formatter
- thinking stream parser
- streaming LLM response
- CLI commands
- attachment state
- main REPL loop

Herhangi bir kodu taşımadan önce bağımlılıklarını anlamaya çalış.

---

# 2. Mevcut tasarımdaki ana sorun

Kodun temel problemi tek tek fonksiyonların varlığı değil.

Asıl sorun:

1. Çok fazla runtime state'in global değişkenlerle tutulması.
2. `main()` fonksiyonunun çok fazla sorumluluk üstlenmesi.
3. LLM communication, terminal rendering ve persistence katmanlarının birbirine bağlı olması.
4. Session fonksiyonlarının global aktif session durumunu değiştirmesi.
5. CLI command routing'in doğrudan `main()` içine gömülü olması.
6. Attachment yönetiminin ana döngünün içine dağılmış olması.

Örneğin mevcut kodda aşağıdakiler global durum olarak tutuluyor:

- `CURRENT_SESSION`
- `CURRENT_CHAT_DIR`
- `HISTORY_FILE`
- `TOKEN_FILE`
- `METADATA_FILE`
- `MAX_CONTEXT_TOKENS`
- `DEBUG`

Bunların mümkün olduğunca kontrollü state nesneleri veya ilgili servisler altında tutulmasını istiyorum.

---

# 3. Hedef proje yapısı

Başlangıç hedefi olarak aşağıdaki mimariyi kullan:

```text
project/
│
├── main.py
├── config.py
├── state.py
├── application.py
│
├── commands/
│   ├── __init__.py
│   ├── router.py
│   ├── session_commands.py
│   ├── media_commands.py
│   └── system_commands.py
│
├── chat/
│   ├── __init__.py
│   ├── service.py
│   ├── context.py
│   └── attachments.py
│
├── llm/
│   ├── __init__.py
│   ├── client.py
│   ├── stream.py
│   └── server_info.py
│
├── sessions/
│   ├── __init__.py
│   ├── manager.py
│   └── storage.py
│
├── media/
│   ├── __init__.py
│   ├── audio.py
│   ├── files.py
│   ├── images.py
│   └── pipe.py
│
└── ui/
    ├── __init__.py
    ├── terminal.py
    ├── markdown.py
    └── stream_renderer.py
```

Bu yapı mutlak değildir.

Eğer bazı modüllerin gereksiz yere küçük kalacağını düşünüyorsan mantıklı birleştirmeler yapabilirsin.

Ancak modüllerin sorumluluk sınırlarını koru.

---

# 4. `config.py`

`.env` ve sabit configuration değerlerini burada topla.

Örneğin:

```text
server:
    server_base
    api_base_url
    api_key
    model

whisper:
    binary
    model
    language

application:
    chat_directory
    pipe_path
    context_fallback
    context_safety_ratio
    system_prompt
```

Şu ayrımı mutlaka koru:

```text
configuration = uygulama çalışırken normalde değişmeyen değerler
runtime state = program çalışırken değişen değerler
```

Örneğin:

```text
WHISPER_MODEL
SERVER_BASE
SYSTEM_PROMPT
```

configuration'dır.

Buna karşılık:

```text
CURRENT_SESSION
DEBUG
MAX_CONTEXT_TOKENS
pending_text_attachments
```

runtime state'tir.

OpenAI client nesnesini configuration dosyasına koyma.

---

# 5. `state.py`

Runtime durumunu global değişkenlerden çıkarmaya çalış.

Önerilen kavramsal yapı:

```text
ApplicationState
│
├── active_session
├── actual_context_tokens
├── max_context_tokens
├── debug_enabled
└── attachments
```

Session state:

```text
SessionState
│
├── id
├── title
├── directory
├── history_file
├── metadata_file
├── token_file
└── history
```

Attachment state:

```text
AttachmentState
│
├── text_attachments
├── vision_message
└── vision_path
```

Her şeyi tek bir devasa state nesnesine doldurma.

State sadece gerçekten runtime state olan verileri içersin.

---

# 6. Session sistemini iki katmana ayır

Session sistemi şu şekilde tasarlansın:

```text
SessionManager
      │
      v
SessionStorage
```

## `SessionStorage`

Sadece persistence/disk işlemlerinden sorumlu olsun.

Örneğin:

```text
create(...)
delete(...)
list(...)
load_history(...)
save_history(...)
load_metadata(...)
save_metadata(...)
append_token_usage(...)
```

Bu katman:

- Terminal UI bilmemeli.
- LLM bilmemeli.
- Aktif session kavramını mümkün olduğunca bilmemeli.

## `SessionManager`

Uygulama seviyesindeki session davranışını yönetsin:

```text
new_session()
open_session()
delete_session()
rename_session()
clear_session()
current_session()
list_sessions()
```

Önemli:

`load_session()` benzeri işlemler global değişkenleri mutate etmek yerine bir `SessionState` üretmeli veya kontrollü şekilde uygulama state'ini güncellemelidir.

---

# 7. Mevcut `/chats` davranışına özellikle dikkat et

Mevcut tasarımda session listesini göstermek için session'lar tek tek yükleniyor.

Ancak `load_session()` aktif session globalini değiştirdiği için `/chats` komutunun sadece listeleme yaparken aktif session durumunu değiştirme riski var.

Yeni tasarımda:

```text
SessionStorage.get_metadata(session_id)
```

gibi salt-okuma operasyonları aktif session'ı değiştirmemeli.

Genel prensip:

> Bir şeyi listelemek veya okumak uygulamanın aktif durumunu değiştirmemeli.

---

# 8. Command Router oluştur

`main()` içindeki büyük:

```text
if /new
if /chats
if /open
if /rename
if /delete
if /clear
if /debug
if /help
if /stats
if /ses
elif /read
elif /resim
```

yapısını ana döngüden çıkar.

Hedef:

```text
CommandRouter
│
├── session commands
│   ├── new
│   ├── chats
│   ├── open
│   ├── rename
│   ├── delete
│   └── clear
│
├── media commands
│   ├── ses
│   ├── read
│   ├── dosya
│   └── resim
│
└── system commands
    ├── stats
    ├── debug
    └── help
```

Genel akış:

```text
user input
    │
    v
CommandRouter
    │
    ├── komutsa ────────> ilgili handler
    │
    └── komut değilse ──> ChatService
```

Router iş mantığını kendi içinde gerçekleştirmemeli.

İlgili service/manager'lara yönlendirmeli.

---

# 9. `application.py`

Ana uygulama koordinasyonu burada olsun.

Önerilen yapı:

```text
AgentApplication
│
├── config
├── state
├── terminal
├── command_router
├── chat_service
├── session_manager
├── attachment_manager
└── pipe_listener
```

Programın genel akışı yaklaşık şöyle olmalı:

```text
initialize
    ↓
aktif session'ı yükle
    ↓
pipe listener başlat
    ↓
server bilgisini al
    ↓
terminal başlangıç bilgisini göster
    ↓
┌──────────── REPL ──────────────┐
│                               │
│ input oku                     │
│       ↓                       │
│ command mı?                   │
│   ├─ evet → router            │
│   └─ hayır → chat_service     │
│                               │
└───────────────────────────────┘
```

`AgentApplication` işi kendisi yapmaktan çok servisleri koordine etmeli.

---

# 10. `main.py` çok küçük hale gelsin

Refactor sonunda `main.py` yalnızca **composition root / entry point** olarak kullanılmalı.

Kavramsal olarak görevi:

```text
configuration yükle

gerekli nesneleri oluştur:
    storage
    session manager
    llm client
    media services
    terminal
    command router
    chat service
    application

application.run()
```

olmalı.

Business logic veya CLI command implementasyonları `main.py` içinde kalmamalı.

---

# 11. Chat katmanı

Normal mesaj gönderim akışını `main()` fonksiyonundan çıkar.

Bir `ChatService` oluştur.

Kavramsal bağımlılıkları:

```text
ChatService
     │
     ├── AttachmentManager
     ├── ContextManager
     ├── LLMClient
     ├── SessionManager
     └── StreamRenderer
```

`send_message()` benzeri bir operasyonun akışı yaklaşık şöyle olmalı:

```text
attachment'ları hazırla
        ↓
user message oluştur
        ↓
context budget kontrol et
        ↓
messages oluştur
        ↓
LLM'e gönder
        ↓
assistant cevabını al
        ↓
history güncelle
        ↓
session'ı kaydet
        ↓
attachment buffer'ı temizle
```

`application.py` bunun iç detaylarını bilmemeli.

---

# 12. Context yönetimi

Aşağıdaki mevcut fonksiyonlar doğal olarak aynı modülde toplanabilir:

```text
estimate_tokens()
estimate_messages_tokens()
trim_history()
build_messages()
```

Bunları:

```text
ContextManager
│
├── estimate_text()
├── estimate_messages()
├── trim()
├── build_messages()
└── calculate_budget()
```

gibi bir yapı altında düzenleyebilirsin.

Context size global state üzerinden rastgele erişilen bir değer olmamalı.

`MAX_CONTEXT_TOKENS` uygulama/runtime state veya ilgili context configuration üzerinden erişilmeli.

Mevcut güvenlik payı davranışını koru.

---

# 13. LLM katmanını persistence'tan ayır

Mevcut `do_stream_and_respond()` fonksiyonu çok fazla sorumluluk taşıyor.

Şu anda kabaca:

```text
API çağrısı
→ stream okuma
→ thinking parse
→ terminal output
→ token hesaplama
→ token logging
→ history mutate
→ history save
```

işlerini aynı yerde yapıyor.

Bunu ayır.

Önerilen mimari:

```text
LLMClient
     │
     └── stream(messages)
              │
              v
         StreamProcessor
              │
       ┌──────┴──────┐
       │             │
    thinking       content
       │             │
       └──────┬──────┘
              v
        StreamRenderer
```

İşlem sonunda mümkünse buna benzer bir sonuç nesnesi üret:

```text
StreamResult

assistant_text
thinking_text
input_tokens
output_tokens
elapsed
usage_estimated
```

Bu sonuç daha sonra `ChatService` tarafından history/persistence tarafına aktarılmalı.

Çok önemli prensip:

> `LLMClient` `history.json`, session klasörleri veya token log dosyalarının varlığını bilmemeli.

---

# 14. Thinking parser ile terminal rendering'i ayır

Mevcut `ThinkingStreamParser` iki farklı işi yapıyor:

1. `<think>` / `</think>` parsing
2. doğrudan terminale `print()` yapmak

Bunları mümkün olduğunca ayır:

```text
StreamParser
     +
StreamRenderer
```

Parser aşağıdaki olayları anlamalı:

```text
thinking başladı
thinking chunk geldi
thinking bitti
response chunk geldi
```

Renderer ise:

```text
💭 Düşünüyor...
Ajan:
ANSI renkleri
terminal output
```

ile ilgilenmeli.

Böylece gelecekte terminal UI yerine başka bir UI kullanılması LLM parsing kodunu değiştirmeyi gerektirmez.

---

# 15. `MarkdownFormatter`

Bu sınıf zaten tek ve anlaşılır bir sorumluluğa sahip.

Büyük ölçüde mevcut davranışını koruyarak:

```text
ui/markdown.py
```

içine taşı.

Görevi:

```text
Markdown streaming text
        ↓
MarkdownFormatter
        ↓
ANSI terminal text
```

olsun.

Markdown formatter'ın chat/session/LLM persistence mantığına bağımlılığı olmamalı.

---

# 16. Media katmanı

## `media/audio.py`

Whisper ve mikrofon:

```text
AudioService
│
├── transcribe_file()
└── record_and_transcribe()
```

Mevcut:

```text
whisper_transcribe()
record_and_transcribe()
```

davranışlarını burada koru.

## `media/files.py`

Text dosyası yükleme.

Örneğin:

```text
TextFileLoader
└── load()
```

## `media/images.py`

Görsel işlemleri:

```text
ImageLoader
│
├── validate()
├── determine_mime()
└── prepare_for_model()
```

Base64/data URI davranışını koru.

## `media/pipe.py`

Named pipe/readline integration ayrı tutulmalı:

```text
PipeInput
│
├── start()
├── watch()
└── consume_prefill()
```

Thread lifecycle ve prefill synchronization burada bulunabilir.

---

# 17. Attachment yönetimi

Mevcut:

```text
pending_text_attachments
pending_vision_msg
pending_vision_path
```

durumunu ana döngüden çıkar.

Bir:

```text
AttachmentManager
```

veya:

```text
AttachmentState
```

üzerinden yönet.

Örneğin kavramsal işlemler:

```text
add_text(...)
add_audio_transcription(...)
set_image(...)
has_pending()
build_message(...)
clear()
```

Ancak gereksiz abstraction oluşturma.

Sadece mevcut karmaşıklığı gerçekten azaltıyorsa kullan.

---

# 18. UI katmanı

Terminal çıktıları mümkün olduğunca UI katmanında toplansın.

Örneğin:

```text
TerminalUI
│
├── prompt_user()
├── show_startup()
├── show_error()
├── show_success()
├── show_context_bar()
├── show_token_stats()
├── show_help()
└── show_session_list()
```

Ancak her `print()` çağrısını zorla bir metoda dönüştürerek gereksiz boilerplate yaratma.

Amaç business logic içerisindeki terminal bağımlılığını azaltmak.

---

# 19. Hedef bağımlılık yönü

Genel mimari şu yönde ilerlesin:

```text
                         main.py
                            │
                            v
                    AgentApplication
                            │
          ┌─────────────────┼─────────────────┐
          │                 │                 │
          v                 v                 v
    CommandRouter       ChatService       TerminalUI
          │                 │
    ┌─────┼──────┐          │
    │     │      │          ├──────── ContextManager
    │     │      │          │
    v     v      v          ├──────── AttachmentManager
 Session Media System       │
Commands Commands Commands ├──────── LLMClient
    │        │              │             │
    │        │              │             v
    │        │              │       StreamProcessor
    │        │              │             │
    │        │              │             v
    │        │              │       StreamRenderer
    │        │              │
    v        v              v
Session   Audio/File     SessionManager
Manager   Image/Pipe          │
    │                         │
    └──────────────┬──────────┘
                   v
             SessionStorage
                   │
                   v
            chats/<session>/
```

Ana prensip:

```text
UI
↓
Application / Commands
↓
Services
↓
Infrastructure
```

Alt katmanlar mümkün olduğunca üst katmanları bilmemeli.

Örneğin aşağıdaki bağımlılıklar oluşmasın:

```text
SessionStorage → TerminalUI
LLMClient → SessionManager
MarkdownFormatter → ChatService
```

---

# 20. Mevcut davranışları koru

Refactor sonrasında aşağıdakilerin çalışmaya devam ettiğinden emin ol:

```text
/new
/chats
/open N
/rename
/delete N
/clear
/stats
/debug
/help

/ses
/ses <dosya>
/read <dosya>
/dosya <dosya>
/resim <dosya>

q
quit
```

Ayrıca:

- mevcut sohbetlerin yüklenmesi,
- history.json yazılması,
- metadata.json kullanılması,
- token loglarının tutulması,
- context trimming,
- server context size discovery,
- OpenAI-compatible streaming API,
- reasoning/thinking stream,
- `<think>` parsing fallback,
- Markdown terminal formatting,
- Whisper transcription,
- microphone recording,
- named pipe,
- readline prefill,
- text attachments,
- multimodal image gönderimi

çalışmaya devam etmeli.

---

# 21. Hata davranışlarını gereksiz yere değiştirme

Mevcut kullanıcıya gösterilen hataları ve fallback mekanizmalarını korumaya çalış.

Özellikle:

- Whisper binary bulunamaması
- Whisper model bulunamaması
- `arecord` bulunamaması
- dosya bulunamaması
- resim bulunamaması
- server context endpoint erişim hatası
- API streaming hatası
- boş transcription
- geçersiz session index

gibi durumların programı gereksiz yere çökertmemesine dikkat et.

---

# 22. Gereksiz refactor yapma

Şunlardan kaçın:

- Abstract Base Class kullanmak sırf kullanılabiliyor diye.
- Her servis için interface/protocol oluşturmak.
- Dependency injection framework eklemek.
- Event bus eklemek.
- Repository pattern'i gereksiz şekilde karmaşıklaştırmak.
- Async mimariye geçmek.
- CLI framework eklemek.
- Dataclass kullanılabilecek yerde karmaşık class hierarchy oluşturmak.
- Mevcut kod stilini tamamen değiştirmek.
- Aynı davranışı gerçekleştirmek için gereksiz üçüncü parti dependency eklemek.

Python'un standart özelliklerini ve basit composition yaklaşımını tercih et.

---

# 23. Refactor sırası

Refactor'ı tek seferde büyük bir yeniden yazım şeklinde gerçekleştirme.

Şu sırayı takip et:

### Aşama 1 — Configuration ve state

- Config değerlerini ayır.
- Runtime globals'ı azalt.
- Uygulama state modelini oluştur.

### Aşama 2 — Session sistemi

- `SessionStorage`
- `SessionManager`
- global session değişkenlerini kaldır/azalt.

Bu aşamanın sonunda mevcut session'ların açılabildiğini doğrula.

### Aşama 3 — Media

Ayır:

```text
audio
files
images
pipe
```

Davranış değişikliği yapma.

### Aşama 4 — UI

Ayır:

```text
MarkdownFormatter
Thinking/stream rendering
terminal helpers
```

### Aşama 5 — Context

Token estimation ve history trimming kodunu `chat/context.py` içine taşı.

### Aşama 6 — LLM

`do_stream_and_respond()` fonksiyonunu parçala:

```text
LLMClient
StreamProcessor
StreamRenderer
```

Persistence işini LLM katmanından çıkar.

### Aşama 7 — ChatService

Mesaj oluşturma, attachment birleştirme, context kontrolü, LLM çağrısı ve history güncellemesini burada koordine et.

### Aşama 8 — Command Router

CLI komutlarını `main()` fonksiyonundan çıkar.

### Aşama 9 — Application

REPL döngüsünü `AgentApplication` içine taşı.

### Aşama 10 — `main.py`

`main.py` dosyasını yalnızca dependency wiring + application startup seviyesine indir.

---

# 24. Her aşamadan sonra doğrulama yap

Her önemli refactor adımından sonra en azından syntax/import kontrolü yap.

Mümkünse:

```bash
python -m compileall .
```

veya eşdeğer bir kontrol kullan.

Uygun olduğunda küçük smoke test'ler gerçekleştir.

Özellikle circular import oluşmadığını kontrol et.

---

# 25. Import tasarımına dikkat et

Modülleri oluştururken circular dependency yaratma.

Örneğin mümkün olduğunca:

```text
application
    ↓
commands/chat
    ↓
sessions/llm/media
```

yönünü koru.

Shared state modelleri veya config gerekiyorsa daha alt seviyedeki:

```text
config.py
state.py
```

gibi modüllerde tutulabilir.

---

# 26. Session dosya uyumluluğunu koru

Mevcut `chats/` dizinindeki eski sohbetler refactor sonrasında da açılabilmeli.

Mevcut yapı yaklaşık olarak:

```text
chats/
└── <session-id>/
    ├── history.json
    ├── metadata.json
    └── token_log.txt
```

şeklinde devam etmeli.

Mevcut veriler için migration gerektirecek değişikliklerden kaçın.

---

# 27. Özellikle koruman gereken bir multimodal davranış

Görsel gönderildiğinde gerçek base64 görseli kalıcı history içine kaydetmek yerine mevcut kodun yaptığı gibi history'de metinsel bir temsil tutuluyor.

Bu davranışı gereksiz yere değiştirme.

Ama multimodal mesaj LLM'e gönderilirken gerekli:

```text
image_url
+
text
```

içeriği korunmalı.

---

# 28. Context trimming davranışını dikkatlice incele

Mevcut kod history'yi user/assistant çiftleri halinde kırpmaya çalışıyor.

Bu davranışı refactor sırasında yanlışlıkla tek mesaj kırpacak veya conversation ordering'i bozacak hale getirme.

Ayrıca gerçek server usage token değerleri mevcutsa onları; yoksa mevcut yaklaşık token hesabını kullanma davranışını koru.

---

# 29. Stream sistemi için fonksiyonel sınır

Stream katmanı mümkün olduğunca:

```text
input:
    messages

output:
    StreamResult
```

mantığına yaklaşmalı.

Session persistence gibi yan etkiler üst seviyede yönetilmeli.

Terminal streaming doğal olarak canlı output gerektirdiği için renderer dependency'si kullanılabilir.

Ancak LLM transport katmanı ile session storage birbirine bağlanmamalı.

---

# 30. Kod kalitesi

Yeni kod:

- okunabilir,
- açık isimlendirilmiş,
- Pythonic,
- gereksiz yorumlardan arındırılmış,
- type hint kullanılan,
- küçük ve tek sorumluluklu fonksiyonlara sahip

olsun.

Ancak sırf fonksiyon kısa olsun diye mantıksal olarak tek bir işlemi gereksiz yere 5–10 fonksiyona bölme.

---

# 31. Mevcut kullanıcı deneyimini koru

Terminal arayüzü refactor sonrasında kullanıcı açısından mümkün olduğunca aynı görünmeli.

Özellikle:

```text
Sen:
Ajan:
💭 Düşünüyor...
context bar
token stats
renkli Markdown
```

davranışlarını koru.

Bu görev UI yeniden tasarımı değildir.

---

# 32. Yeni özellik ekleme

Bu refactor sırasında aşağıdaki gibi yeni özellikler ekleme:

- TTS
- web search
- tool calling
- GUI
- TUI
- yeni database
- yeni model provider
- async streaming
- plugin sistemi

Mimari ileride bunları eklemeye uygun olabilir, ancak bu görev kapsamında implementasyonlarını yapma.

---

# 33. Çalışma biçimin

Önce kodu analiz et.

Ardından mevcut bağımlılıkları çıkar.

Sonra küçük ve güvenli adımlarla refactor gerçekleştir.

Bir kodu yeni modüle taşırken:

1. bağımlılıklarını belirle,
2. ilgili modülü oluştur,
3. kodu taşı,
4. importları düzelt,
5. eski yeri temizle,
6. syntax/import kontrolü yap,
7. sonra sonraki aşamaya geç.

Çalışan kodu bir anda tamamen silip sıfırdan yeniden oluşturma.

---

# 34. Karar verme yetkin

Yukarıdaki dosya yapısı bir rehberdir.

Kodun gerçek yapısını gördükten sonra:

- iki küçük modülü birleştirebilir,
- anlamsız bir class yerine fonksiyon kullanabilir,
- uygun yerde dataclass kullanabilir,
- bazı isimleri iyileştirebilirsin.

Ancak mimari prensipleri koru:

> yüksek cohesion, düşük coupling, kontrollü state, tek sorumluluk, açık bağımlılık yönü.

---

# 35. Tamamlandığında bana rapor ver

Refactor bittikten sonra aşağıdaki formatta kısa ama teknik bir rapor oluştur:

## Oluşturulan yapı

Yeni dosya ağacını göster.

## Taşınan sorumluluklar

Örneğin:

```text
main.py → application.py
main.py → commands/*
main.py → media/*
...
```

## State değişiklikleri

Hangi global state'lerin kaldırıldığını veya nereye taşındığını açıkla.

## Önemli mimari kararlar

Özellikle:

- session management
- persistence
- LLM streaming
- attachments
- command routing
- terminal rendering

konularındaki kararları açıkla.

## Korunan davranışlar

Mevcut özelliklerin hangilerinin doğrulandığını belirt.

## Bulduğun mevcut hatalar

Refactor sırasında fark ettiğin önceden var olan bug veya problemli davranışları ayrı olarak belirt.

Bunları sessizce değiştirme.

Eğer güvenli ve davranışı açıkça hatalı bir bug ise düzeltebilirsin, fakat raporda mutlaka belirt.

## Doğrulamalar

Çalıştırdığın:

- compile checks,
- tests,
- smoke tests

varsa sonuçlarını yaz.

---

# Son hedef

Refactor sonunda kod tabanı şu zihinsel modele sahip olmalı:

```text
main.py             → kur ve başlat
application.py      → uygulama yaşam döngüsü / REPL

config.py           → configuration
state.py            → runtime state

commands/           → CLI command handling
sessions/           → session + persistence
chat/               → message/context coordination
llm/                → model communication + stream processing
media/              → audio/file/image/pipe
ui/                 → terminal presentation
```

En önemli kriter:

> `main.py` artık uygulamanın bütün detaylarını bilen devasa bir dosya olmamalı.

Mevcut programın davranışını korurken, her modülün neden var olduğu ve hangi sorumluluğa sahip olduğu kodu okuyan biri tarafından kolayca anlaşılabilmeli.