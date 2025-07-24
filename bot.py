import os
import logging
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
import traceback
from database import export_database_to_file, is_guild_banned, create_tables, create_screenshots_table, create_amistosos_tables

load_dotenv()

logger = logging.getLogger('bot')
logger.setLevel(logging.DEBUG)

logging.basicConfig(level=logging.INFO, filename='bot.log', format='[%(asctime)s] [%(levelname)s] %(message)s')

file_handler = logging.FileHandler('bot.log')
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logger.addHandler(file_handler)

console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
logger.addHandler(console_handler)

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
intents.messages = True
intents.guild_messages = True
intents.dm_messages = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

OWNER_ID = int(os.getenv("OWNER_ID", "509812954426769418"))  # Agrega tu ID en .env como OWNER_ID

@bot.event
async def on_ready():
    logger.info(f'Bot conectado como {bot.user}')
    try:
        await bot.load_extension('Cogs.LeagueCog')
        logger.info('Cog LeagueCog cargado.')
        for guild in bot.guilds:
            if not is_guild_banned(guild.id):
                create_tables(guild.id)
                create_screenshots_table(guild.id)
                create_amistosos_tables(guild.id)
                synced = await bot.tree.sync(guild=discord.Object(id=guild.id))
                logger.info(f'Comandos sincronizados para guild {guild.id}: {[cmd.name for cmd in synced]}')
            else:
                await guild.leave()
                logger.info(f'Bot salió del guild baneado {guild.id}')
        global_synced = await bot.tree.sync()
        logger.info(f'Comandos sincronizados globalmente: {[cmd.name for cmd in global_synced]}')
        export_database_to_file(guild_id=None)
        logger.info('Bot completamente inicializado.')
    except Exception as e:
        logger.error(f'Error al cargar extensiones o sincronizar: {e}', exc_info=True)

@bot.event
async def on_guild_join(guild):
    if is_guild_banned(guild.id):
        await guild.leave()
        logger.info(f'Bot salió del guild baneado {guild.id}')
    else:
        create_tables(guild.id)
        create_screenshots_table(guild.id)
        create_amistosos_tables(guild.id)
        synced = await bot.tree.sync(guild=discord.Object(id=guild.id))
        logger.info(f'Comandos sincronizados para nuevo guild {guild.id}: {[cmd.name for cmd in synced]}')

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    logger.error(f'Error en comando: {error}', exc_info=True)
    embed = discord.Embed(title="❌ Error", description=str(error), color=discord.Color.red())
    if interaction.response.is_done():
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="list_guilds", description="Lista los servidores en los que está el bot (solo owner)")
async def list_guilds(interaction: discord.Interaction):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("No tienes permiso para usar este comando.", ephemeral=True)
        return
    guilds_list = []
    for guild in bot.guilds:
        if not is_guild_banned(guild.id):
            guilds_list.append(f"ID: {guild.id} | Nombre: {guild.name}")
    if not guilds_list:
        description = "El bot no está en ningún servidor no baneado."
    else:
        description = "\n".join(guilds_list)
    embed = discord.Embed(
        title="📋 Servidores del Bot",
        description=description,
        color=discord.Color.blue()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)
    logger.info(f"El dueño {interaction.user.id} ejecutó /list_guilds.")

@bot.tree.command(name="ban_guild", description="Banear un guild (solo owner)")
@app_commands.describe(guild_id="ID del guild a banear")
async def ban_guild_command(interaction: discord.Interaction, guild_id: str):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("No tienes permiso para usar este comando.", ephemeral=True)
        return
    try:
        if not guild_id.isdigit():
            raise ValueError("El ID del guild debe ser un número entero.")
        guild_id_int = int(guild_id)
        if len(guild_id) < 10:
            raise ValueError("El ID del guild es demasiado corto. Los IDs de Discord suelen tener al menos 10 dígitos.")
        
        from database import ban_guild
        ban_guild(guild_id_int)
        guild = bot.get_guild(guild_id_int)
        if guild:
            await guild.leave()
            logger.info(f'Bot salió del guild {guild_id_int} tras ser baneado.')
        await interaction.response.send_message(f"Guild {guild_id_int} baneado.", ephemeral=True)
    except ValueError as ve:
        logger.error(f"Error de validación en guild_id {guild_id}: {ve}")
        await interaction.response.send_message(f"Error: {str(ve)}", ephemeral=True)
    except sqlite3.Error as se:
        logger.error(f"Error en la base de datos al banear guild {guild_id}: {se}")
        await interaction.response.send_message("Error al banear el guild en la base de datos.", ephemeral=True)
    except Exception as e:
        logger.error(f"Error inesperado al banear guild {guild_id}: {e}")
        await interaction.response.send_message(f"Error inesperado: {e}", ephemeral=True)

