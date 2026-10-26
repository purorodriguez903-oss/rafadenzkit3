import os
import sys
import re
import time
import random
import socket
import asyncio
import logging
from logging.handlers import RotatingFileHandler
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
from aiohttp import web
import edge_tts
from gtts import gTTS

# Cargar variables de entorno
load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
VOICE_CHANNEL_ID = int(os.getenv("VOICE_CHANNEL_ID", "1543395577289777202"))
GUILD_ID = int(os.getenv("GUILD_ID", "1387608034641055785"))
PORT = int(os.getenv("PORT", "8080"))

# Configuración de Logging Dual (Consola + Archivo bot.log con rotación)
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.log")
file_handler = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
console_handler = logging.StreamHandler(sys.stdout)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[file_handler, console_handler]
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

# Candado de instancia única local para evitar que se ejecuten 2 bots en la misma máquina
SINGLE_INSTANCE_SOCKET = None
def ensure_single_local_instance(port: int = 49152):
    """Garantiza que solo una instancia del bot corra en esta máquina."""
    global SINGLE_INSTANCE_SOCKET
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(('127.0.0.1', port))
        SINGLE_INSTANCE_SOCKET = s
    except OSError:
        logger.error("❌ ERROR: Ya hay otra instancia de DenzerBot ejecutándose en esta PC.")
        logger.error("   Cierra la otra ventana o ejecuta detener_bot.bat antes de iniciar.")
        sys.exit(1)

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

