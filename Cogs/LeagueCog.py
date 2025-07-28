import discord
from discord import app_commands, ui
from discord.ext import commands
import database as db
from utils.make_embed import success, error, info
from utils.format_tag import format_tag
from utils.helpers import check_ban
import logging
from discord.ui import View, Button
from PIL import ImageFilter
from PIL import Image
from ocr_utils import preprocess_image_for_ocr, extract_nicktags, find_best_nicktag
import requests
import asyncio
from io import BytesIO
import re
from datetime import datetime, timezone, timedelta
import pytesseract
from discord import SelectOption
from discord.interactions import Interaction
import discord
from discord import Embed, Color
import sqlite3

logger = logging.getLogger('bot')

class OfferView(discord.ui.View):
    def __init__(self, offer_id, manager_id, guild_id, is_clause_payment=False):
        super().__init__(timeout=None)
        self.offer_id = offer_id
        self.manager_id = manager_id
        self.guild_id = guild_id
        self.is_clause_payment = is_clause_payment

    @ui.button(label="✅ Aceptar", style=discord.ButtonStyle.green)
    async def accept(self, interaction: discord.Interaction, button: ui.Button):
        if await check_ban(interaction, interaction.user.id, self.guild_id):
            return
        
        offer = db.get_offer(self.guild_id, self.offer_id)
        if not offer or offer['status'] not in ['pending', 'bought_clause']:
            await interaction.response.edit_message(embed=error("Oferta no válida o ya procesada."), view=None)
            return
        
        # Verificar que el usuario que acepta es el jugador objetivo
        player = db.get_player_by_id(self.guild_id, interaction.user.id)
        if not player or player['name'] != offer['player_name']:
            await interaction.response.edit_message(embed=error("No eres el jugador objetivo de esta oferta."), view=None)
            return
        
        if self.is_clause_payment:
            if db.accept_clause_payment(self.guild_id, self.offer_id):
                await interaction.response.edit_message(embed=success("Transferencia por cláusula aceptada."), view=None)
                manager = interaction.client.get_user(self.manager_id)
                if manager:
                    try:
                        await manager.send(embed=info(f"El jugador {player['name']} aceptó la transferencia por cláusula #{self.offer_id}."))
                    except discord.Forbidden:
                        logger.warning(f"No se pudo notificar al manager {self.manager_id}: DMs cerrados.")
            else:
                await interaction.response.edit_message(embed=error("Fondos insuficientes."), view=None)
        else:
            if db.accept_offer(self.guild_id, self.offer_id):
                await interaction.response.edit_message(embed=success("Oferta aceptada."), view=None)
                manager = interaction.client.get_user(self.manager_id)
                if manager:
                    try:
                        await manager.send(embed=info(f"El jugador {player['name']} aceptó la oferta #{self.offer_id}."))
                    except discord.Forbidden:
                        logger.warning(f"No se pudo notificar al manager {self.manager_id}: DMs cerrados.")
            else:
                await interaction.response.edit_message(embed=error("Error al aceptar la oferta."), view=None)

    @ui.button(label="❌ Rechazar", style=discord.ButtonStyle.red)
    async def reject(self, interaction: discord.Interaction, button: ui.Button):
        if await check_ban(interaction, interaction.user.id, self.guild_id):
            return
        
        offer = db.get_offer(self.guild_id, self.offer_id)
        if not offer or offer['status'] not in ['pending', 'bought_clause']:
            await interaction.response.edit_message(embed=error("Oferta no válida o ya procesada."), view=None)
            return
        
        db.reject_offer(self.guild_id, self.offer_id)
        await interaction.response.edit_message(embed=info("Oferta rechazada."), view=None)
        manager = interaction.client.get_user(self.manager_id)
        if manager:
            try:
                await manager.send(embed=info(f"El jugador {interaction.user.name} rechazó la oferta #{self.offer_id}."))
            except discord.Forbidden:
                logger.warning(f"No se pudo notificar al manager {self.manager_id}: DMs cerrados.")

    async def on_timeout(self):
        try:
            await self.message.edit(view=None)
        except:
            pass

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: ui.Item):
        logger.error(f'Error en OfferView: {error}', exc_info=True)
        await interaction.response.send_message(embed=error("Ocurrió un error."), ephemeral=True)

class ConfirmAmistosoView(ui.View):
    def __init__(self, solicitud_id, bot, guild_id, cog):
        super().__init__(timeout=None)
        self.solicitud_id = solicitud_id
        self.bot = bot
        self.guild_id = guild_id
        self.cog = cog

    @ui.button(label="✅ Aceptar", style=discord.ButtonStyle.green)
    async def accept(self, interaction: discord.Interaction, button: ui.Button):
        solicitud = db.get_solicitud_by_id(self.guild_id, self.solicitud_id)
        if not solicitud or solicitud['status'] != 'pending':
            await interaction.response.send_message(embed=error("Solicitud no válida o ya procesada."), ephemeral=True)
            return
        team = db.get_team_by_manager(self.guild_id, interaction.user.id) or db.get_team_by_captain(self.guild_id, interaction.user.id)
        if not team or team['id'] != solicitud['solicitado_team_id']:
            await interaction.response.send_message(embed=error("No eres el manager ni capitán del equipo solicitado."), ephemeral=True)
            return

        amistosos = db.get_amistosos_for_tabla(self.guild_id, solicitud['tabla_id'])
        if any(a['horario'] == solicitud['horario'] and (a['team1_id'] in [solicitud['solicitante_team_id'], solicitud['solicitado_team_id']] or a['team2_id'] in [solicitud['solicitante_team_id'], solicitud['solicitado_team_id']]) for a in amistosos):
            await interaction.response.send_message(embed=error("Uno de los equipos ya tiene un amistoso en ese horario."), ephemeral=True)
            return

        db.update_solicitud_status(self.guild_id, self.solicitud_id, 'accepted', interaction.user.id)
        db.add_amistoso(self.guild_id, solicitud['solicitante_team_id'], solicitud['solicitado_team_id'], solicitud['horario'], solicitud['tabla_id'])

        solicitante_team = db.get_team_by_id(self.guild_id, solicitud['solicitante_team_id'])
        solicitado_team = db.get_team_by_id(self.guild_id, solicitud['solicitado_team_id'])
        embed = success(f"Amistoso programado: {solicitante_team['name']} vs {solicitado_team['name']} a las {solicitud['horario']}")
        
        solicitante_manager = self.bot.get_user(solicitante_team['manager_id'])
        if solicitante_manager:
            try:
                await solicitante_manager.send(embed=embed)
            except discord.HTTPException:
                pass
        
        config = db.get_server_config(self.guild_id)
        if config and config['amistosos_channel_id']:
            channel = self.bot.get_channel(config['amistosos_channel_id'])
            if channel:
                await channel.send(embed=embed)

        await interaction.response.send_message(embed=success("Amistoso aceptado y programado."), ephemeral=True)

        if config and config['amistosos_channel_id']:
            channel = self.bot.get_channel(config['amistosos_channel_id'])
            if channel and self.cog.amistosos_message_id:
                tabla = db.get_latest_amistosos_tabla(self.guild_id)
                if tabla:
                    tabla_texto = self.cog.generate_amistosos_table(self.guild_id, tabla['id'])
                else:
                    tabla_texto = "No hay tabla activa."
                try:
                    message = await channel.fetch_message(self.cog.amistosos_message_id)
                    await message.edit(content=tabla_texto)
                except discord.NotFound:
                    self.cog.amistosos_message_id = None

    @ui.button(label="❌ Rechazar", style=discord.ButtonStyle.red)
    async def reject(self, interaction: discord.Interaction, button: ui.Button):
        solicitud = db.get_solicitud_by_id(self.guild_id, self.solicitud_id)
        if not solicitud or solicitud['status'] != 'pending':
            await interaction.response.send_message(embed=error("Solicitud no válida o ya procesada."), ephemeral=True)
            return
        team = db.get_team_by_manager(self.guild_id, interaction.user.id) or db.get_team_by_captain(self.guild_id, interaction.user.id)
        if not team or team['id'] != solicitud['solicitado_team_id']:
            await interaction.response.send_message(embed=error("No eres el manager ni capitán del equipo solicitado."), ephemeral=True)
            return

        db.update_solicitud_status(self.guild_id, self.solicitud_id, 'rejected', interaction.user.id)

        solicitante_team = db.get_team_by_id(self.guild_id, solicitud['solicitante_team_id'])
        solicitado_team = db.get_team_by_id(self.guild_id, solicitud['solicitado_team_id'])
        embed = error(f"Solicitud de amistoso rechazada: {solicitante_team['name']} vs {solicitado_team['name']} a las {solicitud['horario']}")
        
        solicitante_manager = self.bot.get_user(solicitante_team['manager_id'])
        if solicitante_manager:
            try:
                await solicitante_manager.send(embed=embed)
            except discord.HTTPException:
                pass

        await interaction.response.send_message(embed=success("Solicitud de amistoso rechazada."), ephemeral=True)

