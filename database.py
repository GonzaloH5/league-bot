import sqlite3
import logging
import os
from datetime import datetime, timedelta

database_logger = logging.getLogger('database')
database_logger.setLevel(logging.INFO)
handler = logging.FileHandler('bot.log')
handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
database_logger.addHandler(handler)

GLOBAL_DB_PATH = 'global.db'
VALID_STATUSES = {'pending', 'accepted', 'rejected', 'cancelled', 'finalized', 'bought_clause'}

def get_db_path(guild_id: int) -> str:
    return f"league_{guild_id}.db"

def create_tables(guild_id: int):
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.executescript("""
            CREATE TABLE IF NOT EXISTS teams (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                manager_id INTEGER,
                division TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS players (
                user_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                team_id INTEGER,
                transferable INTEGER DEFAULT 0,
                banned INTEGER DEFAULT 0,
                contract_duration INTEGER,
                release_clause INTEGER,
                original_release_clause INTEGER,
                FOREIGN KEY(team_id) REFERENCES teams(id)
            );
            CREATE TABLE IF NOT EXISTS transfer_offers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id INTEGER NOT NULL,
                from_team_id INTEGER,
                to_team_id INTEGER,
                from_manager_id INTEGER,
                to_manager_id INTEGER,
                price INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                contract_duration INTEGER,
                release_clause INTEGER,
                FOREIGN KEY(player_id) REFERENCES players(user_id),
                FOREIGN KEY(from_team_id) REFERENCES teams(id),
                FOREIGN KEY(to_team_id) REFERENCES teams(id)
            );
            CREATE TABLE IF NOT EXISTS club_balance (
                team_id INTEGER PRIMARY KEY,
                balance INTEGER DEFAULT 0,
                FOREIGN KEY(team_id) REFERENCES teams(id)
            );
            CREATE TABLE IF NOT EXISTS team_captains (
                team_id INTEGER,
                captain_id INTEGER,
                PRIMARY KEY (team_id, captain_id),
                FOREIGN KEY (team_id) REFERENCES teams(id),
                FOREIGN KEY (captain_id) REFERENCES players(user_id)
            );
            CREATE TABLE IF NOT EXISTS guild_config (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            CREATE TABLE IF NOT EXISTS server_config (
                guild_id INTEGER PRIMARY KEY,
                ss_channel_ids TEXT,
                amistosos_channel_id INTEGER,
                arbiter_role_id INTEGER,
                registro_channel_id INTEGER
            );
            CREATE TABLE IF NOT EXISTS screenshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                nicktag TEXT NOT NULL,
                discord_name TEXT NOT NULL,
                channel_id INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                screenshot_time TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                image_url TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES players(user_id)
            );
            CREATE TABLE IF NOT EXISTS amistosos_tablas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS amistosos_horarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tabla_id INTEGER NOT NULL,
                horario TEXT NOT NULL,
                disponible INTEGER DEFAULT 1,
                FOREIGN KEY(tabla_id) REFERENCES amistosos_tablas(id)
            );
            CREATE TABLE IF NOT EXISTS amistosos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tabla_id INTEGER NOT NULL,
                horario TEXT NOT NULL,
                team1_id INTEGER NOT NULL,
                team2_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'confirmed',
                FOREIGN KEY(tabla_id) REFERENCES amistosos_tablas(id),
                FOREIGN KEY(team1_id) REFERENCES teams(id),
                FOREIGN KEY(team2_id) REFERENCES teams(id)
            );
            CREATE TABLE IF NOT EXISTS solicitudes_amistosos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tabla_id INTEGER NOT NULL,
                horario TEXT NOT NULL,
                solicitante_team_id INTEGER NOT NULL,
                solicitado_team_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                FOREIGN KEY(tabla_id) REFERENCES amistosos_tablas(id),
                FOREIGN KEY(solicitante_team_id) REFERENCES teams(id),
                FOREIGN KEY(solicitado_team_id) REFERENCES teams(id)
            );
            """)
            conn.commit()
        database_logger.info(f"Tablas creadas/verificadas para guild {guild_id}.")
    except sqlite3.Error as e:
        database_logger.error(f"Error al crear tablas para guild {guild_id}: {e}")
        raise

