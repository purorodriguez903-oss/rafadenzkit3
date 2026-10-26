import os
import sys
import re
import random
import asyncio
import logging
import unicodedata
from dotenv import load_dotenv

# Forzar codificación UTF-8 en consolas Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

import discord
from discord import app_commands
from discord.ext import tasks
import edge_tts
from gtts import gTTS

# Cargar variables de entorno
load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
VOICE_CHANNEL_ID = int(os.getenv("VOICE_CHANNEL_ID", "1543395577289777202"))
GUILD_ID = int(os.getenv("GUILD_ID", "1387608034641055785"))

# Configuración de Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("Denzer247Bot")

# Cargar librería Opus de discord para Windows
if not discord.opus.is_loaded():
    try:
        bundled_opus = os.path.join(os.path.dirname(discord.__file__), "bin", "libopus-0.x64.dll")
        if os.path.exists(bundled_opus):
            discord.opus.load_opus(bundled_opus)
            logger.info("Librería Opus cargada correctamente.")
    except Exception as e:
        logger.warning(f"Aviso al cargar Opus: {e}")

# Carpeta para archivos temporales de audio
AUDIO_TEMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp_audio")
os.makedirs(AUDIO_TEMP_DIR, exist_ok=True)

def extract_natural_name(member: discord.Member) -> str:
    """
    Limpia y extrae el nombre natural y pronunciable de CUALQUIER usuario.
    Normaliza fuentes góticas/estilizadas y quita clanes/emojis.
    """
    raw_name = member.display_name or member.global_name or member.name or "amigo"

    norm = unicodedata.normalize('NFKC', str(raw_name))
    spaced = re.sub(r'[-$_./\\#@+!*~,;:|()\[\]{}<>]', ' ', norm)
    cleaned = re.sub(r'[^\w\s]', '', spaced)
    words = cleaned.split()

    if not words:
        clean_fallback = re.sub(r'[^\w]', '', unicodedata.normalize('NFKC', member.name))
        return clean_fallback if clean_fallback else "amigo"

    filtered = [w for w in words if len(w) > 1]
    main_name = filtered[0] if filtered else words[0]

    if main_name.lower().endswith('yt') and len(main_name) > 3:
        main_name = main_name[:-2]

    return main_name

def clean_chat_message(content: str) -> str:
    """Limpia el mensaje de texto para que suene fluido al leerse por TTS."""
    text = re.sub(r'<@!?[0-9]+>', '', content)
    text = re.sub(r'<#[0-9]+>', '', text)
    text = re.sub(r'https?://\S+', 'un enlace', text)
    text = re.sub(r'<a?:\w+:\d+>', '', text)
    text = ' '.join(text.split())
    if len(text) > 140:
        text = text[:137] + "..."
    return text.strip()

class SilenceSource(discord.AudioSource):
    """
    Emite 20ms de silencio PCM estéreo a 48kHz (3840 bytes).
    Mantiene la conexión de Discord activa 24/7 sin timeouts.
    """
    def read(self):
        return b'\x00' * 3840

