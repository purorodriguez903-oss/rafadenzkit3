import os
import sys
import json
import base64
import urllib.request
from dotenv import load_dotenv

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

load_dotenv()
token = os.getenv("DISCORD_TOKEN")

if not token:
    print("❌ ERROR: No se encontró DISCORD_TOKEN en .env")
    sys.exit(1)

headers = {
    "Authorization": f"Bot {token}",
    "Content-Type": "application/json",
    "User-Agent": "DiscordBot (https://denzel.bot, v1.0)"
}

script_dir = os.path.dirname(os.path.abspath(__file__))
avatar_gif_path = os.path.join(script_dir, "avatar.gif")
banner_path = os.path.join(script_dir, "banner.png")

# 1. Cargar Avatar GIF
avatar_b64 = None
if os.path.exists(avatar_gif_path):
    with open(avatar_gif_path, "rb") as f:
        avatar_b64 = "data:image/gif;base64," + base64.b64encode(f.read()).decode("utf-8")

# 2. Cargar Banner
banner_b64 = None
if os.path.exists(banner_path):
    with open(banner_path, "rb") as f:
        banner_b64 = "data:image/png;base64," + base64.b64encode(f.read()).decode("utf-8")

# 3. Actualizar /users/@me
print("🚀 Actualizando perfil del bot en Discord...")
user_payload = {}
if avatar_b64:
    user_payload["avatar"] = avatar_b64
if banner_b64:
    user_payload["banner"] = banner_b64

if user_payload:
    try:
        req = urllib.request.Request(
            "https://discord.com/api/v10/users/@me",
            data=json.dumps(user_payload).encode("utf-8"),
            headers=headers,
            method="PATCH"
        )
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
            print(f"✅ Avatar y Banner del usuario actualizados exitosamente!")
    except urllib.error.HTTPError as e:
        print(f"⚠️ Error al actualizar usuario: {e.code} - {e.read().decode()}")

# 4. Actualizar descripción / bio en /applications/@me
description = """💸 𝐃𝐄𝐍𝐙𝐄𝐋-𝐗𝐈𝐓 💸 | 𝟐𝟒/𝟕 𝐕𝐎𝐈𝐂𝐄 𝐊𝐄𝐄𝐏𝐄𝐑 🔊
───────────────────────────────
⚡ Bot oficial de voz permanente 24/7.
🛡️ Blindaje Inmortal: Anti-Kick • Anti-Move • Anti-AFK
👑 Activo ininterrumpidamente las 24 horas del día.
───────────────────────────────
💎 Denzel XT | Always Online & Secured."""

app_payload = {
    "description": description
}
if avatar_b64:
    app_payload["icon"] = avatar_b64
if banner_b64:
    app_payload["cover_image"] = banner_b64

try:
    req2 = urllib.request.Request(
        "https://discord.com/api/v10/applications/@me",
        data=json.dumps(app_payload).encode("utf-8"),
        headers=headers,
        method="PATCH"
    )
    with urllib.request.urlopen(req2) as resp:
        print("✅ Descripción (About Me) y portada de aplicación guardadas exitosamente!")
except urllib.error.HTTPError as e:
    print(f"⚠️ Error al actualizar aplicación: {e.code} - {e.read().decode()}")

print("\n🎉 ¡Todos los cambios han sido aplicados exitosamente a Discord!")
