from application import AgentApplication
from chat.attachments import AttachmentManager
from chat.context import ContextManager
from chat.mentions import MentionProcessor
from chat.service import ChatService
from commands.router import CommandRouter
from commands.search_commands import SearchCommands
from commands.session_commands import SessionCommands
from commands.system_commands import SystemCommands
from config import load_config
from llm.client import LLMClient
from media.audio import AudioService
from media.files import TextFileLoader
from media.images import ImageLoader
from media.pipe import PipeInput
from search.service import SearchService
from sessions.manager import SessionManager
from sessions.storage import SessionStorage
from state import ApplicationState
from ui.stream_renderer import StreamRenderer
from ui.terminal import TerminalUI


def main():
    config = load_config()

    state = ApplicationState()

    storage = SessionStorage(config.chat_directory)
    session_manager = SessionManager(storage)

    terminal = TerminalUI()
    context = ContextManager(config.system_prompt, config.context_safety_ratio)
    renderer = StreamRenderer()
    llm_client = LLMClient(config)
    audio = AudioService(config)
    files = TextFileLoader()
    images = ImageLoader()
    pipe_input = PipeInput(config.pipe_path)
    attachments = AttachmentManager(state)
    search_service = SearchService()

    chat_service = ChatService(
        state, attachments, context, llm_client, session_manager, renderer,
        terminal, search_service,
    )

    session_commands = SessionCommands(session_manager, context, attachments, terminal)
    system_commands = SystemCommands(session_manager, terminal)
    search_commands = SearchCommands(search_service, attachments, chat_service, terminal)
    router = CommandRouter(session_commands, system_commands, search_commands)
    mentions = MentionProcessor(
        files, images, attachments, search_service, terminal, audio=audio,
    )

    app = AgentApplication(
        config,
        state,
        terminal,
        router,
        chat_service,
        session_manager,
        attachments,
        pipe_input,
        context,
        mentions,
    )
    app.run()


if __name__ == "__main__":
    main()
