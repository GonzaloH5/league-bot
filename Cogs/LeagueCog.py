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
from discord import ui, SelectOption
from discord.interactions import Interaction
import sqlite3
from discord.ext import commands

logger = logging.getLogger('bot')

class OfferView(ui.View):
    def __init__(self, offer_id: int, manager_id: int, is_clause_payment: bool = False):
        super().__init__(timeout=None)
        self.offer_id = offer_id
        self.manager_id = manager_id
        self.is_clause_payment = is_clause_payment

    @ui.button(label="✅ Aceptar", style=discord.ButtonStyle.green)
    async def accept(self, interaction: discord.Interaction, button: ui.Button):
        if await check_ban(interaction, interaction.user.id):
            return
        offer = db.get_offer(self.offer_id)
        if not offer or offer['status'] not in ['pending', 'bought_clause']:
            await interaction.response.edit_message(embed=error("Oferta no válida o ya procesada."), view=None)
            return
        if self.is_clause_payment:
            if db.accept_clause_payment(self.offer_id):
                await interaction.response.edit_message(embed=success("Transferencia por cláusula aceptada."), view=None)
                manager = interaction.client.get_user(self.manager_id)
                if manager:
                    await manager.send(embed=info(f"El jugador {interaction.user.name} aceptó la transferencia por cláusula #{self.offer_id}."))
            else:
                await interaction.response.edit_message(embed=error("Fondos insuficientes."), view=None)
        else:
            db.accept_offer(self.offer_id)
            await interaction.response.edit_message(embed=success("Oferta aceptada."), view=None)
            manager = interaction.client.get_user(self.manager_id)
            if manager:
                await manager.send(embed=info(f"El jugador {interaction.user.name} aceptó tu oferta #{self.offer_id}."))

    @ui.button(label="❌ Rechazar", style=discord.ButtonStyle.red)
    async def reject(self, interaction: discord.Interaction, button: ui.Button):
        if await check_ban(interaction, interaction.user.id):
            return
        offer = db.get_offer(self.offer_id)
        if not offer or offer['status'] not in ['pending', 'bought_clause']:
            await interaction.response.edit_message(embed=error("Oferta no válida o ya procesada."), view=None)
            return
        db.reject_offer(self.offer_id)
        await interaction.response.edit_message(embed=info("Oferta rechazada."), view=None)
        manager = interaction.client.get_user(self.manager_id)
        if manager:
            await manager.send(embed=info(f"El jugador {interaction.user.name} rechazó tu oferta #{self.offer_id}."))

    async def on_timeout(self):
        try:
            await self.message.edit(view=None)
        except:
            pass

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: ui.Item):
        logger.error(f'Error en OfferView: {error}', exc_info=True)
        await interaction.response.send_message(embed=error("Ocurrió un error."), ephemeral=True)

class TeamBookView(ui.View):
    def __init__(self, teams: list, user_id: int, bot: commands.Bot):
        super().__init__(timeout=300)
        self.teams = teams
        self.user_id = user_id
        self.bot = bot
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
            captains = db.get_captains(team['id'])
            captain_mentions = [self.bot.get_user(
                c).mention for c in captains if self.bot.get_user(c)]
            embed.add_field(name="Capitanes", value=", ".join(
                captain_mentions) or "Sin capitanes", inline=False)
            players = db.get_players_by_team(team['id'])
            embed.add_field(name="Jugadores", value="\n".join(
                [f"{p['name']}: {p['contract_details'] or 'Sin contrato'}" for p in players]) or "Ninguno", inline=False)
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
    def __init__(self, amistosos, bot):
        super().__init__(timeout=60)
        self.bot = bot
        self.add_item(EliminarAmistosoSelect(amistosos, bot))

