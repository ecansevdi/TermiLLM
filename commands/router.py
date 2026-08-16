from commands.media_commands import MediaCommands
from commands.search_commands import SearchCommands
from commands.session_commands import SessionCommands
from commands.system_commands import SystemCommands


class CommandRouter:
    """Kullanıcı girdisini ilgili komut handler'ına yönlendirir.

    Komut değilse False döner; çağıran ChatService'e devreder.
    """

    def __init__(self, session_commands: SessionCommands,
                 media_commands: MediaCommands,
                 system_commands: SystemCommands,
                 search_commands: SearchCommands):
        self._session = session_commands
        self._media = media_commands
        self._system = system_commands
        self._search = search_commands

    def handle(self, user_input: str, state) -> bool:
        head = user_input.split(maxsplit=1)[0]
        if head == "/arama":
            self._search.ayarlar(state)
            return True
        if head in ("/ara", "/search"):
            self._search.ara(state, user_input)
            return True
        if user_input == "/new":
            self._session.new(state)
            return True
        if user_input == "/chats":
            self._session.chats(state)
            return True
        if user_input.startswith("/open"):
            self._session.open(state, user_input)
            return True
        if user_input.startswith("/rename"):
            self._session.rename(state, user_input)
            return True
        if user_input.startswith("/delete"):
            self._session.delete(state, user_input)
            return True
        if user_input == "/clear":
            self._session.clear(state)
            return True
        if user_input == "/debug":
            self._system.debug(state)
            return True
        if user_input == "/help":
            self._system.help(state)
            return True
        if user_input == "/stats":
            self._system.stats(state)
            return True
        if user_input.startswith("/ses"):
            self._media.ses(state, user_input)
            return True
        if user_input.startswith("/read") or user_input.startswith("/dosya"):
            self._media.read(state, user_input)
            return True
        if user_input.startswith("/resim"):
            self._media.resim(state, user_input)
            return True
        return False