def create_global_tables():
    try:
        with sqlite3.connect(GLOBAL_DB_PATH) as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS banned_guilds (
                guild_id INTEGER PRIMARY KEY
            )''')
            conn.commit()
        database_logger.info("Tablas globales creadas/verificadas.")
    except sqlite3.Error as e:
        database_logger.error(f"Error al crear tablas globales: {e}")

def ban_guild(guild_id: int):
    try:
        with sqlite3.connect(GLOBAL_DB_PATH) as conn:
            conn.execute('INSERT OR IGNORE INTO banned_guilds (guild_id) VALUES (?)', (guild_id,))
            conn.commit()
        database_logger.info(f"Guild {guild_id} baneado.")
    except sqlite3.Error as e:
        database_logger.error(f"Error al banear guild {guild_id}: {e}")

def unban_guild(guild_id: int):
    try:
        with sqlite3.connect(GLOBAL_DB_PATH) as conn:
            conn.execute('DELETE FROM banned_guilds WHERE guild_id = ?', (guild_id,))
            conn.commit()
        database_logger.info(f"Guild {guild_id} desbaneado.")
    except sqlite3.Error as e:
        database_logger.error(f"Error al desbanear guild {guild_id}: {e}")

def is_guild_banned(guild_id: int) -> bool:
    try:
        with sqlite3.connect(GLOBAL_DB_PATH) as conn:
            cur = conn.execute('SELECT 1 FROM banned_guilds WHERE guild_id = ?', (guild_id,))
            return cur.fetchone() is not None
    except sqlite3.Error as e:
        database_logger.error(f"Error al verificar si guild {guild_id} está baneado: {e}")
        return False

def set_market_status(guild_id: int, status: str):
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute('INSERT OR REPLACE INTO guild_config (key, value) VALUES (?, ?)', ('market_status', status))
            conn.commit()
        database_logger.info(f"Estado del mercado para guild {guild_id} establecido a {status}.")
    except sqlite3.Error as e:
        database_logger.error(f"Error al establecer estado del mercado para guild {guild_id}: {e}")

def get_market_status(guild_id: int) -> str:
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.execute('SELECT value FROM guild_config WHERE key = ?', ('market_status',))
            row = cur.fetchone()
            return row[0] if row else 'closed'
    except sqlite3.Error as e:
        database_logger.error(f"Error al obtener estado del mercado para guild {guild_id}: {e}")
        return 'closed'

def set_server_settings(guild_id: int, ss_channel_ids: str, arbiter_role_id: int):
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT OR REPLACE INTO server_config (guild_id, ss_channel_ids, arbiter_role_id) VALUES (?, ?, ?)",
                (guild_id, ss_channel_ids, arbiter_role_id)
            )
            conn.commit()
            database_logger.info(f"Configuración establecida para guild {guild_id}: canales {ss_channel_ids}, rol {arbiter_role_id}")
    except sqlite3.Error as e:
        database_logger.error(f"Error al establecer configuración para guild {guild_id}: {e}")

def set_amistosos_channel(guild_id: int, channel_id: int):
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE server_config SET amistosos_channel_id = ? WHERE guild_id = ?",
                (channel_id, guild_id)
            )
            if cur.rowcount == 0:
                cur.execute(
                    "INSERT INTO server_config (guild_id, amistosos_channel_id) VALUES (?, ?)",
                    (guild_id, channel_id)
                )
            conn.commit()
            database_logger.info(f"Canal de amistosos establecido a {channel_id} para guild {guild_id}")
    except sqlite3.Error as e:
        database_logger.error(f"Error al establecer canal de amistosos para guild {guild_id}: {e}")

def get_server_config(guild_id: int) -> dict:
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute('SELECT * FROM server_config WHERE guild_id = ?', (guild_id,))
            row = cur.fetchone()
            if row:
                config = dict(row)
                config['ss_channel_ids'] = [int(id.strip()) for id in config['ss_channel_ids'].split(',')] if config['ss_channel_ids'] else []
                return config
            return None
    except sqlite3.Error as e:
        database_logger.error(f"Error al obtener configuración del servidor para guild {guild_id}: {e}")
        return None

def reset_transferable_status(guild_id: int):
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute('UPDATE players SET transferable = 0')
            conn.commit()
            database_logger.info(f"Estado transferable reiniciado a 0 para todos los jugadores en guild {guild_id}.")
    except sqlite3.Error as e:
        database_logger.error(f"Error al reiniciar transferable en guild {guild_id}: {e}")

def _row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row) if row else None

def add_team(guild_id: int, name: str, division: str, manager_id: int = None) -> bool:
    db_path = get_db_path(guild_id)
    if not name or not division:
        return False
    if manager_id and get_team_by_manager(guild_id, manager_id):
        return False
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute('INSERT INTO teams(name, manager_id, division) VALUES (?, ?, ?)', (name, manager_id, division))
            team_id = cur.lastrowid
            cur.execute('INSERT OR IGNORE INTO club_balance(team_id, balance) VALUES (?, 0)', (team_id,))
            conn.commit()
            database_logger.info(f"Equipo {name} creado con ID {team_id} en división {division} en guild {guild_id}.")
        return True
    except sqlite3.IntegrityError:
        database_logger.warning(f"Intento de crear equipo duplicado: {name} en guild {guild_id}")
        return False

def delete_team(guild_id: int, team_name: str) -> bool:
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute('SELECT id FROM teams WHERE name = ?', (team_name,))
            team = cur.fetchone()
            if not team:
                return False
            team_id = team[0]
            cur.execute('UPDATE players SET team_id = NULL, contract_duration = NULL, release_clause = NULL, transferable = 0 WHERE team_id = ?', (team_id,))
            cur.execute('DELETE FROM transfer_offers WHERE from_team_id = ? OR to_team_id = ?', (team_id, team_id))
            cur.execute('DELETE FROM club_balance WHERE team_id = ?', (team_id,))
            cur.execute('DELETE FROM team_captains WHERE team_id = ?', (team_id,))
            cur.execute('DELETE FROM amistosos WHERE team1_id = ? OR team2_id = ?', (team_id, team_id))
            cur.execute('DELETE FROM solicitudes_amistosos WHERE solicitante_team_id = ? OR solicitado_team_id = ?', (team_id, team_id))
            cur.execute('DELETE FROM teams WHERE id = ?', (team_id,))
            conn.commit()
            database_logger.info(f"Equipo {team_name} eliminado en guild {guild_id}.")
        return True
    except sqlite3.Error as e:
        database_logger.error(f"Error al eliminar equipo {team_name} en guild {guild_id}: {e}")
        return False

def get_team_by_manager(guild_id: int, manager_id: int) -> dict:
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute('SELECT * FROM teams WHERE manager_id = ?', (manager_id,))
            return _row_to_dict(cur.fetchone())
    except sqlite3.Error as e:
        database_logger.error(f"Error al obtener equipo por manager {manager_id} en guild {guild_id}: {e}")
        return None

def get_team_by_name(guild_id: int, name: str) -> dict:
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute('SELECT * FROM teams WHERE name = ?', (name,))
            return _row_to_dict(cur.fetchone())
    except sqlite3.Error as e:
        database_logger.error(f"Error al obtener equipo por nombre {name} en guild {guild_id}: {e}")
        return None

def get_team_by_id(guild_id: int, team_id: int) -> dict:
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute('SELECT * FROM teams WHERE id = ?', (team_id,))
            return _row_to_dict(cur.fetchone())
    except sqlite3.Error as e:
        database_logger.error(f"Error al obtener equipo por ID {team_id} en guild {guild_id}: {e}")
        return None

def get_all_teams(guild_id: int, division: str = None) -> list:
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            if division:
                cur.execute('SELECT * FROM teams WHERE division = ? ORDER BY name', (division,))
            else:
                cur.execute('SELECT * FROM teams ORDER BY name')
            return [dict(row) for row in cur.fetchall()]
    except sqlite3.Error as e:
        database_logger.error(f"Error al obtener equipos en guild {guild_id}: {e}")
        return []

def assign_manager_to_team(guild_id: int, team_id: int, manager_id: int):
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute('UPDATE teams SET manager_id = ? WHERE id = ?', (manager_id, team_id))
            conn.commit()
            database_logger.info(f"Manager {manager_id} asignado al equipo {team_id} en guild {guild_id}.")
    except sqlite3.Error as e:
        database_logger.error(f"Error al asignar manager {manager_id} al equipo {team_id} en guild {guild_id}: {e}")

def add_player(guild_id: int, name: str, user_id: int, team_id: int = None) -> bool:
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute('INSERT INTO players(user_id, name, team_id) VALUES (?, ?, ?)', (user_id, name, team_id))
            conn.commit()
            database_logger.info(f"Jugador {name} (ID: {user_id}) agregado en guild {guild_id}.")
        return True
    except sqlite3.IntegrityError:
        database_logger.warning(f"Intento de agregar jugador duplicado con ID {user_id} en guild {guild_id}")
        return False

def get_player_by_id(guild_id: int, user_id: int) -> dict:
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute('SELECT * FROM players WHERE user_id = ?', (user_id,))
            return _row_to_dict(cur.fetchone())
    except sqlite3.Error as e:
        database_logger.error(f"Error al obtener jugador por ID {user_id} en guild {guild_id}: {e}")
        return None

def ban_player(guild_id: int, user_id: int):
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute('UPDATE players SET banned = 1 WHERE user_id = ?', (user_id,))
            conn.commit()
            database_logger.info(f"Jugador con ID {user_id} baneado en guild {guild_id}.")
    except sqlite3.Error as e:
        database_logger.error(f"Error al banear jugador con ID {user_id} en guild {guild_id}: {e}")

def unban_player(guild_id: int, user_id: int):
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute('UPDATE players SET banned = 0 WHERE user_id = ?', (user_id,))
            conn.commit()
            database_logger.info(f"Jugador con ID {user_id} desbaneado en guild {guild_id}.")
    except sqlite3.Error as e:
        database_logger.error(f"Error al desbanear jugador con ID {user_id} en guild {guild_id}: {e}")

def remove_player_from_team(guild_id: int, user_id: int) -> bool:
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute('UPDATE players SET team_id = NULL, contract_duration = NULL, release_clause = NULL, transferable = 0 WHERE user_id = ?', (user_id,))
            if cur.rowcount > 0:
                conn.commit()
                database_logger.info(f"Jugador con ID {user_id} removido de su equipo en guild {guild_id}.")
                return True
            return False
    except sqlite3.Error as e:
        database_logger.error(f"Error al quitar jugador con ID {user_id} del equipo en guild {guild_id}: {e}")
        return False

def get_transferable_players(guild_id: int) -> list:
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute('''
                SELECT p.user_id, p.name, p.team_id, p.release_clause 
                FROM players p
                LEFT JOIN teams t ON p.user_id = t.manager_id
                WHERE p.transferable = 1 AND t.manager_id IS NULL
            ''')
            rows = cur.fetchall()
        return [{'user_id': r['user_id'], 'name': r['name'], 'team_id': r['team_id'], 'release_clause': r['release_clause']} for r in rows]
    except sqlite3.Error as e:
        database_logger.error(f"Error al obtener jugadores transferibles en guild {guild_id}: {e}")
        return []

def set_player_transferable(guild_id: int, user_id: int, new_clause: int = None) -> bool:
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            if new_clause is not None:
                cur.execute('SELECT release_clause FROM players WHERE user_id = ?', (user_id,))
                current_clause = cur.fetchone()
                original_clause = current_clause[0] if current_clause else None
                cur.execute('UPDATE players SET transferable = 1, release_clause = ?, original_release_clause = ? WHERE user_id = ?', 
                           (new_clause, original_clause, user_id))
            else:
                cur.execute('UPDATE players SET transferable = 1 WHERE user_id = ?', (user_id,))
            if cur.rowcount > 0:
                conn.commit()
                database_logger.info(f"Jugador con ID {user_id} marcado como transferible con cláusula {new_clause if new_clause else 'sin cambios'} en guild {guild_id}.")
                return True
            return False
    except sqlite3.Error as e:
        database_logger.error(f"Error al marcar jugador con ID {user_id} como transferible en guild {guild_id}: {e}")
        return False

def unset_player_transferable(guild_id: int, user_id: int) -> bool:
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute('SELECT original_release_clause FROM players WHERE user_id = ?', (user_id,))
            original_clause = cur.fetchone()
            if original_clause and original_clause[0] is not None:
                cur.execute('UPDATE players SET transferable = 0, release_clause = ?, original_release_clause = NULL WHERE user_id = ?', 
                           (original_clause[0], user_id))
            else:
                cur.execute('UPDATE players SET transferable = 0 WHERE user_id = ?', (user_id,))
            if cur.rowcount > 0:
                conn.commit()
                database_logger.info(f"Jugador con ID {user_id} removido de transferibles en guild {guild_id}.")
                return True
            return False
    except sqlite3.Error as e:
        database_logger.error(f"Error al quitar estado transferible a jugador con ID {user_id} en guild {guild_id}: {e}")
        return False

def create_transfer_offer(guild_id: int, player_id: int, from_team_id: int, to_team_id: int, from_manager_id: int, clause: int, duration: int, price: int) -> int:
    if get_market_status(guild_id) != 'open':
        database_logger.warning(f"Mercado cerrado en guild {guild_id}. No se puede crear oferta.")
        return -2
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            # Verificar que el jugador exista
            cur.execute('SELECT 1 FROM players WHERE user_id = ?', (player_id,))
            if not cur.fetchone():
                database_logger.error(f"Jugador con ID {player_id} no encontrado en guild {guild_id}.")
                return -3
            cur.execute('''
                INSERT INTO transfer_offers (player_id, from_team_id, to_team_id, from_manager_id, price, status, contract_duration, release_clause)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (player_id, from_team_id, to_team_id, from_manager_id, price, 'pending', duration, clause))
            offer_id = cur.lastrowid
            conn.commit()
            database_logger.info(f"Oferta de transferencia {offer_id} creada para jugador con ID {player_id} en guild {guild_id}.")
            return offer_id
    except sqlite3.Error as e:
        database_logger.error(f"Error al crear oferta de transferencia para jugador con ID {player_id} en guild {guild_id}: {e}")
        return -1

