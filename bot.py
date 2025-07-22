import os
import logging
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
import traceback
from database import export_database_to_file

load_dotenv()

logger = logging.getLogger('leaguebot')
logger.setLevel(logging.DEBUG)

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

@bot.event
async def on_ready():
    logger.info(f'Bot conectado como {bot.user}')
    try:
        await bot.load_extension('Cogs.LeagueCog')
        logger.info('Cog LeagueCog cargado.')
        guild_id = os.getenv('GUILD_ID')
        if guild_id:
            try:
                guild = discord.Object(id=int(guild_id))
                synced = await bot.tree.sync(guild=guild)
                logger.info(f'Comandos sincronizados al guild {guild_id}: {[cmd.name for cmd in synced]}')
            except Exception as e:
                logger.error(f'Error al sincronizar comandos al guild {guild_id}: {e}', exc_info=True)
        else:
            synced = await bot.tree.sync()
            logger.info(f'Comandos sincronizados globalmente: {[cmd.name for cmd in synced]}')
        export_database_to_file()
        logger.info('Copia de la base de datos generada al iniciar el bot.')
    except Exception as e:
        logger.error(f'Error al cargar extensiones, sincronizar o exportar la base de datos: {e}', exc_info=True)

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    logger.error(f'Error en comando: {error}', exc_info=True)
    embed = discord.Embed(title="❌ Error", description=str(error), color=discord.Color.red())
    if interaction.response.is_done():
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.response.send_message(embed=embed, ephemeral=True)

if __name__ == '__main__':
    BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
    if not BOT_TOKEN:
        logger.error("DISCORD_BOT_TOKEN no está configurado.")
        raise RuntimeError("DISCORD_BOT_TOKEN no está configurado.")
    bot.run(BOT_TOKEN)