def format_uptime(seconds: float) -> str:
    """Convierte segundos en formato legible de horas y minutos."""
    total_seconds = int(seconds)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"

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
        self.start_time = time.time()
        self.current_status_index = 0
        self.watchdog_fail_count = 0

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

    async def start_cloud_health_server(self):
        """
        Servidor HTTP liviano para despliegue en la nube (Railway / Render / Koyeb).
        Responde '200 OK' al healthcheck de Railway para evitar que el contenedor se reinicie a los 2 minutos.
        """
        try:
            app = web.Application()
            async def handle_ping(request):
                uptime_str = format_uptime(time.time() - self.start_time)
                return web.Response(text=f"OK - Denzer 24/7 Voice Bot Online (Uptime: {uptime_str})")

            app.router.add_get("/", handle_ping)
            app.router.add_get("/health", handle_ping)

            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, "0.0.0.0", PORT)
            await site.start()
            logger.info(f"🌐 Servidor de salud activo en puerto {PORT} (Protección Anti-Reinicio Cloud).")
        except Exception as e:
            logger.debug(f"Aviso servidor de salud HTTP: {e}")

    async def on_ready(self):
        logger.info("=" * 65)
        logger.info(f"🟢 BOT EN LÍNEA: {self.user.name} ({self.user.id})")
        logger.info(f"🔊 Canal de Voz Objetivo: {self.target_channel_id}")
        logger.info("🎙️ Saludo: 'Bienvenido papi [Username]' (Voz Latina Real)")
        logger.info("💬 TTS de Chat: Activado (Texto libre y comando /tts)")
        logger.info("🛡️ Modo 24/7 Inmortal: Activado (Keepalive Nativo Opus + Anti-Desconexión)")
        logger.info("=" * 65)

        # Iniciar servidor web de salud para Railway si aplica
        await self.start_cloud_health_server()

        # Sincronizar comando Slash /tts en el servidor
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
        if not self.voice_keepalive.is_running():
            self.voice_keepalive.start()
        if not self.audio_worker.is_running():
            self.audio_worker.start()
        if not self.status_rotator.is_running():
            self.status_rotator.start()

    async def ensure_voice_connection(self):
        """
        Asegura la conexión ininterrumpida al canal de voz objetivo.
        NO destruye conexiones vivas para garantizar que el contador de horas no se reinicie.
        """
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

                # CASO 1: Si ya está en el canal fijado y conectado, NO TOCAR NADA (evita reiniciar el tiempo)
                if voice_client and voice_client.is_connected() and voice_client.channel.id == self.target_channel_id:
                    self.watchdog_fail_count = 0
                    return

                # CASO 2: Si el bot fue arrastrado/movido a otro canal de voz, moverlo de vuelta suavemente
                if voice_client and voice_client.is_connected() and voice_client.channel.id != self.target_channel_id:
                    logger.warning(f"⚠️ Bot fuera de su canal. Moviendo suavemente a '{target_channel.name}'...")
                    try:
                        await asyncio.wait_for(voice_client.move_to(target_channel), timeout=5.0)
                        logger.info(f"✅ Bot devuelto a '{target_channel.name}'.")
                        self.watchdog_fail_count = 0
                        return
                    except Exception as e:
                        logger.warning(f"Aviso al mover directo ({e}), reconectando...")

                # CASO 3: Desconexión real comprobada, reconectar limpiamente
                if voice_client:
                    try:
                        await voice_client.disconnect(force=True)
                    except Exception:
                        pass
                    await asyncio.sleep(1.0)

                logger.info(f"🔄 Conectando a canal '{target_channel.name}' (ID: {self.target_channel_id})...")
                try:
                    await target_channel.connect(reconnect=True, timeout=30.0, self_deaf=False)
                    logger.info(f"✅ ¡CONECTADO CON ÉXITO A: '{target_channel.name}'!")
                    self.watchdog_fail_count = 0
                except discord.ClientException as ce:
                    logger.warning(f"Aviso al conectar ({ce}), reintentando conexión limpia...")
                    if guild.voice_client:
                        await guild.voice_client.disconnect(force=True)
                        await asyncio.sleep(1.5)
                        await target_channel.connect(reconnect=True, timeout=30.0, self_deaf=False)
                        self.watchdog_fail_count = 0

            except Exception as e:
                logger.error(f"❌ Error en conexión de voz: {e}")

    @tasks.loop(seconds=20)
    async def voice_keepalive(self):
        """
        Envía un paquete nativo Opus silencioso de 3 bytes periódicamente.
        Mantiene el Voice Gateway de Discord activo 24/7 sin desincronización RTP ni consumo de CPU.
        """
        try:
            target_channel = self.get_channel(self.target_channel_id)
            if not target_channel or not target_channel.guild.voice_client:
                return

            vc = target_channel.guild.voice_client
            if vc and vc.is_connected() and not vc.is_playing() and not self.is_playing_speech:
                # Frame oficial Opus de silencio (3 bytes)
                vc.send_audio_packet(b'\xF8\xFF\xFE', encode=False)
        except Exception as e:
            logger.debug(f"Aviso keepalive: {e}")

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
                logger.info("🛡️ Reconectando con gracia de 2 segundos para sesión limpia...")
                await asyncio.sleep(2.0)
                await self.ensure_voice_connection()
            elif after.channel.id != self.target_channel_id:
                logger.warning(f"🚨 ¡ALERTA! El bot fue movido a '{after.channel.name}'.")
                logger.info("🛡️ Regresando al canal fijado suavemente...")
                await asyncio.sleep(1.0)
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
            await asyncio.sleep(0.1)

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
            await asyncio.wait_for(finish_event.wait(), timeout=15.0)
        except Exception as e:
            logger.error(f"Detalle en audio worker: {e}")
        finally:
            self.is_playing_speech = False

    @tasks.loop(seconds=15)
    async def voice_watchdog(self):
        """
        Guardián de conexión inteligente.
        Revisa la conexión cada 15 segundos sin matar conexiones saludables que estén en auto-reconexión.
        """
        try:
            target_channel = self.get_channel(self.target_channel_id)
            if not target_channel:
                return

            guild = target_channel.guild
            voice_client = guild.voice_client

            if not voice_client or not voice_client.is_connected():
                self.watchdog_fail_count += 1
                logger.warning(f"🔍 [Guardián] Sin conexión activa detectada ({self.watchdog_fail_count}/2)...")
                # Solo forzar reconexión si ha fallado de forma persistente (2 chequeos consecutivos = 30s)
                if self.watchdog_fail_count >= 2:
                    logger.info("🔍 [Guardián] Restaurando conexión al canal fijado...")
                    await self.ensure_voice_connection()
            else:
                self.watchdog_fail_count = 0
                if voice_client.channel.id != self.target_channel_id:
                    logger.warning("🔍 [Guardián] Canal diferente detectado. Restaurando...")
                    await self.ensure_voice_connection()

        except Exception as e:
            logger.debug(f"[Guardián] Error: {e}")

    @tasks.loop(seconds=20)
    async def status_rotator(self):
        """Rota los estados en el perfil del bot mostrando el tiempo activo real (horas y minutos)."""
        try:
            uptime_str = format_uptime(time.time() - self.start_time)
            status_list = [
                f"24/7 Online ⏱️ {uptime_str}",
                "Denzel XT 💸 | 100% Inmortal",
                "Leyendo Chat de Voz 🎙️",
                "Usa /tts para hablar 💬"
            ]

            status_text = status_list[self.current_status_index]
            self.current_status_index = (self.current_status_index + 1) % len(status_list)

            activity = discord.Activity(
                type=discord.ActivityType.listening,
                name=status_text
            )
            await self.change_presence(status=discord.Status.online, activity=activity)
        except Exception as e:
            logger.debug(f"Error rotando estado: {e}")

    @voice_watchdog.before_loop
    @voice_keepalive.before_loop
    @audio_worker.before_loop
    @status_rotator.before_loop
    async def before_tasks(self):
        await self.wait_until_ready()

def run_bot():
    # Asegurar instancia única local
    ensure_single_local_instance()

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