def get_offer(guild_id: int, offer_id: int) -> dict:
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute('SELECT * FROM transfer_offers WHERE id = ?', (offer_id,))
            return _row_to_dict(cur.fetchone())
    except sqlite3.Error as e:
        database_logger.error(f"Error al obtener oferta {offer_id} en guild {guild_id}: {e}")
        return None

def update_offer_status(guild_id: int, offer_id: int, status: str):
    if status not in VALID_STATUSES:
        database_logger.warning(f"Estado inválido {status} para oferta {offer_id} en guild {guild_id}")
        return
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute('UPDATE transfer_offers SET status = ? WHERE id = ?', (status, offer_id))
            conn.commit()
            database_logger.info(f"Oferta {offer_id} actualizada a estado {status} en guild {guild_id}.")
    except sqlite3.Error as e:
        database_logger.error(f"Error al actualizar oferta {offer_id} en guild {guild_id}: {e}")

def accept_offer(guild_id: int, offer_id: int) -> bool:
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute('SELECT * FROM transfer_offers WHERE id = ?', (offer_id,))
            offer = cur.fetchone()
            if not offer or offer['status'] != 'pending':
                database_logger.warning(f"Oferta {offer_id} no válida o no está pendiente en guild {guild_id}.")
                return False
            player = get_player_by_id(guild_id, offer['player_id'])
            if not player:
                database_logger.error(f"Jugador con ID {offer['player_id']} no encontrado para oferta {offer_id} en guild {guild_id}.")
                return False
            from_team_id = offer['from_team_id']
            to_team_id = offer['to_team_id']
            cur.execute('SELECT balance FROM club_balance WHERE team_id = ?', (to_team_id,))
            balance = cur.fetchone()
            if not balance or balance['balance'] < offer['price']:
                database_logger.warning(f"Fondos insuficientes para oferta {offer_id} en guild {guild_id}.")
                return False
            cur.execute('UPDATE club_balance SET balance = balance - ? WHERE team_id = ?', (offer['price'], to_team_id))
            if from_team_id:
                cur.execute('UPDATE club_balance SET balance = balance + ? WHERE team_id = ?', (offer['price'], from_team_id))
            cur.execute('UPDATE players SET team_id = ?, contract_duration = ?, release_clause = ? WHERE user_id = ?', 
                       (to_team_id, offer['contract_duration'], offer['release_clause'], offer['player_id']))
            cur.execute('UPDATE transfer_offers SET status = ? WHERE id = ?', ('accepted', offer_id))
            conn.commit()
            database_logger.info(f"Oferta {offer_id} aceptada en guild {guild_id}.")
            return True
    except sqlite3.Error as e:
        database_logger.error(f"Error al aceptar oferta {offer_id} en guild {guild_id}: {e}")
        return False

