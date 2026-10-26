import os
import math
import shutil
from PIL import Image, ImageEnhance, ImageFilter, ImageDraw, ImageChops

AVATAR_SRC = r"C:\Users\RafaPlug11\.gemini\antigravity-ide\brain\b43aff08-c793-4b12-9324-43ed594fe89e\denzel_avatar_base_1792892139252.jpg"
BANNER_SRC = r"C:\Users\RafaPlug11\.gemini\antigravity-ide\brain\b43aff08-c793-4b12-9324-43ed594fe89e\denzel_banner_1792892152681.jpg"

WORKSPACE = r"c:\Users\RafaPlug11\Pictures\DenzerBotDiscord"

# 1. Copiar banner y avatar estático en alta calidad
shutil.copyfile(AVATAR_SRC, os.path.join(WORKSPACE, "avatar_base.jpg"))
shutil.copyfile(BANNER_SRC, os.path.join(WORKSPACE, "banner.png"))
print("Archivos base copiados.")

# 2. Generar el avatar animado en GIF (formato Discord)
base_img = Image.open(AVATAR_SRC).convert("RGBA")
target_size = (400, 400)
base_img = base_img.resize(target_size, Image.Resampling.LANCZOS)

frames = []
total_frames = 24  # ~1.6 segundos a 15 fps (bucle perfecto de trap beat)

for i in range(total_frames):
    t = (i / total_frames) * 2 * math.pi
    
    # Efecto 1: Pulso de bajo / Bass pulse (zoom rítmico sutil)
    pulse = 1.0 + 0.035 * math.sin(t)
    w = int(target_size[0] * pulse)
    h = int(target_size[1] * pulse)
    scaled = base_img.resize((w, h), Image.Resampling.BILINEAR)
    left = (w - target_size[0]) // 2
    top = (h - target_size[1]) // 2
    frame = scaled.crop((left, top, left + target_size[0], top + target_size[1]))

    # Efecto 2: Variación de brillo y contraste del neon verde
    glow = 1.0 + 0.18 * math.sin(t)
    enhancer = ImageEnhance.Brightness(frame)
    frame = enhancer.enhance(glow)
    
    # Efecto 3: Partículas y chispas flotantes de dinero / diamantes
    overlay = Image.new("RGBA", target_size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    
    # Partículas flotantes que suben en bucle
    for p_idx in range(12):
        px = int((p_idx * 37 + (i * 2.5)) % target_size[0])
        py = int((p_idx * 43 - (i * 4.5)) % target_size[1])
        alpha = int(140 + 90 * math.sin(t + p_idx))
        radius = 2 + (p_idx % 3)
        draw.ellipse(
            (px - radius, py - radius, px + radius, py + radius),
            fill=(0, 255, 128, alpha)
        )
    
    # Marco / Borde neón con pulso
    border_alpha = int(120 + 80 * math.sin(t))
    draw.rectangle([0, 0, target_size[0] - 1, target_size[1] - 1], outline=(0, 255, 136, border_alpha), width=3)
    
    frame = Image.alpha_composite(frame, overlay)

    # Efecto 4: Glitch cyberpunk en frames específicos (frame 6 y 18 para el beat drop)
    if i in (6, 18):
        # Desplazamiento de canales RGB
        r, g, b, a = frame.split()
        r = ImageChops.offset(r, 6, 0)
        b = ImageChops.offset(b, -6, 0)
        frame = Image.merge("RGBA", (r, g, b, a))

    # Convertir a paleta adaptable optimizada para GIF nítido
    gif_frame = frame.convert("RGB").quantize(colors=128, method=Image.Quantize.MEDIANCUT)
    frames.append(gif_frame)

gif_path = os.path.join(WORKSPACE, "avatar.gif")
frames[0].save(
    gif_path,
    save_all=True,
    append_images=frames[1:],
    duration=65,  # 65ms por frame (~15.3 fps)
    loop=0,
    optimize=True
)

file_size_kb = os.path.getsize(gif_path) / 1024
print(f"Avatar animado creado exitosamente: {gif_path} ({file_size_kb:.1f} KB)")