class TeamBookView(ui.View):
    def __init__(self, teams: list, user_id: int, bot: commands.Bot, guild_id: int):
        super().__init__(timeout=300)
        self.teams = teams
        self.user_id = user_id
        self.bot = bot
        self.guild_id = guild_id
        self.current_page = 0

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id

    def get_embed(self) -> discord.Embed:
        if self.current_page == 0:
            embed = info("Equipos Registrados")
            if not self.teams:
                embed.description = "No hay equipos registrados."
                return embed
            embed.description = "\n".join(
                [f"- {team['name']} (División {team['division']})" for team in self.teams])
            return embed
        else:
            team = self.teams[self.current_page - 1]
            embed = info(f"Equipo: {team['name']} (División {team['division']})")
            manager = self.bot.get_user(
                team['manager_id']) if team['manager_id'] else None
            embed.add_field(
                name="Manager", value=manager.mention if manager else "Sin manager", inline=False)
            captains = db.get_captains(self.guild_id, team['id'])
            captain_mentions = [self.bot.get_user(
                c).mention for c in captains if self.bot.get_user(c)]
            embed.add_field(name="Capitanes", value=", ".join(
                captain_mentions) or "Sin capitanes", inline=False)
            players = db.get_players_by_team(self.guild_id, team['id'])
            embed.add_field(name="Jugadores", value="\n".join(
                [f"{p['name']}: {p['contract_duration'] or 'Sin contrato'}" for p in players]) or "Ninguno", inline=False)
            embed.set_footer(
                text=f"Página {self.current_page} de {len(self.teams)}")
            return embed

    @ui.button(label="🏠", style=discord.ButtonStyle.grey)
    async def home_button(self, interaction: discord.Interaction, button: ui.Button):
        self.current_page = 0
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @ui.button(label="⬅️", style=discord.ButtonStyle.blurple)
    async def prev_button(self, interaction: discord.Interaction, button: ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @ui.button(label="➡️", style=discord.ButtonStyle.blurple)
    async def next_button(self, interaction: discord.Interaction, button: ui.Button):
        if self.current_page < len(self.teams):
            self.current_page += 1
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def on_timeout(self):
        try:
            await self.message.edit(view=None)
        except:
            pass

class EliminarAmistosoView(ui.View):
    def __init__(self, amistosos, bot, guild_id: int):
        super().__init__(timeout=60)
        self.bot = bot
        self.guild_id = guild_id
        self.add_item(EliminarAmistosoSelect(amistosos, bot, guild_id))

class EliminarAmistosoSelect(ui.Select):
    def __init__(self, amistosos, bot, guild_id: int):
        self.bot = bot
        self.guild_id = guild_id
        options = [
            SelectOption(
                label=f"{db.get_team_by_id(self.guild_id, a['team1_id'])['name']} vs {db.get_team_by_id(self.guild_id, a['team2_id'])['name']} ({a['horario']})",
                value=str(a['id'])
            ) for a in amistosos
        ]
        if not options:
            options = [SelectOption(label="No hay amistosos para eliminar", value="none")]
        super().__init__(placeholder="Selecciona un amistoso para eliminar", options=options)

    async def callback(self, interaction: Interaction):
        if self.values[0] == "none":
            await interaction.response.send_message(embed=error("No hay amistosos disponibles para eliminar."), ephemeral=True)
            return

        amistoso_id = int(self.values[0])
        amistoso = next((a for a in db.get_amistosos_for_tabla(self.guild_id, db.get_latest_amistosos_tabla(self.guild_id)['id']) if a['id'] == amistoso_id), None)
        if not amistoso:
            await interaction.response.send_message(embed=error("Amistoso no encontrado."), ephemeral=True)
            return

        manager_team = db.get_team_by_manager(self.guild_id, interaction.user.id)
        captain_team = db.get_team_by_captain(self.guild_id, interaction.user.id)
        team = manager_team or captain_team
        if not team or (team['id'] != amistoso['team1_id'] and team['id'] != amistoso['team2_id']):
            await interaction.response.send_message(embed=error("No eres manager ni capitán de los equipos involucrados."), ephemeral=True)
            return

        db.delete_amistoso(self.guild_id, amistoso_id)
        logger.info(f"Amistoso ID {amistoso_id} eliminado por {interaction.user.name} ({interaction.user.id})")

        team1 = db.get_team_by_id(self.guild_id, amistoso['team1_id'])
        team2 = db.get_team_by_id(self.guild_id, amistoso['team2_id'])
        recipients = []
        for t in [team1, team2]:
            manager_id = t['manager_id']
            captains = db.get_captains(self.guild_id, t['id'])
            if manager_id:
                recipients.append(manager_id)
            recipients.extend(captains)

        for recipient_id in set(recipients):
            if recipient_id != interaction.user.id:
                recipient = self.bot.get_user(recipient_id)
                if recipient:
                    try:
                        await recipient.send(embed=info(f"El amistoso entre {team1['name']} y {team2['name']} en el horario {amistoso['horario']} fue eliminado por {interaction.user.name} en el servidor {interaction.guild.name}."))
                        logger.info(f"Notificación de eliminación enviada a {recipient.name} ({recipient_id})")
                    except discord.Forbidden:
                        logger.warning(f"No se pudo notificar a {recipient.name} ({recipient_id}) - DMs desactivados")
                    except discord.HTTPException as e:
                        logger.error(f"Error HTTP al notificar a {recipient.name} ({recipient_id}): {e}")

        tabla = db.get_latest_amistosos_tabla(self.guild_id)
        if tabla:
            table = self.bot.cogs['LeagueCog'].generate_amistosos_table(self.guild_id, tabla['id'])
        else:
            table = "No hay tabla activa."

        config = db.get_server_config(self.guild_id)
        if config and config['amistosos_channel_id']:
            channel = self.bot.get_channel(config['amistosos_channel_id'])
            if channel and self.bot.cogs['LeagueCog'].amistosos_message_id:
                try:
                    message = await channel.fetch_message(self.bot.cogs['LeagueCog'].amistosos_message_id)
                    await message.edit(content=table)
                except discord.NotFound:
                    logger.warning(f"Mensaje {self.bot.cogs['LeagueCog'].amistosos_message_id} no encontrado para actualizar tabla de amistosos")
                except discord.Forbidden:
                    logger.error(f"Permisos insuficientes para editar mensaje en canal {config['amistosos_channel_id']}")

        await interaction.response.send_message(embed=success("Amistoso eliminado correctamente."), ephemeral=True)

class PaginationView(View):
    def __init__(self, players, items_per_page=10):
        super().__init__(timeout=300)
        self.players = players
        self.items_per_page = items_per_page
        self.current_page = 0
        self.total_pages = (
            len(players) + items_per_page - 1) // items_per_page

        self.prev_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page >= self.total_pages - 1

    async def update_embed(self, interaction: discord.Interaction):
        start = self.current_page * self.items_per_page
        end = start + self.items_per_page
        page_players = self.players[start:end]

        embed = info("Agentes Libres")
        if not page_players:
            embed.description = "No hay agentes libres disponibles."
        else:
            player_list = []
            for player in page_players:
                player_info = f"**{player['name']}** (ID: {player['user_id']})"
                if player['contract_duration']:
                    player_info += f"\nDuración contrato: {player['contract_duration']} meses"
                if player['release_clause']:
                    player_info += f"\nCláusula: {player['release_clause']:,}"
                player_list.append(player_info)
            embed.description = "\n\n".join(player_list)
            embed.set_footer(
                text=f"Página {self.current_page + 1} de {self.total_pages}")

        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="⬅️", style=discord.ButtonStyle.blurple)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            self.prev_button.disabled = self.current_page == 0
            self.next_button.disabled = self.current_page >= self.total_pages - 1
            await self.update_embed(interaction)

    @discord.ui.button(label="➡️", style=discord.ButtonStyle.blurple)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            self.prev_button.disabled = self.current_page == 0
            self.next_button.disabled = self.current_page >= self.total_pages - 1
            await self.update_embed(interaction)