def reject_offer(guild_id: int, offer_id: int):
    update_offer_status(guild_id, offer_id, 'rejected')

def list_offers_by_manager(guild_id: int, manager_id: int, status: str) -> list:
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute('SELECT t.*, p.name FROM transfer_offers t JOIN players p ON t.player_id = p.user_id WHERE from_manager_id = ? AND status = ?', (manager_id, status))
            return [dict(row) for row in cur.fetchall()]
    except sqlite3.Error as e:
        database_logger.error(f"Error al listar ofertas por manager {manager_id} en guild {guild_id}: {e}")
        return []

def list_offers_for_player(guild_id: int, user_id: int, status: str) -> list:
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute('SELECT t.*, p.name FROM transfer_offers t JOIN players p ON t.player_id = p.user_id WHERE p.user_id = ? AND t.status = ?', (user_id, status))
            return [dict(row) for row in cur.fetchall()]
    except sqlite3.Error as e:
        database_logger.error(f"Error al listar ofertas para jugador {user_id} en guild {guild_id}: {e}")
        return []

def has_pending_offer(guild_id: int, manager_id: int, user_id: int) -> bool:
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute('SELECT 1 FROM transfer_offers WHERE from_manager_id = ? AND player_id = ? AND status IN ("pending", "bought_clause")', (manager_id, user_id))
            return cur.fetchone() is not None
    except sqlite3.Error as e:
        database_logger.error(f"Error al verificar oferta pendiente para manager {manager_id} y jugador {user_id} en guild {guild_id}: {e}")
        return False

def pay_clause_and_transfer(guild_id: int, player_id: int, to_team_id: int, price: int, manager_id: int) -> int:
    if get_market_status(guild_id) != 'open':
        database_logger.warning(f"Mercado cerrado en guild {guild_id}. No se puede pagar cláusula.")
        return -2
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute('SELECT * FROM players WHERE user_id = ?', (player_id,))
            player = cur.fetchone()
            if not player:
                database_logger.error(f"Jugador con ID {player_id} no encontrado en guild {guild_id}.")
                return -1
            from_team_id = player['team_id']
            cur.execute('SELECT balance FROM club_balance WHERE team_id = ?', (to_team_id,))
            balance = cur.fetchone()
            if not balance or balance['balance'] < price:
                database_logger.warning(f"Fondos insuficientes para pagar cláusula de jugador con ID {player_id} en guild {guild_id}.")
                return -1
            cur.execute('UPDATE club_balance SET balance = balance - ? WHERE team_id = ?', (price, to_team_id))
            if from_team_id:
                cur.execute('UPDATE club_balance SET balance = balance + ? WHERE team_id = ?', (price, from_team_id))
            cur.execute('INSERT INTO transfer_offers (player_id, from_team_id, to_team_id, from_manager_id, price, status, release_clause) VALUES (?, ?, ?, ?, ?, ?, ?)',
                       (player_id, from_team_id, to_team_id, manager_id, price, 'bought_clause', price))
            offer_id = cur.lastrowid
            conn.commit()
            database_logger.info(f"Oferta por cláusula {offer_id} creada para jugador con ID {player_id} en guild {guild_id}.")
            return offer_id
    except sqlite3.Error as e:
        database_logger.error(f"Error al pagar cláusula para jugador con ID {player_id} en guild {guild_id}: {e}")
        return -1

def accept_clause_payment(guild_id: int, offer_id: int) -> bool:
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute('SELECT * FROM transfer_offers WHERE id = ?', (offer_id,))
            offer = cur.fetchone()
            if not offer or offer['status'] != 'bought_clause':
                database_logger.warning(f"Oferta {offer_id} no válida o no está en estado 'bought_clause' en guild {guild_id}.")
                return False
            player = get_player_by_id(guild_id, offer['player_id'])
            if not player:
                database_logger.error(f"Jugador con ID {offer['player_id']} no encontrado para oferta {offer_id} en guild {guild_id}.")
                return False
            cur.execute('UPDATE players SET team_id = ?, contract_duration = NULL, release_clause = ? WHERE user_id = ?', 
                       (offer['to_team_id'], offer['release_clause'], offer['player_id']))
            cur.execute('UPDATE transfer_offers SET status = ? WHERE id = ?', ('accepted', offer_id))
            conn.commit()
            database_logger.info(f"Pago de cláusula {offer_id} aceptado en guild {guild_id}.")
            return True
    except sqlite3.Error as e:
        database_logger.error(f"Error al aceptar pago de cláusula {offer_id} en guild {guild_id}: {e}")
        return False