class EliminarAmistosoSelect(ui.Select):
    def __init__(self, amistosos, bot):
        self.bot = bot
        options = [
            SelectOption(
                label=f"{db.get_team_by_id(a['team1_id'])['name']} vs {db.get_team_by_id(a['team2_id'])['name']} ({a['hora']})",
                value=str(a['id'])
            ) for a in amistosos
        ]
        if not options:
            options = [SelectOption(
                label="No hay amistosos para eliminar", value="none")]
        super().__init__(placeholder="Selecciona un amistoso para eliminar", options=options)

    async def callback(self, interaction: Interaction):
        if self.values[0] == "none":
            await interaction.response.send_message(embed=error("No hay amistosos disponibles para eliminar."), ephemeral=True)
            return

        amistoso_id = int(self.values[0])
        amistoso = db.get_amistoso_by_id(amistoso_id)
        if not amistoso:
            await interaction.response.send_message(embed=error("Amistoso no encontrado."), ephemeral=True)
            return

        manager_team = db.get_team_by_manager(interaction.user.id)
        captain_team = db.get_team_by_captain(interaction.user.id)
        team = manager_team or captain_team
        if not team or (team['id'] != amistoso['team1_id'] and team['id'] != amistoso['team2_id']):
            await interaction.response.send_message(embed=error("No eres manager ni capitán de los equipos involucrados."), ephemeral=True)
            return

        db.delete_amistoso(amistoso_id)
        logger.info(
            f"Amistoso ID {amistoso_id} eliminado por {interaction.user.name} ({interaction.user.id})")

        team1 = db.get_team_by_id(amistoso['team1_id'])
        team2 = db.get_team_by_id(amistoso['team2_id'])
        recipients = []
        for t in [team1, team2]:
            manager_id = t['manager_id']
            captains = db.get_captains(t['id'])
            if manager_id:
                recipients.append(manager_id)
            recipients.extend(captains)

        for recipient_id in set(recipients):
            if recipient_id != interaction.user.id:
                recipient = self.bot.get_user(recipient_id)
                if recipient:
                    try:
                        await recipient.send(embed=info(f"El amistoso entre {team1['name']} y {team2['name']} a las {amistoso['hora']} fue eliminado por {interaction.user.name}."))
                        logger.info(
                            f"Notificación de eliminación enviada a {recipient.name} ({recipient_id})")
                    except discord.Forbidden:
                        logger.warning(
                            f"No se pudo notificar a {recipient.name} ({recipient_id}) - DMs desactivados")
                    except discord.HTTPException as e:
                        logger.error(
                            f"Error HTTP al notificar a {recipient.name} ({recipient_id}): {e}")

        hoy = datetime.now(
            self.bot.cogs['LeagueCog'].tz_minus_3).strftime("%Y-%m-%d")
        amistosos = db.get_amistosos_del_dia(hoy)
        table = self.bot.cogs['LeagueCog'].generate_amistosos_table(amistosos)
        channel = self.bot.get_channel(
            self.bot.cogs['LeagueCog'].amistosos_channel_id)
        if channel and self.bot.cogs['LeagueCog'].amistosos_message_id:
            try:
                message = await channel.fetch_message(self.bot.cogs['LeagueCog'].amistosos_message_id)
                await message.edit(content=table)
            except discord.NotFound:
                logger.warning(
                    f"Mensaje {self.bot.cogs['LeagueCog'].amistosos_message_id} no encontrado para actualizar tabla de amistosos")
            except discord.Forbidden:
                logger.error(
                    f"Permisos insuficientes para editar mensaje en canal {self.bot.cogs['LeagueCog'].amistosos_channel_id}")

        await interaction.response.send_message(embed=success("Amistoso eliminado correctamente."), ephemeral=True)