class ReviewView(ui.View):
    def __init__(self, screenshot_id: int, guild_id: int):
        super().__init__(timeout=None)
        self.screenshot_id = screenshot_id
        self.guild_id = guild_id

    async def check_arbiter(self, interaction: discord.Interaction):
        config = db.get_server_config(self.guild_id)
        if not config or not config['arbiter_role_id']:
            return False
        arbiter_role_id = config['arbiter_role_id']
        return any(role.id == arbiter_role_id for role in interaction.user.roles)

    @ui.button(label="✅ Aceptar", style=discord.ButtonStyle.green)
    async def accept(self, interaction: discord.Interaction, button: ui.Button):
        if not await self.check_arbiter(interaction):
            await interaction.response.send_message(embed=error("Solo los árbitros pueden revisar capturas."), ephemeral=True)
            return
        db.update_screenshot_status(self.guild_id, self.screenshot_id, 'accepted')
        await interaction.response.edit_message(embed=success(f"Captura #{self.screenshot_id} aceptada."), view=None)

    @ui.button(label="❌ Rechazar", style=discord.ButtonStyle.red)
    async def reject(self, interaction: discord.Interaction, button: ui.Button):
        if not await self.check_arbiter(interaction):
            await interaction.response.send_message(embed=error("Solo los árbitros pueden revisar capturas."), ephemeral=True)
            return
        db.update_screenshot_status(self.guild_id, self.screenshot_id, 'rejected')
        await interaction.response.edit_message(embed=success(f"Captura #{self.screenshot_id} rechazada."), view=None)

class LeagueCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.tz_minus_3 = timezone(timedelta(hours=-3))
        self.amistosos_message_id = None

    def generate_amistosos_table(self, guild_id: int, tabla_id: int) -> str:
        horarios = db.get_horarios_for_tabla(tabla_id, guild_id)
        amistosos = db.get_amistosos_for_tabla(guild_id, tabla_id)
        partidos_por_horario = {h['horario']: "Disponible" if h['disponible'] else "Ocupado" for h in horarios}
        for amistoso in amistosos:
            team1 = db.get_team_by_id(guild_id, amistoso['team1_id'])
            team2 = db.get_team_by_id(guild_id, amistoso['team2_id'])
            if team1 and team2:
                partidos_por_horario[amistoso['horario']] = f"**{team1['name']} vs {team2['name']}** ⚽"
        table = f"```\n📅 Tabla de Amistosos (ID: {tabla_id}) 📅\n⚽ Horario | Partido ⚽\n{'═'*30}\n"
        for horario in [h['horario'] for h in horarios]:
            partido = partidos_por_horario[horario]
            table += f"⚪ {horario} | {partido} 🟢\n" if partido == "Disponible" else f"🏟️ {horario} | {partido}\n"
        table += "```\n"
        return table

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            logger.debug("Ignorando mensaje de un bot.")
            return

        config = db.get_server_config(message.guild.id)
        if not config or not config.get('ss_channel_ids', []) or message.channel.id not in config['ss_channel_ids']:
            return

        if not config['arbiter_role_id']:
            logger.warning(f"No se encontró rol de árbitro configurado en guild {message.guild.id}")
            return

        if not message.attachments:
            logger.debug(f"Mensaje en {message.channel.id} sin adjuntos, ignorado.")
            return

        await asyncio.sleep(1)
        logger.info(f"Mensaje recibido en canal {message.channel.id} por {message.author} con adjuntos: {message.attachments}")

        attachment = message.attachments[0]
        if not attachment.filename.lower().endswith(('.png', '.jpg', '.jpeg')):
            await message.reply(embed=error("Por favor, envía una imagen en formato PNG o JPG."))
            return

        guild_id = message.guild.id
        user_id = message.author.id
        player = db.get_player_by_id(guild_id, user_id)

        if not player:
            team = db.get_team_by_manager(guild_id, user_id)
            if team:
                db_path = db.get_db_path(guild_id)
                with sqlite3.connect(db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    cur = conn.cursor()
                    cur.execute('SELECT * FROM players WHERE team_id = ? AND user_id = ?', (team['id'], user_id))
                    player = cur.fetchone()

        if not player:
            return  # no es jugador 

        try:
            response = requests.get(attachment.url)
            response.raise_for_status()
            img = Image.open(BytesIO(response.content))
            img = preprocess_image_for_ocr(img)
        except Exception as e:
            logger.error(f"Error al procesar la imagen: {e}")
            await message.reply(embed=error("Error al procesar la imagen. Intenta de nuevo."))
            return

        try:
            text = pytesseract.image_to_string(img, lang='eng')
            logger.debug(f"Texto extraído por OCR: {text}")
            text = text.replace('O', '0').replace('I', '1').replace('l', '1')
        except Exception as e:
            logger.error(f"Error en OCR: {e}")
            await message.reply(embed=error("Error al procesar la imagen con OCR. Intenta de nuevo."))
            return

        nicktags = extract_nicktags(text)
        discord_name = message.author.name
        discord_display = message.author.display_name
        nicktag = find_best_nicktag(nicktags, discord_name, discord_display)

        time_pattern = re.compile(r'\b([01]?\d|2[0-3])[:.][0-5]\d\b')
        time_match = time_pattern.search(text)
        screenshot_time = time_match.group(0).replace('.', ':') if time_match else None

        review_channel_id = config['ss_channel_ids'][0]
        review_channel = self.bot.get_channel(review_channel_id)
        arbiter_role = message.guild.get_role(config['arbiter_role_id'])
        if not review_channel or not arbiter_role:
            logger.error(f"Canal de revisión {review_channel_id} o rol {config['arbiter_role_id']} no encontrado.")
            await message.reply(embed=error("Error interno: canal o rol no encontrado. Contacta a un admin."))
            return

        screenshot_id = db.add_screenshot(
            message.guild.id,
            message.author.id,
            nicktag or "No detectado",
            discord_name,
            message.channel.id,
            attachment.url,
            screenshot_time
        )

        if nicktag and screenshot_time:
            db.update_screenshot_status(message.guild.id, screenshot_id, 'accepted')
            await message.reply(embed=success(f"Captura validada correctamente. NICKTAG: {nicktag}, Hora: {screenshot_time}"))
        else:
            embed = info(f"Captura dudosa #{screenshot_id} de {discord_name}")
            embed.add_field(name="NICKTAG detectado", value=nicktag or "No detectado", inline=False)
            embed.add_field(name="Nombre Discord", value=discord_name, inline=False)
            embed.add_field(name="Hora detectada", value=screenshot_time or "No detectada", inline=False)
            embed.set_image(url=attachment.url)
            view = ReviewView(screenshot_id, message.guild.id)
            await review_channel.send(content=f"{arbiter_role.mention}", embed=embed, view=view)
            await message.reply(embed=error("Captura enviada a revisión: datos incompletos."))

        await self.bot.process_commands(message)

    @app_commands.command(name="set_registro_channel", description="Establece el canal para registros de jugadores (solo admin)")
    @app_commands.describe(canal="Canal para registros")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_registro_channel(self, interaction: discord.Interaction, canal: discord.TextChannel):
        db.set_registro_channel(interaction.guild.id, canal.id)
        await interaction.response.send_message(embed=success(f"Canal de registros establecido a {canal.mention}."), ephemeral=True)
    
    @app_commands.command(name="test_command", description="Comando de prueba para verificar sincronización")
    async def test_command(self, interaction: discord.Interaction):
        await interaction.response.send_message("¡Comando de prueba funcionando!", ephemeral=True)

    @app_commands.command(name="check_market", description="Verifica el estado del mercado")
    async def check_market(self, interaction: discord.Interaction):
        status = db.get_market_status(interaction.guild.id)
        await interaction.response.send_message(f"El mercado está {status}.", ephemeral=True)

    @app_commands.command(name="ss", description="Ver historial de capturas")
    @app_commands.describe(jugador="Jugador objetivo (opcional)")
    async def ss(self, interaction: discord.Interaction, jugador: discord.User = None):
        if jugador and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(embed=error("Solo los administradores pueden ver el historial de otros usuarios."), ephemeral=True)
            return

        user_id = jugador.id if jugador else interaction.user.id
        screenshots = db.get_screenshots_by_user(interaction.guild.id, user_id)
        if not screenshots:
            await interaction.response.send_message(embed=info("No hay capturas registradas."), ephemeral=True)
            return

        embed = info(f"Historial de capturas de {jugador.name if jugador else interaction.user.name}")
        for ss in screenshots[:10]:
            channel = self.bot.get_channel(ss['channel_id'])
            channel_name = f"#{channel.name}" if channel else "Canal no encontrado"
            value = f"NICKTAG: {ss['nicktag']}\nCanal: {channel_name}"
            embed.add_field(
                name=f"Captura {ss['id']}",
                value=value,
                inline=False
            )
        embed.set_footer(text=f"Total: {len(screenshots)} capturas")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="set_screenshot_settings",
        description="Configura los canales y el rol para capturas (solo admin)"
    )
    @app_commands.describe(
        canales="Menciona los canales para capturas (ejemplo: #canal1,#canal2 sin espacios)",
        rol="Rol de árbitro (no puede ser @everyone)"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def set_screenshot_settings(self, interaction: discord.Interaction, canales: str, rol: discord.Role):
        channel_mentions = [name.strip() for name in canales.replace(' ', '').split(',')]
        channel_ids = []

        if rol == interaction.guild.default_role:
            await interaction.response.send_message(
                embed=error("El rol no puede ser @everyone. Selecciona un rol específico."),
                ephemeral=True
            )
            return

        for mention in channel_mentions:
            match = re.match(r'^<#(\d+)>$', mention)
            if not match:
                await interaction.response.send_message(
                    embed=error(f"Formato inválido en '{mention}'. Usa menciones como #canal1,#canal2 sin espacios."),
                    ephemeral=True
                )
                return
            clean_id = match.group(1)
            channel = interaction.guild.get_channel(int(clean_id))
            if not isinstance(channel, discord.TextChannel):
                await interaction.response.send_message(
                    embed=error(f"Mención inválida: {mention} no es un canal de texto."),
                    ephemeral=True
                )
                return
            channel_ids.append(channel.id)

        if not channel_ids:
            await interaction.response.send_message(
                embed=error("No se encontraron canales válidos."),
                ephemeral=True
            )
            return

        ss_channel_ids_str = ','.join(map(str, channel_ids))
        db.set_server_settings(interaction.guild.id, ss_channel_ids_str, rol.id)

        channel_mentions_str = ', '.join([f'<#{id}>' for id in channel_ids])
        await interaction.response.send_message(
            embed=success(f"Canales configurados: {channel_mentions_str}, rol: {rol.mention}"),
            ephemeral=True
        )
    
    @app_commands.command(name="asignarcanalamistosos", description="Asignar el canal para tablas de amistosos (solo admin)")
    @app_commands.describe(canal="Canal para tablas de amistosos")
    @app_commands.checks.has_permissions(administrator=True)
    async def asignarcanalamistosos(self, interaction: discord.Interaction, canal: discord.TextChannel):
        db.set_amistosos_channel(interaction.guild.id, canal.id)
        await interaction.response.send_message(embed=success(f"Canal de tablas de amistosos establecido a {canal.mention}."), ephemeral=True)
    
    @app_commands.command(name="crearequipo", description="Crear un equipo nuevo")
    @app_commands.describe(nombre="Nombre del equipo", division="División del equipo")
    @app_commands.checks.has_permissions(administrator=True)
    async def crearequipo(self, interaction: discord.Interaction, nombre: str, division: str):
        if db.add_team(interaction.guild.id, nombre, division):
            await interaction.response.send_message(embed=success(f"Equipo {nombre} creado en división {division}."), ephemeral=True)
        else:
            await interaction.response.send_message(embed=error("El equipo ya existe o el manager ya está asignado a otro equipo."), ephemeral=True)

    @app_commands.command(name="asignarmanager", description="Asignar un manager a un equipo")
    @app_commands.describe(equipo="Nombre del equipo", manager="Usuario a asignar")
    @app_commands.checks.has_permissions(administrator=True)
    async def asignarmanager(self, interaction: discord.Interaction, equipo: str, manager: discord.User):
        team = db.get_team_by_name(interaction.guild.id, equipo)
        if not team:
            await interaction.response.send_message(embed=error("Equipo no encontrado."), ephemeral=True)
            return
        if team and team['manager_id'] is not None:
            await interaction.response.send_message(embed=error("El equipo ya tiene un manager."), ephemeral=True)
            return
        if db.get_team_by_manager(interaction.guild.id, manager.id):
            await interaction.response.send_message(embed=error("El usuario ya es manager de otro equipo."), ephemeral=True)
            return
        db.assign_manager_to_team(interaction.guild.id, team['id'], manager.id)
        await interaction.response.send_message(embed=success(f"{manager.name} asignado como manager de {equipo}."))

    @app_commands.command(name="registrarjugador", description="Regístrate como jugador en la liga")
    async def registrarjugador(self, interaction: discord.Interaction):
        user = interaction.user
        
        config = db.get_server_config(interaction.guild.id)
        if config and 'registro_channel_id' in config and interaction.channel_id != config['registro_channel_id']:
            await interaction.response.send_message(embed=error("Este comando solo puede usarse en el canal de registros."), ephemeral=True)
            return
    
        if db.get_team_by_manager(interaction.guild.id, user.id):
            await interaction.response.send_message(embed=error(f"{user.name} es manager y no puede ser jugador."), ephemeral=True)
            return
    
        existing_player = db.get_player_by_id(interaction.guild.id, user.id)
        if existing_player:
            await interaction.response.send_message(embed=error(f"{user.name} ya está registrado como {existing_player['name']}."),
                                                    ephemeral=True)
            return
    
        if db.add_player(interaction.guild.id, user.name, user.id):
            await interaction.response.send_message(embed=success(f"{user.name} registrado como jugador."), ephemeral=True)
        else:
            await interaction.response.send_message(embed=error("Error al registrarte. Contacta a un administrador."), ephemeral=True)

    @app_commands.command(name="agenteslibres", description="Mostrar la lista de agentes libres")
    async def agenteslibres(self, interaction: discord.Interaction):
        players = db.get_free_agents(interaction.guild.id)
        if not players:
            await interaction.response.send_message(embed=error("No hay agentes libres disponibles."), ephemeral=True)
            return

        view = PaginationView(players, items_per_page=10)
        embed = info("Agentes Libres")
        player_list = []
        for player in players[:10]:
            player_info = f"**{player['name']}** (ID: {player['user_id']})"
            if player['contract_duration']:
                player_info += f"\nDuración contrato: {player['contract_duration']} meses"
            if player['release_clause']:
                player_info += f"\nCláusula: {player['release_clause']:,}"
            player_list.append(player_info)
        embed.description = "\n\n".join(player_list)
        embed.set_footer(text=f"Página 1 de {(len(players) + 9) // 10}")

        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="agregarcapitan", description="Agregar un capitán a un equipo")
    @app_commands.describe(equipo="Nombre del equipo", jugador="Jugador a agregar como capitán")
    @app_commands.checks.has_permissions(administrator=True)
    async def agregarcapitan(self, interaction: discord.Interaction, equipo: str, jugador: discord.User):
        team = db.get_team_by_name(interaction.guild.id, equipo)
        if not team:
            await interaction.response.send_message(embed=error("Equipo no encontrado."), ephemeral=True)
            return
        player = db.get_player_by_id(interaction.guild.id, jugador.id)
        if not player:
            await interaction.response.send_message(embed=error("Jugador no encontrado."), ephemeral=True)
            return
        if db.add_captain(interaction.guild.id, team['id'], jugador.id):
            await interaction.response.send_message(embed=success(f"{jugador.name} agregado como capitán de {equipo}."), ephemeral=True)
        else:
            await interaction.response.send_message(embed=error("El jugador ya es capitán o error al agregar."), ephemeral=True)

    @app_commands.command(name="quitarcapitan", description="Quitar un capitán de un equipo")
    @app_commands.describe(equipo="Nombre del equipo", jugador="Jugador a quitar como capitán")
    @app_commands.checks.has_permissions(administrator=True)
    async def quitarcapitan(self, interaction: discord.Interaction, equipo: str, jugador: discord.User):
        team = db.get_team_by_name(interaction.guild.id, equipo)
        if not team:
            await interaction.response.send_message(embed=error("Equipo no encontrado."), ephemeral=True)
            return
        if db.remove_captain(interaction.guild.id, team['id'], jugador.id):
            await interaction.response.send_message(embed=success(f"{jugador.name} removido como capitán de {equipo}."), ephemeral=True)
        else:
            await interaction.response.send_message(embed=error("El jugador no es capitán o error al quitar."), ephemeral=True)

    @app_commands.command(name="ofertarcontrato", description="Enviar una oferta de contrato a un jugador")
    @app_commands.describe(jugador="Jugador objetivo", clausula="Cláusula de rescisión", duracion="Duración en meses")
    async def ofertarcontrato(self, interaction: discord.Interaction, jugador: discord.Member, clausula: int, duracion: int):
        if await check_ban(interaction, jugador.id, interaction.guild.id):
            return

        manager_team = db.get_team_by_manager(interaction.guild.id, interaction.user.id)
        if not manager_team:
            await interaction.response.send_message(embed=error("No eres manager de ningún equipo."), ephemeral=True)
            return

        if clausula <= 0 or duracion <= 0:
            await interaction.response.send_message(embed=error("Cláusula y duración deben ser positivas."), ephemeral=True)
            return

        player = db.get_player_by_id(interaction.guild.id, jugador.id)
        if not player:
            await interaction.response.send_message(embed=error(f"{jugador.name} no está registrado como jugador."), ephemeral=True)
            return

        if db.has_pending_offer(interaction.guild.id, interaction.user.id, jugador.id):
            await interaction.response.send_message(embed=error("Ya existe una oferta pendiente para este jugador."), ephemeral=True)
            return

        offer_id = db.create_transfer_offer(
            interaction.guild.id,
            player['name'],
            None if not player['team_id'] else player['team_id'],
            manager_team['id'],
            interaction.user.id,
            clausula,
            duracion,
            clausula
        )
        if offer_id == -1:
            logger.error(f"Falló la creación de la oferta para {player['name']} en guild {interaction.guild.id}.")
            await interaction.response.send_message(embed=error("Error al crear la oferta."), ephemeral=True)
            return
        elif offer_id == -2:
            await interaction.response.send_message(embed=error("El mercado está cerrado."), ephemeral=True)
            return

        view = OfferView(offer_id, interaction.user.id, interaction.guild.id)
        try:
            await jugador.send(embed=info(f"Oferta de {format_tag(interaction.user)}:\n**Cláusula:** {clausula:,}\n**Duración:** {duracion} meses\nID: {offer_id}"), view=view)
            await interaction.response.send_message(embed=success(f"Oferta enviada a {jugador.name}."), ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(embed=error("No puedo enviar DM al jugador."), ephemeral=True)

    @app_commands.command(name="cancelaroferta", description="Cancelar una oferta enviada")
    @app_commands.describe(oferta_id="ID de la oferta")
    async def cancelaroferta(self, interaction: discord.Interaction, oferta_id: int):
        offer = db.get_offer(interaction.guild.id, oferta_id)
        if not offer or offer['from_manager_id'] != interaction.user.id:
            await interaction.response.send_message(embed=error("Oferta no encontrada o no autorizada."), ephemeral=True)
            return
        if offer['status'] not in ['pending', 'bought_clause']:
            await interaction.response.send_message(embed=error("Solo puedes cancelar ofertas pendientes o de cláusula."), ephemeral=True)
            return
        db.update_offer_status(interaction.guild.id, oferta_id, 'cancelled')
        await interaction.response.send_message(embed=success("Oferta cancelada."), ephemeral=True)

    @app_commands.command(name="ofertaspendientes", description="Ver todas las ofertas pendientes")
    async def ofertaspendientes(self, interaction: discord.Interaction):
        player = db.get_player_by_id(interaction.guild.id, interaction.user.id)
        if player and player['banned']:
            await interaction.response.send_message(embed=error("Estás sancionado y no puedes usar este comando."), ephemeral=True)
            return
        sent = db.list_offers_by_manager(interaction.guild.id, interaction.user.id, 'pending') + \
            db.list_offers_by_manager(
                interaction.guild.id, interaction.user.id, 'bought_clause')
        received = db.list_offers_for_player(interaction.guild.id, interaction.user.id, 'pending') + db.list_offers_for_player(
            interaction.guild.id, interaction.user.id, 'bought_clause') if player else []
        embed = info("Ofertas pendientes:")
        if sent:
            embed.add_field(name="Enviadas", value="\n".join(
                [f"ID {o['id']} a {o['player_name']} - Cláusula: {o['release_clause'] or 'N/A':,}, Duración: {o['contract_duration'] or 'N/A'} meses" for o in sent]), inline=False)
        if received:
            embed.add_field(name="Recibidas", value="\n".join(
                [f"ID {o['id']} de {o['from_manager_id']} - Cláusula: {o['release_clause'] or 'N/A':,}, Duración: {o['contract_duration'] or 'N/A'} meses" for o in received]), inline=False)
        if not (sent or received):
            embed.description = "No hay ofertas pendientes."
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="perfil", description="Ver el perfil de un jugador")
    @app_commands.describe(jugador="Jugador objetivo")
    async def perfil(self, interaction: discord.Interaction, jugador: discord.User):
        if await check_ban(interaction, jugador.id, interaction.guild.id):
            return
        player = db.get_player_by_id(interaction.guild.id, jugador.id)
        if not player:
            await interaction.response.send_message(embed=error("Jugador no encontrado."), ephemeral=True)
            return
        team = db.get_team_by_id(
            interaction.guild.id, player['team_id']) if player['team_id'] else None
        embed = info(f"Perfil de {jugador.name}")
        embed.add_field(
            name="Equipo", value=team['name'] if team else "Agente libre", inline=True)
        embed.add_field(
            name="Transferible", value="Sí" if player['transferable'] else "No", inline=True)
        embed.add_field(
            name="Baneado", value="Sí" if player['banned'] else "No", inline=True)
        embed.add_field(
            name="Contrato", value=f"{player['contract_duration']} meses" if player['contract_duration'] else "N/A", inline=True)
        embed.add_field(
            name="Cláusula", value=f"{player['release_clause']:,}" if player['release_clause'] else "N/A", inline=True)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="equipo", description="Ver información de un equipo")
    @app_commands.describe(equipo="Nombre del equipo")
    async def equipo(self, interaction: discord.Interaction, equipo: str):
        team = db.get_team_by_name(interaction.guild.id, equipo)
        if not team:
            await interaction.response.send_message(embed=error("Equipo no encontrado."), ephemeral=True)
            return
        manager = self.bot.get_user(
            team['manager_id']) if team['manager_id'] else None
        embed = info(f"Equipo {team['name']} (División {team['division']})")
        embed.add_field(
            name="Manager", value=manager.mention if manager else "Sin manager", inline=True)
        captains = db.get_captains(interaction.guild.id, team['id'])
        captain_mentions = [self.bot.get_user(
            c).mention for c in captains if self.bot.get_user(c)]
        embed.add_field(name="Capitanes", value=", ".join(
            captain_mentions) or "Sin capitanes", inline=True)
        embed.add_field(
            name="Balance", value=f"{db.get_club_balance(interaction.guild.id, team['id']):,}", inline=True)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="players", description="Ver jugadores de un equipo")
    @app_commands.describe(equipo="Nombre del equipo")
    async def players(self, interaction: discord.Interaction, equipo: str):
        team = db.get_team_by_name(interaction.guild.id, equipo)
        if not team:
            await interaction.response.send_message(embed=error("Equipo no encontrado."), ephemeral=True)
            return
        players = db.get_players_by_team(interaction.guild.id, team['id'])
        embed = info(f"Jugadores de {equipo}")
        embed.description = "\n".join(
            [f"{p['name']}: {p['contract_duration'] or 'Sin contrato'}" for p in players]) or "No hay jugadores."
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="historialjugador", description="Ver historial de transferencias de un jugador")
    @app_commands.describe(jugador="Jugador objetivo")
    async def historialjugador(self, interaction: discord.Interaction, jugador: discord.User):
        if await check_ban(interaction, jugador.id, interaction.guild.id):
            return
        player = db.get_player_by_id(interaction.guild.id, jugador.id)
        if not player:
            await interaction.response.send_message(embed=error("Jugador no encontrado."), ephemeral=True)
            return
        history = db.get_transfer_history_by_player(
            interaction.guild.id, player['name'])
        embed = info(f"Historial de {jugador.name}")
        embed.description = "\n".join(history) or "Sin historial."
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="historialequipo", description="Ver historial de transferencias de un equipo")
    @app_commands.describe(equipo="Nombre del equipo")
    async def historialequipo(self, interaction: discord.Interaction, equipo: str):
        team = db.get_team_by_name(interaction.guild.id, equipo)
        if not team:
            await interaction.response.send_message(embed=error("Equipo no encontrado."), ephemeral=True)
            return
        history = db.get_transfer_history_by_team(
            interaction.guild.id, team['id'])
        embed = info(f"Historial de {equipo}")
        embed.description = "\n".join(history) or "Sin historial."
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="pagarclausula", description="Paga la cláusula de rescisión de un jugador y envía la oferta con duración y nueva cláusula.")
    @app_commands.describe(
        jugador="Nombre exacto del jugador",
        duracion="Duración del contrato en meses",
        clausula="Nueva cláusula del jugador tras ficharlo"
    )
    async def pagarclausula(self, interaction: discord.Interaction, jugador: discord.User, duracion: int, clausula: int):
        if await check_ban(interaction, jugador.id, interaction.guild.id):
            return
        manager_team = db.get_team_by_manager(
            interaction.guild.id, interaction.user.id)
        if not manager_team:
            await interaction.response.send_message(embed=error("No eres manager de ningún equipo."), ephemeral=True)
            return
        player = db.get_player_by_id(interaction.guild.id, jugador.id)
        if not player or not player['release_clause']:
            await interaction.response.send_message(embed=error("El jugador no tiene cláusula."), ephemeral=True)
            return
        if player['team_id'] == manager_team['id']:
            await interaction.response.send_message(embed=error("El jugador ya está en tu equipo."), ephemeral=True)
            return
        offer_id = db.pay_clause_and_transfer(
            guild_id=interaction.guild.id,
            player_name=player['name'],
            to_team_id=manager_team['id'],
            price=player['release_clause'],
            manager_id=interaction.user.id,
            duration=duracion,
            new_clause=clausula
        )
        if offer_id == -1:
            await interaction.response.send_message(embed=error("Fondos insuficientes."), ephemeral=True)
            return
        view = OfferView(offer_id, interaction.user.id, interaction.guild.id, is_clause_payment=True)
        try:
            await jugador.send(embed=info(
            f"Te han comprado por cláusula.\n"
            f"Manager: {format_tag(interaction.user)}\n"
            f"Duración del nuevo contrato: **{duracion} meses**\n"
            f"Nueva cláusula: **{clausula:,}**"
        ), view=view)
            await interaction.response.send_message(embed=success(f"Oferta por cláusula enviada a {jugador.name}."), ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(embed=error("No puedo enviar DM al jugador."), ephemeral=True)

    @app_commands.command(name="creartabla", description="Crear una nueva tabla de amistosos con horarios especificados")
    @app_commands.describe(inicio="Hora de inicio (HH:MM)", fin="Hora de fin (HH:MM)")
    @app_commands.checks.has_permissions(administrator=True)
    async def creartabla(self, interaction: discord.Interaction, inicio: str, fin: str):
        if not re.match(r"^\d{2}:\d{2}$", inicio) or not re.match(r"^\d{2}:\d{2}$", fin):
            await interaction.response.send_message(embed=error("Formato de hora inválido. Debe ser HH:MM."), ephemeral=True)
            return
        tabla_id = db.create_amistosos_tabla(interaction.guild.id, inicio, fin)
        if tabla_id == -1:
            await interaction.response.send_message(embed=error("Error al crear la tabla. Verifica los horarios."), ephemeral=True)
            return
        await interaction.response.send_message(embed=success(f"Tabla de amistosos creada con ID {tabla_id}."), ephemeral=True)

        config = db.get_server_config(interaction.guild.id)
        if config and config['amistosos_channel_id']:
            channel = self.bot.get_channel(config['amistosos_channel_id'])
            if channel:
                table = self.generate_amistosos_table(interaction.guild.id, tabla_id)
                message = await channel.send(table)
                self.amistosos_message_id = message.id

    @app_commands.command(name="registraramistoso", description="Solicitar un amistoso contra otro equipo en un horario específico")
    @app_commands.describe(equipo="Nombre del equipo contrario", horario="Horario del amistoso (HH:MM)")
    async def registraramistoso(self, interaction: discord.Interaction, equipo: str, horario: str):
        await interaction.response.defer(ephemeral=True)

        manager_team = db.get_team_by_manager(interaction.guild.id, interaction.user.id)
        captain_team = db.get_team_by_captain(interaction.guild.id, interaction.user.id)
        team = manager_team or captain_team
        if not team:
            await interaction.followup.send(embed=error("No eres manager ni capitán de ningún equipo."), ephemeral=True)
            return

        tabla = db.get_latest_amistosos_tabla(interaction.guild.id)
        if not tabla:
            await interaction.followup.send(embed=error("No hay una tabla de amistosos activa."), ephemeral=True)
            return

        horarios = db.get_horarios_for_tabla(tabla['id'], interaction.guild.id)
        horario_info = next((h for h in horarios if h['horario'] == horario), None)
        if not horario_info:
            await interaction.followup.send(embed=error(f"El horario {horario} no está en la tabla actual."), ephemeral=True)
            return
        if not horario_info['disponible']:
            await interaction.followup.send(embed=error(f"El horario {horario} ya está ocupado."), ephemeral=True)
            return

        solicitado_team = db.get_team_by_name(interaction.guild.id, equipo)
        if not solicitado_team:
            await interaction.followup.send(embed=error("Equipo no encontrado."), ephemeral=True)
            return
        if solicitado_team['id'] == team['id']:
            await interaction.followup.send(embed=error("No puedes jugar contra tu propio equipo."), ephemeral=True)
            return

        amistosos = db.get_amistosos_for_tabla(interaction.guild.id, tabla['id'])
        if any(a['horario'] == horario and (a['team1_id'] in [team['id'], solicitado_team['id']] or a['team2_id'] in [team['id'], solicitado_team['id']]) for a in amistosos):
            await interaction.followup.send(embed=error("Uno de los equipos ya tiene un amistoso en ese horario."), ephemeral=True)
            return

        solicitud_id = db.add_solicitud_amistoso(interaction.guild.id, team['id'], solicitado_team['id'], horario, tabla['id'], interaction.user.id)
        if solicitud_id == -1:
            await interaction.followup.send(embed=error("Error al registrar la solicitud."), ephemeral=True)
            return

        manager_id = solicitado_team['manager_id']
        captains = db.get_captains(interaction.guild.id, solicitado_team['id'])
        recipients = set([manager_id] + captains) if manager_id else set(captains)
        if not recipients:
            await interaction.followup.send(embed=error("El equipo solicitado no tiene manager ni capitanes."), ephemeral=True)
            return

        failed_dms = []
        for recipient_id in recipients:
            recipient = self.bot.get_user(recipient_id)
            if recipient:
                try:
                    view = ConfirmAmistosoView(solicitud_id, self.bot, interaction.guild.id, self)
                    await recipient.send(embed=info(f"Solicitud de amistoso de {team['name']} para el horario {horario}."), view=view)
                except discord.Forbidden:
                    failed_dms.append(recipient.name)

        if failed_dms:
            await interaction.followup.send(embed=success(f"Solicitud enviada, pero no se pudo notificar a: {', '.join(failed_dms)}."), ephemeral=True)
        else:
            await interaction.followup.send(embed=success("Solicitud de amistoso enviada."), ephemeral=True)

    @app_commands.command(name="quitarmanager", description="Quitar el manager de un equipo")
    @app_commands.describe(equipo="Nombre del equipo")
    @app_commands.checks.has_permissions(administrator=True)
    async def quitarmanager(self, interaction: discord.Interaction, equipo: str):
        # Obtener el equipo por nombre
        team = db.get_team_by_name(interaction.guild.id, equipo)
        if not team:
            await interaction.response.send_message(embed=error("Equipo no encontrado."), ephemeral=True)
            return

        # Verificar si el equipo tiene un manager asignado
        if team['manager_id'] is None:
            await interaction.response.send_message(embed=error("El equipo no tiene un manager asignado."), ephemeral=True)
            return

        # Quitar el manager asignando NULL al manager_id
        db.assign_manager_to_team(interaction.guild.id, team['id'], None)

        # Obtener el nombre del usuario que era manager (si está disponible)
        manager = self.bot.get_user(team['manager_id']) if team['manager_id'] else None
        manager_name = manager.name if manager else "Desconocido"

        # Enviar mensaje de éxito
        await interaction.response.send_message(embed=success(f"{manager_name} ha sido removido como manager de {equipo}."), ephemeral=True)

    @app_commands.command(name="sancionar", description="Sancionar a un jugador")
    @app_commands.describe(jugador="Jugador objetivo")
    @app_commands.checks.has_permissions(administrator=True)
    async def sancionar(self, interaction: discord.Interaction, jugador: discord.User):
        player = db.get_player_by_id(interaction.guild.id, jugador.id)
        if not player:
            await interaction.response.send_message(embed=error("Jugador no encontrado."), ephemeral=True)
            return
        db.ban_player(interaction.guild.id, player['name'])
        await interaction.response.send_message(embed=success(f"{jugador.name} ha sido sancionado."))

    @app_commands.command(name="quitaresancion", description="Quitar sanción a un jugador")
    @app_commands.describe(jugador="Jugador objetivo")
    @app_commands.checks.has_permissions(administrator=True)
    async def quitaresancion(self, interaction: discord.Interaction, jugador: discord.User):
        player = db.get_player_by_id(interaction.guild.id, jugador.id)
        if not player:
            await interaction.response.send_message(embed=error("Jugador no encontrado."), ephemeral=True)
            return
        db.unban_player(interaction.guild.id, player['name'])
        await interaction.response.send_message(embed=success(f"Sanción quitada a {jugador.name}."))

    @app_commands.command(name="quitarjugador", description="Enviar a un jugador a agentes libres")
    @app_commands.describe(jugador="Jugador a remover")
    async def quitarjugador(self, interaction: discord.Interaction, jugador: discord.User):
        player = db.get_player_by_id(interaction.guild.id, jugador.id)
        if not player:
            await interaction.response.send_message(embed=error("Jugador no encontrado."), ephemeral=True)
            return
        if not player['team_id']:
            await interaction.response.send_message(embed=error(f"{jugador.name} ya es agente libre."), ephemeral=True)
            return
        manager_team = db.get_team_by_manager(
            interaction.guild.id, interaction.user.id)
        if not (interaction.user.guild_permissions.administrator or (manager_team and manager_team['id'] == player['team_id'])):
            await interaction.response.send_message(embed=error("Solo admins o el manager del equipo pueden usar este comando."), ephemeral=True)
            return
        db.remove_player_from_team(interaction.guild.id, player['name'])
        await interaction.response.send_message(embed=success(f"{jugador.name} ahora es agente libre."))

    @app_commands.command(name="avanzartemporada", description="Avanzar una temporada")
    @app_commands.checks.has_permissions(administrator=True)
    async def avanzartemporada(self, interaction: discord.Interaction):
        db.advance_season(interaction.guild.id)
        await interaction.response.send_message(embed=success("Temporada avanzada. Contratos reducidos y agentes libres actualizados."), ephemeral=True)

    @app_commands.command(name="equiposregistrados", description="Ver todos los equipos registrados, opcionalmente por división")
    @app_commands.describe(division="División a filtrar (opcional)")
    async def equiposregistrados(self, interaction: discord.Interaction, division: str = None):
        teams = db.get_all_teams(interaction.guild.id, division)
        view = TeamBookView(teams, interaction.user.id, self.bot, interaction.guild.id)
        await interaction.response.send_message(embed=view.get_embed(), view=view)

    @app_commands.command(name="mercado", description="Ver jugadores transferibles")
    async def mercado(self, interaction: discord.Interaction):
        players = db.get_transferable_players(interaction.guild.id)
        if not players:
            await interaction.response.send_message(embed=info("No hay jugadores transferibles."), ephemeral=True)
            return
        embed = info("Jugadores Transferibles")
        for player in players:
            team = db.get_team_by_id(
                interaction.guild.id, player['team_id']) if player['team_id'] else None
            embed.add_field(
                name=player['name'], value=f"Equipo: {team['name'] if team else 'Libre'}\nCláusula: {player['release_clause']:,}", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="agregarmercado", description="Marcar a un jugador como transferible y opcionalmente modificar su cláusula")
    @app_commands.describe(jugador="Jugador a agregar", clausula="Nueva cláusula (opcional)")
    async def agregarmercado(self, interaction: discord.Interaction, jugador: discord.User, clausula: int = None):
        manager_team = db.get_team_by_manager(
            interaction.guild.id, interaction.user.id)
        if not (interaction.user.guild_permissions.administrator or manager_team):
            await interaction.response.send_message(embed=error("Solo admins o managers pueden usar este comando."), ephemeral=True)
            return
        player = db.get_player_by_id(interaction.guild.id, jugador.id)
        if not player:
            await interaction.response.send_message(embed=error("Jugador no encontrado."), ephemeral=True)
            return
        if player['transferable']:
            await interaction.response.send_message(embed=error(f"{jugador.name} ya está en el mercado."), ephemeral=True)
            return
        if not interaction.user.guild_permissions.administrator and manager_team['id'] != player['team_id']:
            await interaction.response.send_message(embed=error("Solo puedes agregar jugadores de tu equipo."), ephemeral=True)
            return
        if clausula is not None and clausula <= 0:
            await interaction.response.send_message(embed=error("La cláusula debe ser un número positivo."), ephemeral=True)
            return
        db.set_player_transferable(
            interaction.guild.id, player['name'], clausula)
        clause_value = clausula if clausula is not None else player['release_clause']
        await interaction.response.send_message(embed=success(f"{jugador.name} agregado al mercado con cláusula {clause_value:,}."))

    @app_commands.command(name="quitarmercado", description="Quitar a un jugador del mercado")
    @app_commands.describe(jugador="Jugador a quitar")
    async def quitarmercado(self, interaction: discord.Interaction, jugador: discord.User):
        manager_team = db.get_team_by_manager(
            interaction.guild.id, interaction.user.id)
        if not (interaction.user.guild_permissions.administrator or manager_team):
            await interaction.response.send_message(embed=error("Solo admins o managers pueden usar este comando."), ephemeral=True)
            return
        player = db.get_player_by_id(interaction.guild.id, jugador.id)
        if not player:
            await interaction.response.send_message(embed=error("Jugador no encontrado."), ephemeral=True)
            return
        if not player['transferable']:
            await interaction.response.send_message(embed=error(f"{jugador.name} no está en el mercado."), ephemeral=True)
            return
        if not interaction.user.guild_permissions.administrator and manager_team['id'] != player['team_id']:
            await interaction.response.send_message(embed=error("Solo puedes quitar jugadores de tu equipo."), ephemeral=True)
            return
        db.unset_player_transferable(interaction.guild.id, player['name'])
        await interaction.response.send_message(embed=success(f"{jugador.name} removido del mercado."))

    @app_commands.command(name="balance", description="Ver el balance de un club")
    @app_commands.describe(equipo="Nombre del equipo")
    async def balance(self, interaction: discord.Interaction, equipo: str):
        team = db.get_team_by_name(interaction.guild.id, equipo)
        if not team:
            await interaction.response.send_message(embed=error("Equipo no encontrado."), ephemeral=True)
            return
        balance = db.get_club_balance(interaction.guild.id, team['id'])
        await interaction.response.send_message(embed=info(f"Balance de {equipo}: {balance:,}"))

    @app_commands.command(name="addmoney", description="Agregar dinero a un club")
    @app_commands.describe(equipo="Nombre del equipo", cantidad="Cantidad a agregar")
    @app_commands.checks.has_permissions(administrator=True)
    async def addmoney(self, interaction: discord.Interaction, equipo: str, cantidad: int):
        team = db.get_team_by_name(interaction.guild.id, equipo)
        if not team:
            await interaction.response.send_message(embed=error("Equipo no encontrado."), ephemeral=True)
            return
        db.add_money_to_club(interaction.guild.id, team['id'], cantidad)
        await interaction.response.send_message(embed=success(f"{cantidad:,} agregado al balance de {equipo}."))

    @app_commands.command(name="removemoney", description="Quitar dinero a un club")
    @app_commands.describe(equipo="Nombre del equipo", cantidad="Cantidad a quitar")
    @app_commands.checks.has_permissions(administrator=True)
    async def removemoney(self, interaction: discord.Interaction, equipo: str, cantidad: int):
        team = db.get_team_by_name(interaction.guild.id, equipo)
        if not team:
            await interaction.response.send_message(embed=error("Equipo no encontrado."), ephemeral=True)
            return
        db.remove_money_from_club(interaction.guild.id, team['id'], cantidad)
        await interaction.response.send_message(embed=success(f"{cantidad:,} quitado del balance de {equipo}."))

    @app_commands.command(name="eliminarequipo", description="Eliminar un equipo y sus datos")
    @app_commands.describe(equipo="Nombre del equipo")
    @app_commands.checks.has_permissions(administrator=True)
    async def eliminarequipo(self, interaction: discord.Interaction, equipo: str):
        team = db.get_team_by_name(interaction.guild.id, equipo)
        if not team:
            await interaction.response.send_message(embed=error("Equipo no encontrado."), ephemeral=True)
            return
        db.delete_team(interaction.guild.id, equipo)
        await interaction.response.send_message(embed=success("Equipo eliminado, todos sus jugadores son agentes libres"), ephemeral=True)

    @app_commands.command(name="fichajes", description="Ver los últimos fichajes realizados en la liga")
    @app_commands.describe(cantidad="Número de fichajes a mostrar (1-25)")
    async def fichajes(self, interaction: discord.Interaction, cantidad: int = 10):
        if cantidad < 1 or cantidad > 25:
            await interaction.response.send_message(embed=error("La cantidad debe estar entre 1 y 25."), ephemeral=True)
            return
        transfers = db.get_recent_transfers(interaction.guild.id, cantidad)
        if not transfers:
            await interaction.response.send_message(embed=info("No hay fichajes recientes."), ephemeral=True)
            return
        embed = info(f"Últimos {len(transfers)} fichajes")
        for transfer in transfers:
            from_team = transfer['from_team_name'] or 'Libre'
            to_team = transfer['to_team_name'] or 'Libre'
            embed.add_field(
                name=f"ID {transfer['id']}", value=f"{transfer['player_name']}: {from_team} → {to_team} por {transfer['price']:,} [{transfer['status']}]", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="help", description="Muestra los comandos disponibles del bot")
    async def help_command(self, interaction: discord.Interaction):
        try:
            embed = Embed(
                title="🧾 Comandos del Bot",
                description="Comandos organizados por categoría para gestionar la liga y amistosos.",
                color=Color.from_rgb(102, 255, 178)
            )
            avatar_url = self.bot.user.avatar.url if self.bot.user.avatar else None
            embed.set_thumbnail(url=avatar_url or discord.utils.MISSING)
            embed.set_footer(text=self.bot.user.name, icon_url=avatar_url or discord.utils.MISSING)

            general_commands = [
                ("help", "Muestra esta lista de comandos."),
                ("amistosos", "Mostrar la tabla de amistosos del día."),
                ("agenteslibres", "Mostrar la lista de agentes libres."),
                ("ofertaspendientes", "Ver todas las ofertas pendientes."),
                ("perfil", "Ver el perfil de un jugador."),
                ("equipo", "Ver información de un equipo."),
                ("players", "Ver jugadores de un equipo."),
                ("historialjugador", "Ver historial de transferencias de un jugador."),
                ("historialequipo", "Ver historial de transferencias de un equipo."),
                ("equiposregistrados", "Ver todos los equipos registrados, opcionalmente por división."),
                ("mercado", "Ver jugadores transferibles."),
                ("balance", "Ver el balance de un club."),
                ("registrarjugador", "Permite a los usuarios registrarse como jugadores."),
            ]
            general_field = "\n".join([f"**`/{cmd}`** - {desc}" for cmd, desc in general_commands])
            embed.add_field(name="📋 General", value=general_field or "Ningún comando disponible.", inline=False)

            manager_commands = [
                ("fichajes", "Ver los últimos fichajes realizados en la liga."),
                ("agregarmercado", "Marcar a un jugador como transferible y opcionalmente modificar su cláusula."),
                ("quitarmercado", "Quitar a un jugador del mercado."),
                ("quitarjugador", "Enviar a un jugador a agentes libres."),
                ("pagaclausula", "Pagar la cláusula de un jugador."),
                ("cancelaroferta", "Cancelar una oferta enviada."),
                ("ofertarcontrato", "Enviar una oferta de contrato a un jugador."),
                ("registraramistoso", "Solicitar un amistoso contra otro equipo. (Managers/Capitanes)"),
                ("eliminaramistoso", "Eliminar un amistoso programado para hoy. (Managers/Capitanes)")
            ]
            manager_field = "\n".join([f"**`/{cmd}`** - {desc}" for cmd, desc in manager_commands])
            embed.add_field(name="⚽ Manager", value=manager_field or "Ningún comando disponible.", inline=False)

            admin_commands = [
                ("open_market", "Abre el mercado de transferencias."),
                ("close_market", "Cierra el mercado de transferencias."),
                ("sync_commands", "Sincroniza los comandos del bot. (Solo Owner)"),
                ("check_market", "Verifica el estado del mercado."),
                ("ss", "Ver historial de capturas validadas."),
                ("crearequipo", "Crear un equipo nuevo con división."),
                ("creartabla", "Generar la tabla diaria de amistosos."),
                ("asignarmanager", "Asignar un manager a un equipo."),
                ("agregarcapitan", "Agregar un capitán a un equipo."),
                ("quitarcapitan", "Quitar un capitán a un equipo."),
                ("resetearamistosos", "Reiniciar la tabla de amistosos."),
                ("sancionar", "Sancionar a un jugador."),
                ("quitaresancion", "Quitar sanción a un jugador."),
                ("avanzartemporada", "Avanzar una temporada."),
                ("addmoney", "Agregar dinero a un club."),
                ("removemoney", "Quitar dinero a un club."),
                ("eliminarequipo", "Eliminar un equipo y sus datos.")
            ]
            current_field = ""
            field_count = 1
            for cmd, desc in admin_commands:
                command_text = f"**`/{cmd}`** - {desc}\n"
                if len(current_field) + len(command_text) > 1024:
                    embed.add_field(
                        name=f"🔧 Admin (Parte {field_count})",
                        value=current_field or "Ningún comando disponible.",
                        inline=False
                    )
                    current_field = command_text
                    field_count += 1
                else:
                    current_field += command_text
            if current_field:
                embed.add_field(
                    name=f"🔧 Admin (Parte {field_count})",
                    value=current_field or "Ningún comando disponible.",
                    inline=False
                )

            total_length = sum(len(field.value) for field in embed.fields) + len(embed.description) + len(embed.title)
            if total_length > 6000:
                await interaction.response.send_message(
                    embed=error("La lista de comandos es demasiado larga para mostrar."),
                    ephemeral=True
                )
                logging.error(f"Embed demasiado largo ({total_length} caracteres) en /help")
                return

            await interaction.response.send_message(embed=embed, ephemeral=True)
            logging.info(f"El usuario {interaction.user.id} ejecutó /help en el guild {interaction.guild.id if interaction.guild else 'DM'}.")
        except Exception as e:
            logging.error(f"Error en /help: {e}", exc_info=True)
            await interaction.response.send_message(
                embed=error(f"Error al mostrar la ayuda: {str(e)}"),
                ephemeral=True
            )

async def setup(bot):
    await bot.add_cog(LeagueCog(bot))