def get_club_balance(guild_id: int, team_id: int) -> int:
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute('SELECT balance FROM club_balance WHERE team_id = ?', (team_id,))
            balance = cur.fetchone()
            return balance[0] if balance else 0
    except sqlite3.Error as e:
        database_logger.error(f"Error al obtener balance del equipo {team_id} en guild {guild_id}: {e}")
        return 0

def add_money_to_club(guild_id: int, team_id: int, amount: int):
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute('INSERT OR REPLACE INTO club_balance (team_id, balance) VALUES (?, COALESCE((SELECT balance FROM club_balance WHERE team_id = ?), 0) + ?)', 
                       (team_id, team_id, amount))
            conn.commit()
            database_logger.info(f"{amount} agregado al balance del equipo {team_id} en guild {guild_id}.")
    except sqlite3.Error as e:
        database_logger.error(f"Error al agregar dinero al equipo {team_id} en guild {guild_id}: {e}")

def remove_money_from_club(guild_id: int, team_id: int, amount: int):
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute('INSERT OR REPLACE INTO club_balance (team_id, balance) VALUES (?, COALESCE((SELECT balance FROM club_balance WHERE team_id = ?), 0) - ?)', 
                       (team_id, team_id, amount))
            conn.commit()
            database_logger.info(f"{amount} quitado del balance del equipo {team_id} en guild {guild_id}.")
    except sqlite3.Error as e:
        database_logger.error(f"Error al quitar dinero del equipo {team_id} en guild {guild_id}: {e}")

def get_free_agents(guild_id: int) -> list:
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute('SELECT * FROM players WHERE team_id IS NULL')
            return [dict(row) for row in cur.fetchall()]
    except sqlite3.Error as e:
        database_logger.error(f"Error al obtener agentes libres en guild {guild_id}: {e}")
        return []

def add_captain(guild_id: int, team_id: int, captain_id: int) -> bool:
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute('INSERT INTO team_captains (team_id, captain_id) VALUES (?, ?)', (team_id, captain_id))
            conn.commit()
            database_logger.info(f"Capitán {captain_id} agregado al equipo {team_id} en guild {guild_id}.")
            return True
    except sqlite3.IntegrityError:
        database_logger.warning(f"Intento de agregar capitán duplicado {captain_id} al equipo {team_id} en guild {guild_id}")
        return False
    except sqlite3.Error as e:
        database_logger.error(f"Error al agregar capitán {captain_id} al equipo {team_id} en guild {guild_id}: {e}")
        return False

def remove_captain(guild_id: int, team_id: int, captain_id: int) -> bool:
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute('DELETE FROM team_captains WHERE team_id = ? AND captain_id = ?', (team_id, captain_id))
            if cur.rowcount > 0:
                conn.commit()
                database_logger.info(f"Capitán {captain_id} removido del equipo {team_id} en guild {guild_id}.")
                return True
            return False
    except sqlite3.Error as e:
        database_logger.error(f"Error al remover capitán {captain_id} del equipo {team_id} en guild {guild_id}: {e}")
        return False

def get_captains(guild_id: int, team_id: int) -> list:
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute('SELECT captain_id FROM team_captains WHERE team_id = ?', (team_id,))
            return [row[0] for row in cur.fetchall()]
    except sqlite3.Error as e:
        database_logger.error(f"Error al obtener capitanes del equipo {team_id} en guild {guild_id}: {e}")
        return []

def is_captain(guild_id: int, team_id: int, user_id: int) -> bool:
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute('SELECT 1 FROM team_captains WHERE team_id = ? AND captain_id = ?', (team_id, user_id))
            return cur.fetchone() is not None
    except sqlite3.Error as e:
        database_logger.error(f"Error al verificar si {user_id} es capitán del equipo {team_id} en guild {guild_id}: {e}")
        return False

def get_team_by_captain(guild_id: int, captain_id: int) -> dict:
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute('''
                SELECT t.* FROM teams t
                JOIN team_captains tc ON t.id = tc.team_id
                WHERE tc.captain_id = ?
            ''', (captain_id,))
            return _row_to_dict(cur.fetchone())
    except sqlite3.Error as e:
        database_logger.error(f"Error al obtener equipo por capitán {captain_id} en guild {guild_id}: {e}")
        return None

def get_solicitud_by_id(guild_id: int, solicitud_id: int) -> dict:
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute('SELECT * FROM solicitudes_amistosos WHERE id = ?', (solicitud_id,))
            return _row_to_dict(cur.fetchone())
    except sqlite3.Error as e:
        database_logger.error(f"Error al obtener solicitud {solicitud_id} en guild {guild_id}: {e}")
        return None

def update_solicitud_status(guild_id: int, solicitud_id: int, status: str, user_id: int):
    db_path = get_db_path(guild_id)
    solicitud = get_solicitud_by_id(guild_id, solicitud_id)
    if not solicitud:
        return
    team = get_team_by_id(guild_id, solicitud['solicitado_team_id'])
    if not team or (team['manager_id'] != user_id and not is_captain(guild_id, solicitud['solicitado_team_id'], user_id)):
        database_logger.warning(f"Usuario {user_id} no autorizado para actualizar solicitud {solicitud_id} en guild {guild_id}")
        return
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute('UPDATE solicitudes_amistosos SET status = ? WHERE id = ?', (status, solicitud_id))
            conn.commit()
            Daiquiri - Mensajes directos están desactivados para este usuario.
            database_logger.info(f"Solicitud {solicitud_id} actualizada a estado {status} en guild {guild_id}")
    except sqlite3.Error as e:
        database_logger.error(f"Error al actualizar solicitud {solicitud_id} en guild {guild_id}: {e}")

def get_players_by_team(guild_id: int, team_id: int) -> list:
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute('SELECT * FROM players WHERE team_id = ?', (team_id,))
            return [dict(row) for row in cur.fetchall()]
    except sqlite3.Error as e:
        database_logger.error(f"Error al obtener jugadores del equipo {team_id} en guild {guild_id}: {e}")
        return []

def advance_season(guild_id: int):
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute('UPDATE players SET contract_duration = contract_duration - 1 WHERE contract_duration > 0')
            cur.execute('UPDATE players SET team_id = NULL, contract_duration = NULL, release_clause = NULL, transferable = 0 WHERE contract_duration <= 0')
            conn.commit()
            database_logger.info(f"Temporada avanzada en guild {guild_id}. Contratos actualizados.")
    except sqlite3.Error as e:
        database_logger.error(f"Error al avanzar temporada en guild {guild_id}: {e}")

