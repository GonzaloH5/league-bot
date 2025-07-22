import discord

def success(description: str) -> discord.Embed:
    """Embed verde para mensajes de éxito con título estándar"""
    embed = discord.Embed(title="✅ Éxito", description=description, color=discord.Color.green())
    return embed


def error(description: str) -> discord.Embed:
    """Embed rojo para mensajes de error con título estándar"""
    embed = discord.Embed(title="❌ Error", description=description, color=discord.Color.red())
    return embed


def info(description: str) -> discord.Embed:
    """Embed azul para mensajes informativos con título estándar"""
    embed = discord.Embed(title="ℹ️ Información", description=description, color=discord.Color.blue())
    return embed