class ConfirmAmistosoView(ui.View):
    def __init__(self, solicitud_id: int, bot: commands.Bot):
        super().__init__(timeout=None)
        self.solicitud_id = solicitud_id
        self.bot = bot

    @ui.button(label="✅ Aceptar", style=discord.ButtonStyle.green)
    async def accept(self, interaction: discord.Interaction, button: ui.Button):
        solicitud = db.get_solicitud_by_id(self.solicitud_id)
        if not solicitud or solicitud['status'] != 'pending':
            await interaction.response.send_message(embed=error("Solicitud no válida o ya procesada."), ephemeral=True)
            return
        manager_team = db.get_team_by_manager(interaction.user.id)
        if manager_team:
            team = manager_team
        else:
            team = db.get_team_by_captain(interaction.user.id)
        if not team or team['id'] != solicitud['solicitado_team_id']:
            await interaction.response.send_message(embed=error("No eres el manager ni capitán del equipo solicitado."), ephemeral=True)
            return

        hoy = datetime.now(
            self.bot.cogs['LeagueCog'].tz_minus_3).strftime("%Y-%m-%d")
        amistosos_hoy = db.get_amistosos_del_dia(hoy)
        if any(a['hora'] == solicitud['hora'] and (a['team1_id'] in [solicitud['solicitante_team_id'], solicitud['solicitado_team_id']] or a['team2_id'] in [solicitud['solicitante_team_id'], solicitud['solicitado_team_id']]) for a in amistosos_hoy):
            logger.warning(
                f"Conflicto de horario a las {solicitud['hora']} para uno de los equipos")
            await interaction.response.send_message(embed=error("Uno de los equipos ya tiene un amistoso programado a esa hora."), ephemeral=True)
            return

        db.update_solicitud_status(
            self.solicitud_id, 'accepted', interaction.user.id)
        db.add_amistoso(solicitud['solicitante_team_id'],
                        solicitud['solicitado_team_id'], solicitud['hora'], solicitud['fecha'])

        manager_id = team['manager_id']
        captains = db.get_captains(team['id'])
        recipients = set(
            [manager_id] + captains) if manager_id else set(captains)
        for recipient_id in recipients:
            if recipient_id != interaction.user.id:
                recipient = self.bot.get_user(recipient_id)
                if recipient:
                    try:
                        await recipient.send(embed=info(f"El amistoso contra {db.get_team_by_id(solicitud['solicitante_team_id'])['name']} a las {solicitud['hora']} fue aceptado por {interaction.user.name}."))
                        logger.info(
                            f"Notificación de aceptación enviada a {recipient.name} ({recipient_id})")
                    except discord.Forbidden:
                        logger.warning(
                            f"No se pudo notificar a {recipient.name} ({recipient_id}) - DMs desactivados")
                    except discord.HTTPException as e:
                        logger.error(
                            f"Error HTTP al notificar a {recipient.name} ({recipient_id}): {e}")

        await interaction.response.send_message(embed=success("Amistoso aceptado y programado."), ephemeral=True)

        amistosos = db.get_amistosos_del_dia(hoy)
        table = self.bot.cogs['LeagueCog'].generate_amistosos_table(amistosos)
        channel = self.bot.get_channel(
            self.bot.cogs['LeagueCog'].amistosos_channel_id)
        if channel and self.bot.cogs['LeagueCog'].amistosos_message_id:
            try:
                message = await channel.fetch_message(self.bot.cogs['LeagueCog'].amistosos_message_id)
                await message.edit(content=table)
            except discord.NotFound:
                logger.warning(
                    f"Mensaje {self.bot.cogs['LeagueCog'].amistosos_message_id} no encontrado para actualizar tabla de amistosos")
            except discord.Forbidden:
                logger.error(
                    f"Permisos insuficientes para editar mensaje en canal {self.bot.cogs['LeagueCog'].amistosos_channel_id}")

    @ui.button(label="❌ Rechazar", style=discord.ButtonStyle.red)
    async def reject(self, interaction: discord.Interaction, button: ui.Button):
        solicitud = db.get_solicitud_by_id(self.solicitud_id)
        if not solicitud or solicitud['status'] != 'pending':
            await interaction.response.send_message(embed=error("Solicitud no válida o ya procesada."), ephemeral=True)
            return
        manager_team = db.get_team_by_manager(interaction.user.id)
        if manager_team:
            team = manager_team
        else:
            team = db.get_team_by_captain(interaction.user.id)
        if not team or team['id'] != solicitud['solicitado_team_id']:
            await interaction.response.send_message(embed=error("No eres el manager ni capitán del equipo solicitado."), ephemeral=True)
            return
        db.update_solicitud_status(
            self.solicitud_id, 'rejected', interaction.user.id)
        await interaction.response.send_message(embed=info("Solicitud de amistoso rechazada."), ephemeral=True)

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
    def __init__(self, screenshot_id: int):
        super().__init__(timeout=None)
        self.screenshot_id = screenshot_id

    @ui.button(label="✅ Aceptar", style=discord.ButtonStyle.green)
    async def accept(self, interaction: discord.Interaction, button: ui.Button):
        if not any(role.name == "Arbitro" for role in interaction.user.roles):
            await interaction.response.send_message(embed=error("Solo los usuarios con el rol 'Arbitro' pueden revisar capturas."), ephemeral=True)
            return
        db.update_screenshot_status(self.screenshot_id, 'accepted')
        await interaction.response.edit_message(embed=success(f"Captura #{self.screenshot_id} aceptada."), view=None)

    @ui.button(label="❌ Rechazar", style=discord.ButtonStyle.red)
    async def reject(self, interaction: discord.Interaction, button: ui.Button):
        if not any(role.name == "Arbitro" for role in interaction.user.roles):
            await interaction.response.send_message(embed=error("Solo los usuarios con el rol 'Arbitro' pueden revisar capturas."), ephemeral=True)
            return
        db.update_screenshot_status(self.screenshot_id, 'rejected')
        await interaction.response.edit_message(embed=success(f"Captura #{self.screenshot_id} rechazada."), view=None)

class LeagueCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.ss_input_channel_id = 1396571890885333023
        self.review_channel_id = 1396571902905946234
        self.tz_minus_3 = timezone(timedelta(hours=-3))
        self.amistosos_channel_id = 1390465965015306352
        self.amistosos_message_id = None

    def generate_amistosos_table(self, amistosos: list) -> str:
        horarios = ["19:00", "19:30", "20:00", "20:30", "21:00",
                    "21:30", "22:00", "22:30", "23:00", "23:30", "00:00"]
        hoy = datetime.now(self.tz_minus_3).strftime("%Y-%m-%d")

        partidos_por_horario = {h: "Disponible" for h in horarios}
        for amistoso in amistosos:
            if amistoso['fecha'] == hoy:
                team1 = db.get_team_by_id(amistoso['team1_id'])
                team2 = db.get_team_by_id(amistoso['team2_id'])
                if team1 and team2:
                    partidos_por_horario[amistoso['hora']
                                         ] = f"**{team1['name']} vs {team2['name']}** ⚽"

        table = f"```\n"
        table += f"📅 Amistosos del {hoy} 📅\n"
        table += f"⚽ Horario | Partido ⚽\n"
        table += f"{'═'*30}\n"
        for hora in horarios:
            partido = partidos_por_horario[hora]
            if partido == "Disponible":
                table += f"⚪ {hora} | {partido} 🟢\n"
            else:
                table += f"🏟️ {hora} | {partido}\n"
        table += f"```\n"
        return table

    @commands.Cog.listener()
    async def on_message(self, message):
        config = db.get_server_config(message.guild.id)
        if not config or not config['ss_channel_id']:
            logger.warning(f"No se ha configurado el canal de SS para el guild {message.guild.id}")
            return
        if message.channel.id != config['ss_channel_id']:
            return
        await asyncio.sleep(1)
        logger.info(
            f"Mensaje recibido: '{message.content}' en canal {message.channel.id} por {message.author} ({message.author.id}) con adjuntos: {message.attachments}")

        if message.author == self.bot.user:
            logger.debug("Ignorando mensaje del bot.")
            return

        if message.channel.id != self.ss_input_channel_id:
            logger.debug(
                f"Mensaje ignorado: canal {message.channel.id} no es el canal de entrada {self.ss_input_channel_id}.")
            return

        if not message.attachments:
            logger.debug("Mensaje ignorado: no tiene adjuntos.")
            await message.reply(embed=error("Por favor, envía una imagen."))
            return

        attachment = message.attachments[0]
        logger.info(
            f"Procesando adjunto: {attachment.filename}, URL: {attachment.url}")
        if not attachment.filename.lower().endswith(('.png', '.jpg', '.jpeg')):
            logger.warning(
                f"Adjunto no válido: {attachment.filename} no es PNG/JPG.")
            await message.reply(embed=error("Por favor, envía una imagen en formato PNG o JPG."))
            return

        player = db.get_player_by_id(message.guild.id, message.author.id)
        if not player:
            logger.warning(
                f"Usuario {message.author.id} no está registrado como jugador.")
            await message.reply(embed=error("No estás registrado como jugador. Contacta a un admin."))
            return

        try:
            response = requests.get(attachment.url)
            response.raise_for_status()
            img = Image.open(BytesIO(response.content))
            img = preprocess_image_for_ocr(img)
            logger.info("Imagen descargada y preprocesada exitosamente.")
        except Exception as e:
            logger.error(f"Error al descargar o preprocesar la imagen: {e}")
            await message.reply(embed=error("Error al procesar la imagen. Intenta de nuevo."))
            return

        try:
            text = pytesseract.image_to_string(img, lang='eng')
            logger.debug(f"Texto extraído por OCR: {text}")
        except Exception as e:
            logger.error(f"Error en OCR: {e}")
            await message.reply(embed=error("Error al procesar la imagen con OCR. Intenta de nuevo."))
            return

        nicktags = extract_nicktags(text)
        logger.info(f"Nicktags detectados: {nicktags}")

        discord_name = message.author.name
        discord_display = message.author.display_name
        nicktag = find_best_nicktag(nicktags, discord_name, discord_display)
        logger.info(
            f"Nicktag seleccionado tras comparación: {nicktag or 'NINGUNO'}")

        if not nicktag:
            name_pattern = re.compile(r'\b(' + re.escape(discord_name) + r'|' + re.escape(
                discord_display) + r')(?:\.\d+)?', re.IGNORECASE)
            match = name_pattern.search(text)
            if match:
                nicktag = match.group(0)
                logger.info(
                    f"Nicktag encontrado por validación secundaria: {nicktag}")

        time_pattern = re.compile(r'\b([01]?\d|2[0-3])[:.][0-5]\d\b')
        time_match = time_pattern.search(text)
        screenshot_time = time_match.group(0).replace(
            '.', ':') if time_match else None
        logger.info(f"Hora detectada: {screenshot_time or 'NINGUNA'}")

        review_channel = self.bot.get_channel(self.review_channel_id)
        if not review_channel:
            logger.error(
                f"Canal de revisión {self.review_channel_id} no encontrado.")
            await message.reply(embed=error("Error interno: canal de revisión no encontrado. Contacta a un admin."))
            return

        if nicktag and screenshot_time:
            screenshot_id = db.add_screenshot(
                message.author.id,
                nicktag,
                discord_name,
                message.channel.id,
                attachment.url,
                screenshot_time
            )
            db.update_screenshot_status(screenshot_id, 'accepted')
            logger.info(
                f"Captura #{screenshot_id} aceptada automáticamente para {discord_name}.")
            await message.reply(embed=success(f"Captura validada correctamente. NICKTAG: {nicktag}, Hora: {screenshot_time}"))
        else:
            screenshot_id = db.add_screenshot(
                message.author.id,
                nicktag or "No detectado",
                discord_name,
                message.channel.id,
                attachment.url,
                screenshot_time
            )
            embed = info(f"Captura dudosa #{screenshot_id} de {discord_name}")
            embed.add_field(name="NICKTAG detectado",
                            value=nicktag or "No detectado", inline=False)
            embed.add_field(name="Nombre Discord",
                            value=discord_name, inline=False)
            embed.add_field(name="Nombre de visualización",
                            value=discord_display, inline=False)
            embed.add_field(name="Hora detectada",
                            value=screenshot_time or "No detectada", inline=False)
            embed.add_field(
                name="Canal", value=f"#{message.channel.name}", inline=False)
            embed.add_field(
                name="Razón de revisión",
                value="Falta NICKTAG" if not nicktag else "Falta hora" if not screenshot_time else "Datos incompletos",
                inline=False
            )
            embed.set_image(url=attachment.url)
            view = ReviewView(screenshot_id)
            await review_channel.send(embed=embed, view=view)
            logger.info(f"Captura #{screenshot_id} enviada a revisión.")
            await message.reply(embed=error("Captura enviada a revisión: no se detectaron todos los datos requeridos."))

        await self.bot.process_commands(message)
    
    @app_commands.command(name="test_command", description="Comando de prueba para verificar sincronización")
    async def test_command(self, interaction: discord.Interaction):
        await interaction.response.send_message("¡Comando de prueba funcionando!", ephemeral=True)

    @app_commands.command(name="check_market", description="Verifica el estado del mercado")
    async def check_market(self, interaction: discord.Interaction):
        status = db.get_market_status(interaction.guild.id)
        await interaction.response.send_message(f"El mercado está {status}.", ephemeral=True)

    @app_commands.command(name="ss", description="Ver historial de capturas validadas")
    @app_commands.describe(jugador="Jugador objetivo (opcional)")
    async def ss(self, interaction: discord.Interaction, jugador: discord.User = None):
        if jugador and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(embed=error("Solo los admins pueden ver el historial de otros jugadores."), ephemeral=True)
            return

        user_id = jugador.id if jugador else interaction.user.id
        screenshots = db.get_screenshots_by_user(user_id)

        if not screenshots:
            await interaction.response.send_message(embed=info("No hay capturas registradas."), ephemeral=True)
            return

        embed = info(
            f"Historial de capturas de {jugador.name if jugador else interaction.user.name}")
        for ss in screenshots[:10]:
            embed.add_field(
                name=f"ID: {ss['id']} ({ss['status']})",
                value=f"NICKTAG: {ss['nicktag']}\nCanal: {f'#{self.bot.get_channel(ss['channel_id']).name}' if self.bot.get_channel(
                    ss['channel_id']) else 'Desconocido'}\nHora: {ss['screenshot_time'] or 'No detectada'}\nFecha: {ss['timestamp']}",
                inline=False
            )
        embed.set_footer(text=f"Total: {len(screenshots)} capturas")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="eliminaramistoso", description="Eliminar un amistoso programado para hoy")
    async def eliminaramistoso(self, interaction: discord.Interaction):
        logger.info(f"Usuario {interaction.user.id} ejecutó /eliminaramistoso")

        try:
            manager_team = db.get_team_by_manager(interaction.user.id)
            if manager_team:
                team = manager_team
                logger.info(
                    f"Usuario {interaction.user.id} es manager del equipo {team['name']}")
            else:
                captain_team = db.get_team_by_captain(interaction.user.id)
                if captain_team:
                    team = captain_team
                    logger.info(
                        f"Usuario {interaction.user.id} es capitán del equipo {team['name']}")
                else:
                    team = None
                    logger.info(
                        f"Usuario {interaction.user.id} no es manager ni capitán")

            if not team:
                await interaction.response.send_message(embed=error("No eres manager ni capitán de ningún equipo."), ephemeral=True)
                return

            hoy = datetime.now(self.tz_minus_3).strftime("%Y-%m-%d")
            amistosos_hoy = db.get_amistosos_del_dia(hoy)
            amistosos_equipo = [a for a in amistosos_hoy if a['team1_id']
                                == team['id'] or a['team2_id'] == team['id']]

            if not amistosos_equipo:
                await interaction.response.send_message(embed=error("No tienes amistosos programados para hoy."), ephemeral=True)
                return

            await interaction.response.send_message(
                embed=info("Selecciona el amistoso que deseas eliminar:"),
                view=EliminarAmistosoView(amistosos_equipo, self.bot),
                ephemeral=True
            )

        except Exception as e:
            logger.error(
                f"Error inesperado en /eliminaramistoso: {e}", exc_info=True)
            await interaction.response.send_message(embed=error("Ocurrió un error interno. Contacta a un administrador."), ephemeral=True)

    # En LeagueCog.py
    @app_commands.command(name="asignarcanalss", description="Asignar el canal para capturas de pantalla (solo admin)")
    @app_commands.describe(canal="Canal para capturas de pantalla")
    @app_commands.checks.has_permissions(administrator=True)
    async def asignarcanalss(self, interaction: discord.Interaction, canal: discord.TextChannel):
        db.set_ss_channel(interaction.guild.id, canal.id)
        await interaction.response.send_message(embed=success(f"Canal de capturas de pantalla establecido a {canal.mention}."), ephemeral=True)

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

    @app_commands.command(name="amistosos", description="Mostrar la tabla de amistosos del día")
    async def amistosos(self, interaction: discord.Interaction):
        hoy = datetime.now(self.tz_minus_3).strftime("%Y-%m-%d")
        amistosos = db.get_amistosos_del_dia(hoy)
        table = self.generate_amistosos_table(amistosos)
        await interaction.response.send_message(table, ephemeral=True)

    @app_commands.command(name="creartablaamistosos", description="Generar la tabla diaria de amistosos (solo admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def creartablaamistosos(self, interaction: discord.Interaction):
        config = db.get_server_config(interaction.guild.id)
        if not config or not config['amistosos_channel_id']:
            await interaction.response.send_message(embed=error("No se ha configurado el canal de amistosos."), ephemeral=True)
            return
        channel = self.bot.get_channel(config['amistosos_channel_id'])
        if not channel:
            await interaction.response.send_message(embed=error("Canal de amistosos no encontrado."), ephemeral=True)
            return
            table = self.generate_amistosos_table([])
            message = await channel.send(table)
            self.amistosos_message_id = message.id
            await interaction.response.send_message(embed=success("Tabla de amistosos del día creada."), ephemeral=True)

    @app_commands.command(name="registraramistoso", description="Solicitar un amistoso contra otro equipo")
    @app_commands.describe(equipo="Nombre del equipo contrario", hora="Hora del amistoso (HH:MM)")
    async def registraramistoso(self, interaction: discord.Interaction, equipo: str, hora: str):
        logger.info(
            f"Usuario {interaction.user.id} ejecutó /registraramistoso para equipo '{equipo}' a las {hora}")

        await interaction.response.defer(ephemeral=True)

        try:
            manager_team = db.get_team_by_manager(interaction.user.id)
            if manager_team:
                team = manager_team
                is_manager = True
                is_captain_flag = db.is_captain(
                    interaction.guild.id, team['id'], interaction.user.id)
                logger.info(
                    f"Usuario {interaction.user.id} es manager del equipo {team['name']}")
            else:
                captain_team = db.get_team_by_captain(interaction.user.id)
                if captain_team:
                    team = captain_team
                    is_manager = False
                    is_captain_flag = True
                    logger.info(
                        f"icultural {interaction.user.id} es capitán del equipo {team['name']}")
                else:
                    team = None
                    is_manager = False
                    is_captain_flag = False
                    logger.info(
                        f"Usuario {interaction.user.id} no es manager ni capitán")

            if not (is_manager or is_captain_flag):
                await interaction.followup.send(embed=error("No eres manager ni capitán de ningún equipo."), ephemeral=True)
                return

            solicitado_team = db.get_team_by_name(interaction.guild.id, equipo)
            if not solicitado_team:
                logger.warning(f"Equipo '{equipo}' no encontrado")
                await interaction.followup.send(embed=error("Equipo no encontrado."), ephemeral=True)
                return
            if solicitado_team['id'] == team['id']:
                logger.warning(
                    f"Intento de amistoso contra el mismo equipo {team['name']}")
                await interaction.followup.send(embed=error("No puedes jugar contra tu propio equipo."), ephemeral=True)
                return

            hoy = datetime.now(self.tz_minus_3).strftime("%Y-%m-%d")
            logger.info(f"Fecha actual: {hoy}")

            amistosos_hoy = db.get_amistosos_del_dia(hoy)
            for amistoso in amistosos_hoy:
                if amistoso['team1_id'] == team['id']:
                    logger.warning(
                        f"Equipo {team['name']} ya tiene un amistoso programado como solicitante hoy")
                    await interaction.followup.send(embed=error("Tu equipo ya tiene un amistoso programado como solicitante para hoy."), ephemeral=True)
                    return

            try:
                hora_dt = datetime.strptime(hora, "%H:%M")
                if not (19 <= hora_dt.hour < 24 and hora_dt.minute % 30 == 0):
                    raise ValueError
                logger.info(f"Hora válida: {hora}")
            except ValueError:
                logger.warning(f"Hora inválida: {hora}")
                await interaction.followup.send(embed=error("Hora inválida. Debe ser entre 19:00 y 00:00 en intervalos de 30 minutos."), ephemeral=True)
                return

            if any(a['hora'] == hora and (a['team1_id'] in [team['id'], solicitado_team['id']] or a['team2_id'] in [team['id'], solicitado_team['id']]) for a in amistosos_hoy):
                logger.warning(
                    f"Conflicto de horario a las {hora} para uno de los equipos")
                await interaction.followup.send(embed=error("Uno de los equipos ya tiene un amistoso programado a esa hora."), ephemeral=True)
                return

            solicitud_id = db.add_solicitud_amistoso(
                interaction.guild.id, team['id'], solicitado_team['id'], hora, hoy, interaction.user.id)
            if solicitud_id == -1:
                logger.error(
                    f"Error al crear solicitud para equipo {team['name']} vs {solicitado_team['name']}")
                await interaction.followup.send(embed=error("Error al crear la solicitud."), ephemeral=True)
                return
            logger.info(f"Solicitud creada con ID {solicitud_id}")

            manager_id = solicitado_team['manager_id']
            captains = db.get_captains(solicitado_team['id'])
            recipients = set(
                [manager_id] + captains) if manager_id else set(captains)
            logger.info(f"Destinatarios: {recipients}")

            if not recipients:
                logger.warning(
                    f"Equipo {solicitado_team['name']} no tiene manager ni capitanes")
                await interaction.followup.send(embed=error("El equipo solicitado no tiene manager ni capitanes para recibir la solicitud."), ephemeral=True)
                return

            failed_dms = []
            for recipient_id in recipients:
                recipient = self.bot.get_user(recipient_id)
                if recipient:
                    try:
                        view = ConfirmAmistosoView(solicitud_id, self.bot)
                        await recipient.send(embed=info(f"Solicitud de amistoso de {team['name']} para hoy a las {hora}."), view=view)
                        logger.info(
                            f"DM enviado a {recipient.name} ({recipient_id})")
                    except discord.Forbidden:
                        logger.warning(
                            f"No se pudo enviar DM a {recipient.name} ({recipient_id}) - DMs desactivados")
                        failed_dms.append(recipient.name)
                    except discord.HTTPException as e:
                        logger.error(
                            f"Error HTTP al enviar DM a {recipient.name} ({recipient_id}): {e}")
                        failed_dms.append(recipient.name)
                else:
                    logger.warning(f"Usuario {recipient_id} no encontrado")
                    failed_dms.append(str(recipient_id))

            if failed_dms:
                await interaction.followup.send(embed=success(f"Solicitud de amistoso enviada, pero no se pudo notificar a: {', '.join(failed_dms)}."), ephemeral=True)
            else:
                await interaction.followup.send(embed=success("Solicitud de amistoso enviada."), ephemeral=True)

        except Exception as e:
            logger.error(
                f"Error inesperado en /registraramistoso: {e}", exc_info=True)
            await interaction.followup.send(embed=error("Ocurrió un error interno. Contacta a un administrador."), ephemeral=True)

    @app_commands.command(name="resetearamistosos", description="Reiniciar la tabla de amistosos (solo admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def resetearamistosos(self, interaction: discord.Interaction):
        hoy = datetime.now(self.tz_minus_3).strftime("%Y-%m-%d")
        db.delete_amistosos_del_dia(hoy)
        channel = self.bot.get_channel(self.amistosos_channel_id)
        if not channel or not self.amistosos_message_id:
            await interaction.response.send_message(embed=error("Canal o mensaje de amistosos no configurado."), ephemeral=True)
            return
        table = self.generate_amistosos_table([])
        message = await channel.fetch_message(self.amistosos_message_id)
        await message.edit(content=table)
        await interaction.response.send_message(embed=success("Tabla de amistosos reiniciada."), ephemeral=True)

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

    @app_commands.command(name="registrarjugador", description="Registrar a un usuario como jugador")
    @app_commands.describe(jugador="Usuario a registrar")
    @app_commands.checks.has_permissions(administrator=True)
    async def registrarjugador(self, interaction: discord.Interaction, jugador: discord.User):
        if db.get_team_by_manager(interaction.guild.id, jugador.id):
            await interaction.response.send_message(embed=error(f"{jugador.name} es manager y no puede ser jugador."), ephemeral=True)
            return
        if db.get_player_by_id(interaction.guild.id, jugador.id):
            await interaction.response.send_message(embed=error(f"{jugador.name} ya está registrado."), ephemeral=True)
            return
        db.add_player(interaction.guild.id, jugador.name, jugador.id)
        await interaction.response.send_message(embed=success(f"{jugador.name} registrado como jugador."), ephemeral=True)

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
        if await check_ban(interaction, jugador.id):
            return
        manager_team = db.get_team_by_manager(
            interaction.guild.id, interaction.user.id)
        if not manager_team:
            await interaction.response.send_message(embed=error("No eres manager de ningún equipo."), ephemeral=True)
            return
        if clausula <= 0 or duracion <= 0:
            await interaction.response.send_message(embed=error("Cláusula y duración deben ser positivas."), ephemeral=True)
            return
        player = db.get_player_by_id(interaction.guild.id, jugador.id)
        if not player:
            await interaction.response.send_message(embed=error("El usuario no está registrado como jugador."), ephemeral=True)
            return
        if db.has_pending_offer(interaction.guild.id, interaction.user.id, jugador.id):
            await interaction.response.send_message(embed=error("Ya existe una oferta pendiente para este jugador."), ephemeral=True)
            return
        offer_id = db.create_transfer_offer(
            interaction.guild.id, player['name'], manager_team['id'], manager_team['id'], interaction.user.id, clausula, duracion, clausula)
        if offer_id == -1:
            await interaction.response.send_message(embed=error("Error al crear la oferta."), ephemeral=True)
            return
        view = OfferView(offer_id, interaction.user.id)
        try:
            await jugador.send(embed=info(f"Oferta de {format_tag(interaction.user)}:\n**Cláusula:** {clausula:,}\n**Duración:** {duracion} meses\nID: {offer_id}"), view=view)
            await interaction.response.send_message(embed=success("Oferta enviada al jugador."), ephemeral=True)
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
                [f"ID {o['id']} a {o['player_name']} - Cláusula: {o['clause'] or 'N/A':,}, Duración: {o['duration'] or 'N/A'} meses" for o in sent]), inline=False)
        if received:
            embed.add_field(name="Recibidas", value="\n".join(
                [f"ID {o['id']} de {o['manager_name']} - Cláusula: {o['clause'] or 'N/A':,}, Duración: {o['duration'] or 'N/A'} meses" for o in received]), inline=False)
        if not (sent or received):
            embed.description = "No hay ofertas pendientes."
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="perfil", description="Ver el perfil de un jugador")
    @app_commands.describe(jugador="Jugador objetivo")
    async def perfil(self, interaction: discord.Interaction, jugador: discord.User):
        if await check_ban(interaction, jugador.id):
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
            [f"{p['name']}: {p['contract_details'] or 'Sin contrato'}" for p in players]) or "No hay jugadores."
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="historialjugador", description="Ver historial de transferencias de un jugador")
    @app_commands.describe(jugador="Jugador objetivo")
    async def historialjugador(self, interaction: discord.Interaction, jugador: discord.User):
        if await check_ban(interaction, jugador.id):
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

    @app_commands.command(name="pagaclausula", description="Pagar la cláusula de un jugador")
    @app_commands.describe(jugador="Jugador objetivo")
    async def pagaclausula(self, interaction: discord.Interaction, jugador: discord.User):
        if await check_ban(interaction, jugador.id):
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
            interaction.guild.id, player['name'], manager_team['id'], player['release_clause'], interaction.user.id)
        if offer_id == -1:
            await interaction.response.send_message(embed=error("Fondos insuficientes."), ephemeral=True)
            return
        view = OfferView(offer_id, interaction.user.id, is_clause_payment=True)
        try:
            await jugador.send(embed=info(f"Oferta por cláusula de {format_tag(interaction.user)}:\n**Cláusula:** {player['release_clause']:,}\nID: {offer_id}"), view=view)
            await interaction.response.send_message(embed=success(f"Oferta por cláusula enviada a {jugador.name}."), ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(embed=error("No puedo enviar DM al jugador."), ephemeral=True)

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
        view = TeamBookView(teams, interaction.user.id, self.bot)
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
        await interaction.response.send_message(embed=success(f"{jugador.name} agregado al mercado con cláusula {clausula if clausula else player['release_clause']:,}."))

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
        team = db.get_team_by_name(interaction.guild.id, nombre)
        if not team:
            await interaction.response.send_message(embed=error("Equipo no encontrado."), ephemeral=True)
            return
        # Aquí va el código para eliminar el equipo
        db.delete_team(interaction.guild.id, nombre)
        await interaction.response.send_message(embed=success("Equipo eliminado, Todos sus jugadores son agentes libres"), ephemeral=True)

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

    # Comando de ayuda personalizado
    @app_commands.command(name="help", description="Muestra los comandos disponibles del bot")
    async def help_command(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🧾 Comandos del Bot",
            description="Comandos organizados por categoría para gestionar la liga y amistosos.",
            color=discord.Color.from_rgb(102, 255, 178)  # Verde claro
        )
        embed.set_thumbnail(url=self.bot.user.avatar.url if self.bot.user.avatar else discord.utils.MISSING)
        embed.set_footer(text=f"{self.bot.user.name}", icon_url=self.bot.user.avatar.url if self.bot.user.avatar else discord.utils.MISSING)

        # Comandos Generales
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
            ("amistoso", "Ver amistosos programados.")
        ]
        general_field = "\n".join([f"**`/{cmd}`** - {desc}" for cmd, desc in general_commands])
        embed.add_field(name="📋 General", value=general_field, inline=False)

        # Comandos de Manager (accesibles para managers y capitanes)
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
        embed.add_field(name="⚽ Manager", value=manager_field, inline=False)

        # Comandos de Admin
        admin_commands = [
            ("open_market", "Abre el mercado de transferencias."),
            ("close_market", "Cierra el mercado de transferencias."),
            ("sync", "Sincroniza los comandos del bot."),
            ("check_market", "Verifica el estado del mercado."),
            ("ss", "Ver historial de capturas validadas."),
            ("crearequipo", "Crear un equipo nuevo con división."),
            ("creartablaamistosos", "Generar la tabla diaria de amistosos."),
            ("asignarmanager", "Asignar un manager a un equipo."),
            ("registrarjugador", "Registrar a un usuario como jugador."),
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
                    value=current_field,
                    inline=False
                )
                current_field = command_text
                field_count += 1
            else:
                current_field += command_text
        if current_field:
            embed.add_field(
                name=f"🔧 Admin (Parte {field_count})",
                value=current_field,
                inline=False
            )

        total_length = sum(len(field.value) for field in embed.fields) + len(embed.description) + len(embed.title)
        if total_length > 6000:
            await interaction.response.send_message(
                "Error: La lista de comandos es demasiado larga para mostrar.",
                ephemeral=True
            )
            print(f"Error: Embed demasiado largo ({total_length} caracteres)")
            return

        await interaction.response.send_message(embed=embed, ephemeral=True)
        print(f"El usuario {interaction.user.id} ejecutó /help en el guild {interaction.guild.id if interaction.guild else 'DM'}.")



async def sync(self, interaction: discord.Interaction):
    if interaction.user.id == 509812954426769418:
        try:
            synced = await self.bot.tree.sync()  # Se elimina el segundo 'await'
            await interaction.response.send_message(f"Sincronizados {len(synced)} comando(s) globalmente!", ephemeral=True)
            logger.info(f"Synced {len(synced)} command(s) globally")
        except Exception as e:
            await interaction.response.send_message(f"Error al sincronizar: {e}", ephemeral=True)
            logger.error(f"Failed to sync commands: {e}")
    else:
        await interaction.response.send_message("¡Solo el dueño del bot puede usar este comando!", ephemeral=True)

async def setup(bot):
    await bot.add_cog(LeagueCog(bot))