def get_transfer_history_by_player(guild_id: int, user_id: int) -> list:
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute('''
                SELECT t.id, t.player_id, t.price, t.status, t1.name AS from_team_name, t2.name AS to_team_name, p.name AS player_name
                FROM transfer_offers t
                JOIN players p ON t.player_id = p.user_id
                LEFT JOIN teams t1 ON t.from_team_id = t1.id
                LEFT JOIN teams t2 ON t.to_team_id = t2.id
                WHERE t.player_id = ? AND t.status IN ('accepted', 'finalized')
            ''', (user_id,))
            return [f"ID {row['id']}: {row['player_name']} de {row['from_team_name'] or 'Libre'} a {row['to_team_name'] or 'Libre'} por {row['price']:,} [{row['status']}]" 
                   for row in cur.fetchall()]
    except sqlite3.Error as e:
        database_logger.error(f"Error al obtener historial de transferencias para jugador con ID {user_id} en guild {guild_id}: {e}")
        return []

def get_transfer_history_by_team(guild_id: int, team_id: int) -> list:
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute('''
                SELECT t.id, t.player_id, t.price, t.status, t1.name AS from_team_name, t2.name AS to_team_name, p.name AS player_name
                FROM transfer_offers t
                JOIN players p ON t.player_id = p.user_id
                LEFT JOIN teams t1 ON t.from_team_id = t1.id
                LEFT JOIN teams t2 ON t.to_team_id = t2.id
                WHERE (t.from_team_id = ? OR t.to_team_id = ?) AND t.status IN ('accepted', 'finalized')
            ''', (team_id, team_id))
            return [f"ID {row['id']}: {row['player_name']} de {row['from_team_name'] or 'Libre'} a {row['to_team_name'] or 'Libre'} por {row['price']:,} [{row['status']}]" 
                   for row in cur.fetchall()]
    except sqlite3.Error as e:
        database_logger.error(f"Error al obtener historial de transferencias para equipo {team_id} en guild {guild_id}: {e}")
        return []

def get_recent_transfers(guild_id: int, limit: int) -> list:
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute('''
                SELECT t.id, t.player_id, t.price, t.status, t1.name AS from_team_name, t2.name AS to_team_name, p.name AS player_name
                FROM transfer_offers t
                JOIN players p ON t.player_id = p.user_id
                LEFT JOIN teams t1 ON t.from_team_id = t1.id
                LEFT JOIN teams t2 ON t.to_team_id = t2.id
                WHERE t.status IN ('accepted', 'finalized')
                ORDER BY t.id DESC
                LIMIT ?
            ''', (limit,))
            return [dict(row) for row in cur.fetchall()]
    except sqlite3.Error as e:
        database_logger.error(f"Error al obtener transferencias recientes en guild {guild_id}: {e}")
        return []