class DenzerVoiceBot(discord.Client):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.tree = app_commands.CommandTree(self)
        self.target_channel_id = VOICE_CHANNEL_ID
        self.guild_id = GUILD_ID
        self.connection_lock = asyncio.Lock()
        self.audio_queue = asyncio.Queue()
        self.is_playing_speech = False
        self.user_join_cooldowns = {}
        self.current_status_index = 0

        self.status_list = [
            "Canal de voz 24/7 🔊",
            "Denzel XT 💸 | 100% Online",
            "Leyendo Chat de Voz 🎙️",
            "Usa /tts para hablar 💬"
        ]

        self.setup_slash_commands()

    def setup_slash_commands(self):
        @self.tree.command(name="tts", description="Lee tu mensaje en voz alta en el canal de voz para los que no tienen mic")
        @app_commands.describe(mensaje="El texto que quieres que la voz latina diga en la llamada")
        async def tts_cmd(interaction: discord.Interaction, mensaje: str):
            author_name = extract_natural_name(interaction.user)
            clean_msg = clean_chat_message(mensaje)
            if not clean_msg:
                await interaction.response.send_message("❌ Mensaje vacío o no válido.", ephemeral=True)
                return

            speech_text = f"{author_name} dice: {clean_msg}"
            await interaction.response.send_message(f"🎙️ **{author_name} dice:** {clean_msg}")

            try:
                audio_file = await self.generate_speech_audio(speech_text)
                await self.audio_queue.put(audio_file)
            except Exception as e:
                logger.error(f"Error generando TTS de comando /tts: {e}")

    async def on_ready(self):
        logger.info("=" * 65)
        logger.info(f"🟢 BOT EN LÍNEA: {self.user.name} ({self.user.id})")
        logger.info(f"🔊 Canal de Voz Objetivo: {self.target_channel_id}")
        logger.info("🎙️ Saludo: 'Bienvenido papi [Username]' (Voz Latina Real)")
        logger.info("💬 TTS de Chat: Activado (Texto libre y comando /tts)")
        logger.info("🛡️ Modo 24/7 Inmortal: Activado")
        logger.info("=" * 65)

        # Sincronizar comando Slash /tts instantáneamente en el servidor
        try:
            guild_obj = discord.Object(id=self.guild_id)
            self.tree.copy_global_to(guild=guild_obj)
            await self.tree.sync(guild=guild_obj)
            logger.info("⚡ Comandos Slash (/tts) sincronizados en el servidor.")
        except Exception as e:
            logger.warning(f"Aviso al sincronizar slash commands: {e}")

        # Conectar al canal fijado
        await self.ensure_voice_connection()

        # Iniciar loops en segundo plano
        if not self.voice_watchdog.is_running():
            self.voice_watchdog.start()
        if not self.audio_worker.is_running():
            self.audio_worker.start()
        if not self.status_rotator.is_running():
            self.status_rotator.start()

    def start_silence_playback(self, voice_client: discord.VoiceClient):
        """Mantiene audio de silencio constante cuando no hay nadie hablando."""
        try:
            if voice_client and voice_client.is_connected() and not voice_client.is_playing() and not self.is_playing_speech:
                if discord.opus.is_loaded():
                    def after_callback(err):
                        if err:
                            logger.error(f"Error en silencio de fondo: {err}")
                        if voice_client.is_connected() and not voice_client.is_playing() and not self.is_playing_speech:
                            try:
                                voice_client.play(SilenceSource(), after=after_callback)
                            except Exception:
                                pass

                    voice_client.play(SilenceSource(), after=after_callback)
        except Exception as e:
            logger.debug(f"Aviso en silencio: {e}")

    async def ensure_voice_connection(self):
        """Asegura la conexión ininterrumpida al canal de voz objetivo."""
        if self.connection_lock.locked():
            return

        async with self.connection_lock:
            try:
                target_channel = self.get_channel(self.target_channel_id)
                if not target_channel:
                    try:
                        target_channel = await self.fetch_channel(self.target_channel_id)
                    except Exception as e:
                        logger.error(f"❌ No se encontró el canal {self.target_channel_id}: {e}")
                        return

                guild = target_channel.guild
                voice_client = guild.voice_client

                # Si ya está en el canal correcto y conectado
                if voice_client and voice_client.is_connected():
                    if voice_client.channel.id == self.target_channel_id:
                        if not self.is_playing_speech and not voice_client.is_playing():
                            self.start_silence_playback(voice_client)
                        return
                    else:
                        logger.warning(f"⚠️ Bot fuera de su canal. Moviendo de regreso a '{target_channel.name}'...")
                        try:
                            await asyncio.wait_for(voice_client.move_to(target_channel), timeout=3.0)
                            self.start_silence_playback(voice_client)
                            logger.info(f"✅ Bot devuelto a '{target_channel.name}'.")
                            return
                        except Exception as e:
                            logger.warning(f"Aviso al mover directo ({e}), forzando reconexión rápida...")
                            try:
                                await voice_client.disconnect(force=True)
                            except Exception:
                                pass

                # Limpiar si hay conexión previa caída
                if voice_client:
                    try:
                        await voice_client.disconnect(force=True)
                    except Exception:
                        pass
                    await asyncio.sleep(0.5)

                logger.info(f"🔄 Conectando a canal '{target_channel.name}' (ID: {self.target_channel_id})...")
                try:
                    vc = await target_channel.connect(reconnect=True, timeout=25.0, self_deaf=False)
                    logger.info(f"✅ ¡CONECTADO CON ÉXITO A: '{target_channel.name}'!")
                    self.start_silence_playback(vc)
                except discord.ClientException as ce:
                    logger.warning(f"Aviso al conectar: {ce}. Reintentando...")
                    if guild.voice_client:
                        await guild.voice_client.disconnect(force=True)
                        await asyncio.sleep(1)
                        vc = await target_channel.connect(reconnect=True, timeout=25.0, self_deaf=False)
                        self.start_silence_playback(vc)

            except Exception as e:
                logger.error(f"❌ Error en conexión de voz: {e}")

    async def generate_speech_audio(self, text_to_say: str) -> str:
        """Genera el audio en MP3 usando la voz neuronal latina realista (es-MX-DaliaNeural)."""
        file_path = os.path.join(AUDIO_TEMP_DIR, f"tts_{int(asyncio.get_event_loop().time() * 1000)}.mp3")

        try:
            tts = edge_tts.Communicate(text_to_say, voice="es-MX-DaliaNeural", rate="+3%", pitch="-1Hz")
            await tts.save(file_path)
        except Exception as e:
            logger.warning(f"Aviso en Edge-TTS ({e}), usando gTTS como respaldo...")
            def make_gtts():
                g = gTTS(text=text_to_say, lang="es", tld="com.mx")
                g.save(file_path)
            await asyncio.to_thread(make_gtts)

        return file_path

    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """
        1. Protecciones Anti-Kick y Anti-Move para el Bot.
        2. Saludo con voz latina: 'Bienvenido papi [Username]' al entrar.
        """
        # Caso 1: Eventos del propio bot
        if member.id == self.user.id:
            if after.channel is None:
                logger.warning("🚨 ¡ALERTA! El bot fue desconectado del canal.")
                logger.info("🛡️ Reconectando inmediatamente...")
                await asyncio.sleep(0.1)
                await self.ensure_voice_connection()
            elif after.channel.id != self.target_channel_id:
                logger.warning(f"🚨 ¡ALERTA! El bot fue movido a '{after.channel.name}'.")
                logger.info("🛡️ Regresando al canal fijado inmediatamente...")
                await asyncio.sleep(0.1)
                await self.ensure_voice_connection()
            return

        # Ignorar otros bots
        if member.bot:
            return

        # Caso 2: CUALQUIER usuario ENTRA al canal objetivo
        if after.channel and after.channel.id == self.target_channel_id and (before.channel is None or before.channel.id != self.target_channel_id):
            loop_time = asyncio.get_event_loop().time()
            last_join = self.user_join_cooldowns.get(member.id, 0)

            if loop_time - last_join < 2:
                return

            self.user_join_cooldowns[member.id] = loop_time
            clean_name = extract_natural_name(member)

            logger.info(f"👋 [ENTRADA] {member.display_name} ({clean_name}) entró al canal. Encolando saludo...")

            saludos = [
                f"Hola {clean_name}, bienvenido papi, qué bueno que llegaste a la sala.",
                f"Miren quién llegó... Bienvenido papi {clean_name}, ponte cómodo.",
                f"Hola papi {clean_name}, bienvenido a Denzel XT. Disfruta la llamada.",
                f"Qué onda {clean_name}, bienvenido papi, qué gusto tenerte aquí en la sala más dura."
            ]
            frase_saludo = random.choice(saludos)

            try:
                audio_file = await self.generate_speech_audio(frase_saludo)
                await self.audio_queue.put(audio_file)
            except Exception as e:
                logger.error(f"Error generando audio de bienvenida: {e}")

    async def on_message(self, message: discord.Message):
        """
        TTS DE CHAT: Lee en voz alta lo que se escriba en el chat de la llamada.
        """
        if message.author.bot or message.author.id == self.user.id:
            return

        is_target_channel = (message.channel.id == self.target_channel_id)
        is_mentioned = self.user.mentioned_in(message)

        if not is_target_channel and not is_mentioned:
            return

        # Si el contenido viene vacío (porque falta MESSAGE CONTENT INTENT en Discord Portal)
        if not message.content:
            logger.warning(f"⚠️ Mensaje de {message.author} detectado, pero Discord ocultó el texto por falta de 'MESSAGE CONTENT INTENT'.")
            return

        cleaned_text = clean_chat_message(message.content)
        if not cleaned_text:
            return

        author_name = extract_natural_name(message.author)
        logger.info(f"💬 [CHAT TTS] {message.author.display_name} ({author_name}): '{cleaned_text}'")

        speech_text = f"{author_name} dice: {cleaned_text}"

        try:
            try:
                await message.add_reaction("🎙️")
            except Exception:
                pass

            audio_file = await self.generate_speech_audio(speech_text)
            await self.audio_queue.put(audio_file)
        except Exception as e:
            logger.error(f"Error generando audio TTS de chat: {e}")

    @tasks.loop(seconds=1)
    async def audio_worker(self):
        """Procesa y reproduce la fila de audios en orden sin interrupciones."""
        if self.audio_queue.empty() or self.is_playing_speech:
            return

        target_channel = self.get_channel(self.target_channel_id)
        if not target_channel or not target_channel.guild.voice_client:
            return

        voice_client = target_channel.guild.voice_client
        if not voice_client.is_connected():
            return

        audio_file = await self.audio_queue.get()
        if not os.path.exists(audio_file):
            return

        self.is_playing_speech = True
        logger.info("🎙️ Reproduciendo locución...")

        if voice_client.is_playing():
            voice_client.stop()
            await asyncio.sleep(0.2)

        finish_event = asyncio.Event()

        def after_play(err):
            if err:
                logger.error(f"Error en reproducción: {err}")
            try:
                if os.path.exists(audio_file):
                    os.remove(audio_file)
            except Exception:
                pass
            self.loop.call_soon_threadsafe(finish_event.set)

        try:
            audio_source = discord.FFmpegPCMAudio(audio_file)
            voice_client.play(audio_source, after=after_play)
            await asyncio.wait_for(finish_event.wait(), timeout=12.0)
        except Exception as e:
            logger.error(f"Detalle en audio worker: {e}")
        finally:
            self.is_playing_speech = False
            await asyncio.sleep(0.3)
            self.start_silence_playback(voice_client)

    @tasks.loop(seconds=5)
    async def voice_watchdog(self):
        """Revisa la conexión periódicamente."""
        try:
            target_channel = self.get_channel(self.target_channel_id)
            if not target_channel:
                return

            guild = target_channel.guild
            voice_client = guild.voice_client

            if not voice_client or not voice_client.is_connected() or voice_client.channel.id != self.target_channel_id:
                logger.info("🔍 [Guardián] Restaurando conexión al canal...")
                await self.ensure_voice_connection()
            elif not self.is_playing_speech and discord.opus.is_loaded() and not voice_client.is_playing():
                self.start_silence_playback(voice_client)
        except Exception as e:
            logger.debug(f"[Guardián] Error: {e}")

    @tasks.loop(seconds=20)
    async def status_rotator(self):
        """Rota los estados en el perfil del bot."""
        try:
            status_text = self.status_list[self.current_status_index]
            self.current_status_index = (self.current_status_index + 1) % len(self.status_list)

            activity = discord.Activity(
                type=discord.ActivityType.listening,
                name=status_text
            )
            await self.change_presence(status=discord.Status.online, activity=activity)
        except Exception as e:
            logger.debug(f"Error rotando estado: {e}")

    @voice_watchdog.before_loop
    @audio_worker.before_loop
    @status_rotator.before_loop
    async def before_tasks(self):
        await self.wait_until_ready()

def run_bot():
    if not TOKEN:
        logger.error("❌ ERROR: DISCORD_TOKEN no configurado en .env")
        sys.exit(1)

    try:
        intents_full = discord.Intents.default()
        intents_full.guilds = True
        intents_full.voice_states = True
        intents_full.messages = True
        intents_full.message_content = True
        bot = DenzerVoiceBot(intents=intents_full)
        bot.run(TOKEN)
    except discord.errors.PrivilegedIntentsRequired:
        intents_basic = discord.Intents.default()
        intents_basic.guilds = True
        intents_basic.voice_states = True
        intents_basic.messages = True
        bot = DenzerVoiceBot(intents=intents_basic)
        bot.run(TOKEN)

if __name__ == "__main__":
    run_bot()