@bot.tree.command(name="unban_guild", description="Desbanear un guild (solo owner)")
@app_commands.describe(guild_id="ID del guild a desbanear")
async def unban_guild_command(interaction: discord.Interaction, guild_id: str):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("No tienes permiso para usar este comando.", ephemeral=True)
        return
    try:
        if not guild_id.isdigit():
            raise ValueError("El ID del guild debe ser un número entero.")
        guild_id_int = int(guild_id)
        if len(guild_id) < 10:
            raise ValueError("El ID del guild es demasiado corto. Los IDs de Discord suelen tener al menos 10 dígitos.")
        
        from database import unban_guild, is_guild_banned
        if not is_guild_banned(guild_id_int):
            raise ValueError(f"El guild {guild_id_int} no está baneado.")
        
        unban_guild(guild_id_int)
        await interaction.response.send_message(f"Guild {guild_id_int} desbaneado.", ephemeral=True)
        logger.info(f"Guild {guild_id_int} desbaneado por {interaction.user.id}.")
    except ValueError as ve:
        logger.error(f"Error de validación en guild_id {guild_id}: {ve}")
        await interaction.response.send_message(f"Error: {str(ve)}", ephemeral=True)
    except sqlite3.Error as se:
        logger.error(f"Error en la base de datos al desbanear guild {guild_id}: {se}")
        await interaction.response.send_message(f"Error al desbanear el guild en la base de datos: {str(se)}", ephemeral=True)
    except Exception as e:
        logger.error(f"Error inesperado al desbanear guild {guild_id}: {e}")
        await interaction.response.send_message(f"Error inesperado: {str(e)}", ephemeral=True)

@bot.tree.command(name="sync_commands", description="Forzar sincronización de comandos (solo owner)")
async def sync_commands(interaction: discord.Interaction):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("No tienes permiso para usar este comando.", ephemeral=True)
        return
    try:
        synced = await bot.tree.sync(guild=discord.Object(id=interaction.guild.id))
        commands_list = [cmd.name for cmd in synced]
        await interaction.response.send_message(f"Comandos sincronizados: {commands_list}", ephemeral=True)
        logger.info(f"Comandos sincronizados manualmente para guild {interaction.guild.id}: {commands_list}")
    except Exception as e:
        await interaction.response.send_message(f"Error al sincronizar: {e}", ephemeral=True)
        logger.error(f"Error al sincronizar comandos manualmente: {e}")

@bot.tree.command(name="open_market", description="Abrir el mercado de transferencias (solo admins)")
@app_commands.checks.has_permissions(administrator=True)
async def open_market(interaction: discord.Interaction):
    from database import set_market_status
    set_market_status(interaction.guild.id, "open")
    await interaction.response.send_message("El mercado de transferencias ha sido abierto.", ephemeral=False)

@bot.tree.command(name="close_market", description="Cerrar el mercado de transferencias (solo admins)")
@app_commands.checks.has_permissions(administrator=True)
async def close_market(interaction: discord.Interaction):
    from database import set_market_status
    set_market_status(interaction.guild.id, "closed")
    await interaction.response.send_message("El mercado de transferencias ha sido cerrado.", ephemeral=False)

if __name__ == '__main__':
    BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
    if not BOT_TOKEN:
        logger.error("DISCORD_BOT_TOKEN no está configurado.")
        raise RuntimeError("DISCORD_BOT_TOKEN no está configurado.")
    bot.run(BOT_TOKEN)