def add_screenshot(guild_id: int, user_id: int, nicktag: str, discord_name: str, channel_id: int, image_url: str, screenshot_time: str) -> int:
    db_path = get_db_path(guild_id)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute('''
                INSERT INTO screenshots (user_id, nicktag, discord_name, channel_id, timestamp, screenshot_time, status, image_url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, nicktag, discord_name, channel_id, timestamp, screenshot_time, 'pending', image_url))
            screenshot_id = cur.lastrowid
            conn.commit()
            database_logger.info(f"Captura {screenshot_id} agregada para usuario {user_id} en guild {guild_id}.")
            return screenshot_id
    except sqlite3.Error as e:
        database_logger.error(f"Error al agregar captura para usuario {user_id} en guild {guild_id}: {e}")
        return -1

def update_screenshot_status(guild_id: int, screenshot_id: int, status: str):
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute('UPDATE screenshots SET status = ? WHERE id = ?', (status, screenshot_id))
            conn.commit()
            database_logger.info(f"Captura {screenshot_id} actualizada a estado {status} en guild {guild_id}.")
    except sqlite3.Error as e:
        database_logger.error(f"Error al actualizar captura {screenshot_id} en guild {guild_id}: {e}")

def get_screenshots_by_user(guild_id: int, user_id: int) -> list:
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute('SELECT * FROM screenshots WHERE user_id = ?', (user_id,))
            return [dict(row) for row in cur.fetchall()]
    except sqlite3.Error as e:
        database_logger.error(f"Error al obtener capturas para usuario {user_id} en guild {guild_id}: {e}")
        return []

def export_database_to_file(guild_id: int = None):
    if guild_id is None:
        db_path = GLOBAL_DB_PATH
        prefix = "global"
    else:
        db_path = get_db_path(guild_id)
        prefix = f"guild_{guild_id}"
    try:
        backup_dir = "backups"
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir)
            database_logger.info(f"Carpeta {backup_dir} creada.")
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = os.path.join(backup_dir, f"db_backup_{prefix}_{timestamp}.txt")
        
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            
            with open(backup_file, "w", encoding="utf-8") as f:
                f.write("=== Copia de la Base de Datos ===\n")
                f.write(f"Fecha y hora: {timestamp}\n")
                f.write(f"Guild ID: {guild_id if guild_id else 'Global'}\n\n")
                
                if guild_id:
                    f.write("=== Tabla 'teams' ===\n")
                    cur.execute('SELECT * FROM teams')
                    teams = cur.fetchall()
                    if teams:
                        for team in teams:
                            f.write(f"ID: {team['id']}, Name: {team['name']}, Manager ID: {team['manager_id'] or 'None'}, Division: {team['division']}\n")
                    else:
                        f.write("No hay equipos registrados.\n")
                    f.write("\n")
                    
                    f.write("=== Tabla 'players' ===\n")
                    cur.execute('SELECT * FROM players')
                    players = cur.fetchall()
                    if players:
                        for player in players:
                            f.write(f"User ID: {player['user_id']}, Name: {player['name']}, Team ID: {player['team_id'] or 'None'}, "
                                   f"Transferable: {player['transferable']}, Banned: {player['banned']}, "
                                   f"Contract Duration: {player['contract_duration'] or 'None'}, "
                                   f"Release Clause: {player['release_clause'] or 'None'}, "
                                   f"Original Release Clause: {player['original_release_clause'] or 'None'}\n")
                    else:
                        f.write("No hay jugadores registrados.\n")
                    f.write("\n")
                    
                    f.write("=== Tabla 'transfer_offers' ===\n")
                    cur.execute('SELECT t.*, p.name AS player_name FROM transfer_offers t JOIN players p ON t.player_id = p.user_id')
                    offers = cur.fetchall()
                    if offers:
                        for offer in offers:
                            f.write(f"ID: {offer['id']}, Player ID: {offer['player_id']}, Player Name: {offer['player_name']}, "
                                   f"From Team ID: {offer['from_team_id'] or 'None'}, To Team ID: {offer['to_team_id'] or 'None'}, "
                                   f"From Manager ID: {offer['from_manager_id'] or 'None'}, To Manager ID: {offer['to_manager_id'] or 'None'}, "
                                   f"Price: {offer['price']}, Status: {offer['status']}, Contract Duration: {offer['contract_duration'] or 'None'}, "
                                   f"Release Clause: {offer['release_clause'] or 'None'}\n")
                    else:
                        f.write("No hay ofertas de transferencia registradas.\n")
                    f.write("\n")
                    
                    f.write("=== Tabla 'club_balance' ===\n")
                    cur.execute('SELECT * FROM club_balance')
                    balances = cur.fetchall()
                    if balances:
                        for balance in balances:
                            f.write(f"Team ID: {balance['team_id']}, Balance: {balance['balance']}\n")
                    else:
                        f.write("No hay balances registrados.\n")
                    f.write("\n")
                    
                    f.write("=== Tabla 'team_captains' ===\n")
                    cur.execute('SELECT * FROM team_captains')
                    captains = cur.fetchall()
                    if captains:
                        for captain in captains:
                            f.write(f"Team ID: {captain['team_id']}, Captain ID: {captain['captain_id']}\n")
                    else:
                        f.write("No hay capitanes registrados.\n")
                    f.write("\n")
                    
                    f.write("=== Tabla 'guild_config' ===\n")
                    cur.execute('SELECT * FROM guild_config')
                    configs = cur.fetchall()
                    if configs:
                        for config in configs:
                            f.write(f"Key: {config['key']}, Value: {config['value']}\n")
                    else:
                        f.write("No hay configuraciones registradas.\n")
                    f.write("\n")
                    
                    f.write("=== Tabla 'server_config' ===\n")
                    cur.execute('SELECT * FROM server_config')
                    server_configs = cur.fetchall()
                    if server_configs:
                        for config in server_configs:
                            f.write(f"Guild ID: {config['guild_id']}, SS Channel IDs: {config['ss_channel_ids'] or 'None'}, "
                                   f"Amistosos Channel ID: {config['amistosos_channel_id'] or 'None'}, Arbiter Role ID: {config['arbiter_role_id'] or 'None'}, "
                                   f"Registro Channel ID: {config['registro_channel_id'] or 'None'}\n")
                    else:
                        f.write("No hay configuraciones de servidor registradas.\n")
                    f.write("\n")
                    
                    f.write("=== Tabla 'screenshots' ===\n")
                    cur.execute('SELECT * FROM screenshots')
                    screenshots = cur.fetchall()
                    if screenshots:
                        for ss in screenshots:
                            f.write(f"ID: {ss['id']}, User ID: {ss['user_id']}, Nicktag: {ss['nicktag']}, Discord Name: {ss['discord_name']}, "
                                   f"Channel ID: {ss['channel_id']}, Timestamp: {ss['timestamp']}, Screenshot Time: {ss['screenshot_time'] or 'None'}, "
                                   f"Status: {ss['status']}, Image URL: {ss['image_url']}\n")
                    else:
                        f.write("No hay capturas registradas.\n")
                    f.write("\n")
                    
                    f.write("=== Tabla 'amistosos_tablas' ===\n")
                    cur.execute('SELECT * FROM amistosos_tablas')
                    tablas = cur.fetchall()
                    if tablas:
                        for tabla in tablas:
                            f.write(f"ID: {tabla['id']}, Guild ID: {tabla['guild_id']}, Created At: {tabla['created_at']}\n")
                    else:
                        f.write("No hay tablas de amistosos registradas.\n")
                    f.write("\n")
                    
                    f.write("=== Tabla 'amistosos_horarios' ===\n")
                    cur.execute('SELECT * FROM amistosos_horarios')
                    horarios = cur.fetchall()
                    if horarios:
                        for horario in horarios:
                            f.write(f"ID: {horario['id']}, Tabla ID: {horario['tabla_id']}, Horario: {horario['horario']}, Disponible: {horario['disponible']}\n")
                    else:
                        f.write("No hay horarios de amistosos registrados.\n")
                    f.write("\n")
                    
                    f.write("=== Tabla 'amistosos' ===\n")
                    cur.execute('SELECT * FROM amistosos')
                    amistosos = cur.fetchall()
                    if amistosos:
                        for amistoso in amistosos:
                            f.write(f"ID: {amistoso['id']}, Tabla ID: {amistoso['tabla_id']}, Horario: {amistoso['horario']}, "
                                   f"Team1 ID: {amistoso['team1_id']}, Team2 ID: {amistoso['team2_id']}, Status: {amistoso['status']}\n")
                    else:
                        f.write("No hay amistosos registrados.\n")
                    f.write("\n")
                    
                    f.write("=== Tabla 'solicitudes_amistosos' ===\n")
                    cur.execute('SELECT * FROM solicitudes_amistosos')
                    solicitudes = cur.fetchall()
                    if solicitudes:
                        for solicitud in solicitudes:
                            f.write(f"ID: {solicitud['id']}, Tabla ID: {solicitud['tabla_id']}, Horario: {solicitud['horario']}, "
                                   f"Solicitante Team ID: {solicitud['solicitante_team_id']}, Solicitado Team ID: {solicitud['solicitado_team_id']}, "
                                   f"Status: {solicitud['status']}\n")
                    else:
                        f.write("No hay solicitudes de amistosos registradas.\n")
                
                else:
                    f.write("=== Tabla 'banned_guilds' ===\n")
                    cur.execute('SELECT * FROM banned_guilds')
                    banned_guilds = cur.fetchall()
                    if banned_guilds:
                        for guild in banned_guilds:
                            f.write(f"Guild ID: {guild['guild_id']}\n")
                    else:
                        f.write("No hay guilds baneados.\n")
                
                database_logger.info(f"Base de datos exportada a {backup_file}.")
    except sqlite3.Error as e:
        database_logger.error(f"Error al exportar base de datos para guild {guild_id or 'global'}: {e}")

def generate_horarios(inicio: str, fin: str) -> list:
    try:
        inicio_dt = datetime.strptime(inicio, "%H:%M")
        fin_dt = datetime.strptime(fin, "%H:%M")
        if fin_dt < inicio_dt:
            fin_dt += timedelta(days=1)
        horarios = []
        current = inicio_dt
        while current <= fin_dt:
            horarios.append(current.strftime("%H:%M"))
            current += timedelta(minutes=30)
        return horarios
    except ValueError:
        return []

def set_registro_channel(guild_id: int, channel_id: int):
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE server_config SET registro_channel_id = ? WHERE guild_id = ?",
                (channel_id, guild_id)
            )
            if cur.rowcount == 0:
                cur.execute(
                    "INSERT INTO server_config (guild_id, registro_channel_id) VALUES (?, ?)",
                    (guild_id, channel_id)
                )
            conn.commit()
            database_logger.info(f"Canal de registros establecido a {channel_id} para guild {guild_id}")
    except sqlite3.Error as e:
        database_logger.error(f"Error al establecer canal de registros para guild {guild_id}: {e}")

def create_amistosos_tabla(guild_id: int, inicio: str, fin: str) -> int:
    horarios = generate_horarios(inicio, fin)
    if not horarios:
        return -1
    try:
        with sqlite3.connect(get_db_path(guild_id)) as conn:
            cur = conn.cursor()
            cur.execute('INSERT INTO amistosos_tablas (guild_id, created_at) VALUES (?, ?)', 
                        (guild_id, datetime.now().isoformat()))
            tabla_id = cur.lastrowid
            for horario in horarios:
                cur.execute('INSERT INTO amistosos_horarios (tabla_id, horario) VALUES (?, ?)', 
                            (tabla_id, horario))
            conn.commit()
            database_logger.info(f"Tabla de amistosos {tabla_id} creada para guild {guild_id} con {len(horarios)} horarios.")
            return tabla_id
    except sqlite3.Error as e:
        database_logger.error(f"Error al crear tabla de amistosos para guild {guild_id}: {e}")
        return -1

def get_latest_amistosos_tabla(guild_id: int) -> dict:
    try:
        with sqlite3.connect(get_db_path(guild_id)) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute('SELECT * FROM amistosos_tablas WHERE guild_id = ? ORDER BY id DESC LIMIT 1', (guild_id,))
            return _row_to_dict(cur.fetchone())
    except sqlite3.Error as e:
        database_logger.error(f"Error al obtener la última tabla para guild {guild_id}: {e}")
        return None

def get_horarios_for_tabla(tabla_id: int, guild_id: int) -> list:
    try:
        with sqlite3.connect(get_db_path(guild_id)) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute('SELECT horario, disponible FROM amistosos_horarios WHERE tabla_id = ? ORDER BY horario', (tabla_id,))
            return [{'horario': row['horario'], 'disponible': row['disponible']} for row in cur.fetchall()]
    except sqlite3.Error as e:
        database_logger.error(f"Error al obtener horarios para tabla {tabla_id}: {e}")
        return []

def add_solicitud_amistoso(guild_id: int, solicitante_team_id: int, solicitado_team_id: int, horario: str, tabla_id: int, user_id: int) -> int:
    team = get_team_by_id(guild_id, solicitante_team_id)
    if not team or (team['manager_id'] != user_id and not is_captain(guild_id, solicitante_team_id, user_id)):
        database_logger.warning(f"Usuario {user_id} no autorizado para solicitar amistoso.")
        return -1
    try:
        with sqlite3.connect(get_db_path(guild_id)) as conn:
            cur = conn.cursor()
            cur.execute(
                'INSERT INTO solicitudes_amistosos (tabla_id, horario, solicitante_team_id, solicitado_team_id, status) VALUES (?, ?, ?, ?, ?)',
                (tabla_id, horario, solicitante_team_id, solicitado_team_id, 'pending')
            )
            solicitud_id = cur.lastrowid
            conn.commit()
            database_logger.info(f"Solicitud de amistoso creada con ID {solicitud_id} para guild {guild_id}")
            return solicitud_id
    except sqlite3.Error as e:
        database_logger.error(f"Error al crear solicitud de amistoso para guild {guild_id}: {e}")
        return -1

def add_amistoso(guild_id: int, team1_id: int, team2_id: int, horario: str, tabla_id: int) -> bool:
    try:
        with sqlite3.connect(get_db_path(guild_id)) as conn:
            cur = conn.cursor()
            cur.execute('INSERT INTO amistosos (tabla_id, horario, team1_id, team2_id) VALUES (?, ?, ?, ?)', 
                        (tabla_id, horario, team1_id, team2_id))
            cur.execute('UPDATE amistosos_horarios SET disponible = 0 WHERE tabla_id = ? AND horario = ?', 
                        (tabla_id, horario))
            conn.commit()
            database_logger.info(f"Amistoso agregado entre equipo {team1_id} y {team2_id} a las {horario} en tabla {tabla_id}")
            return True
    except sqlite3.Error as e:
        database_logger.error(f"Error al agregar amistoso en guild {guild_id}: {e}")
        return False

def get_amistosos_for_tabla(guild_id: int, tabla_id: int) -> list:
    try:
        with sqlite3.connect(get_db_path(guild_id)) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute('SELECT * FROM amistosos WHERE tabla_id = ?', (tabla_id,))
            return [dict(row) for row in cur.fetchall()]
    except sqlite3.Error as e:
        database_logger.error(f"Error al obtener amistosos para tabla {tabla_id}: {e}")
        return []

def delete_amistoso(guild_id: int, amistoso_id: int) -> bool:
    try:
        with sqlite3.connect(get_db_path(guild_id)) as conn:
            cur = conn.cursor()
            cur.execute('SELECT tabla_id, horario FROM amistosos WHERE id = ?', (amistoso_id,))
            row = cur.fetchone()
            if row:
                tabla_id, horario = row['tabla_id'], row['horario']
                cur.execute('DELETE FROM amistosos WHERE id = ?', (amistoso_id,))
                cur.execute('UPDATE amistosos_horarios SET disponible = 1 WHERE tabla_id = ? AND horario = ?', 
                            (tabla_id, horario))
                conn.commit()
                database_logger.info(f"Amistoso {amistoso_id} eliminado en guild {guild_id}.")
                return True
            return False
    except sqlite3.Error as e:
        database_logger.error(f"Error al eliminar amistoso {amistoso_id}: {e}")
        return False

def initialize_global():
    create_global_tables()

initialize_global()
