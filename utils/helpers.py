from discord import Interaction
from .make_embed import error
from database import get_team_by_name, get_team_by_manager, get_player_by_id

async def send_error(interaction: Interaction, message: str):
    embed = error(message)
    await interaction.response.send_message(embed=embed, ephemeral=True)

async def resolve_team(interaction: Interaction, name: str = None):
    if name:
        team = get_team_by_name(name)
    else:
        team = get_team_by_manager(interaction.user.id)
    if not team:
        await send_error(interaction, 'Equipo no encontrado.')
        return None
    return team

async def check_ban(interaction: Interaction, player_id: int):
    player = get_player_by_id(interaction.guild.id, player_id)
    if player and player['banned']:
        await send_error(interaction, "Este jugador está sancionado y no puede interactuar con el bot.")
        return True
    return False
