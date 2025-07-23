import sqlite3
import logging
import os
from datetime import datetime

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
                name TEXT PRIMARY KEY,
                user_id INTEGER UNIQUE,
                team_id INTEGER,
                transferable INTEGER DEFAULT 0,
                banned INTEGER DEFAULT 0,
                contract_duration INTEGER,
                release_clause INTEGER,
                original_release_clause INTEGER
            );
            CREATE TABLE IF NOT EXISTS transfer_offers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                player_name TEXT NOT NULL,
                from_team_id INTEGER,
                to_team_id INTEGER,
                from_manager_id INTEGER,
                to_manager_id INTEGER,
                price INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                contract_duration INTEGER,
                release_clause INTEGER,
                FOREIGN KEY(player_name) REFERENCES players(name),
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
            cur.executescript("""
            CREATE TABLE IF NOT EXISTS server_config (
                guild_id INTEGER PRIMARY KEY,
                ss_channel_id INTEGER,
                amistosos_channel_id INTEGER
            );

            """)
            conn.commit()
        database_logger.info(f"Tablas creadas/verificadas para guild {guild_id}.")
    except sqlite3.Error as e:
        database_logger.error(f"Error al crear tablas para guild {guild_id}: {e}")
        raise

def create_screenshots_table(guild_id: int):
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute('''CREATE TABLE IF NOT EXISTS screenshots (
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
            )''')
            conn.commit()
        database_logger.info(f"Tabla screenshots creada/verificada para guild {guild_id}.")
    except sqlite3.Error as e:
        database_logger.error(f"Error al crear tabla screenshots para guild {guild_id}: {e}")

def create_amistosos_tables(guild_id: int):
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.executescript("""
            CREATE TABLE IF NOT EXISTS amistosos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                team1_id INTEGER NOT NULL,
                team2_id INTEGER NOT NULL,
                hora TEXT NOT NULL,
                fecha TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'confirmed',
                FOREIGN KEY(team1_id) REFERENCES teams(id),
                FOREIGN KEY(team2_id) REFERENCES teams(id)
            );
            CREATE TABLE IF NOT EXISTS solicitudes_amistosos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                solicitante_team_id INTEGER NOT NULL,
                solicitado_team_id INTEGER NOT NULL,
                hora TEXT NOT NULL,
                fecha TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                FOREIGN KEY(solicitante_team_id) REFERENCES teams(id),
                FOREIGN KEY(solicitado_team_id) REFERENCES teams(id)
            );
            """)
            conn.commit()
        database_logger.info(f"Tablas de amistosos creadas/verificadas para guild {guild_id}.")
    except sqlite3.Error as e:
        database_logger.error(f"Error al crear tablas de amistosos para guild {guild_id}: {e}")

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
            return row[0] if row else 'closed'  # Cerrado por defecto
    except sqlite3.Error as e:
        database_logger.error(f"Error al obtener estado del mercado para guild {guild_id}: {e}")
        return 'closed'

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
            cur.execute('INSERT INTO players(name, user_id, team_id) VALUES (?, ?, ?)', (name, user_id, team_id))
            conn.commit()
            database_logger.info(f"Jugador {name} (ID: {user_id}) agregado en guild {guild_id}.")
        return True
    except sqlite3.IntegrityError:
        database_logger.warning(f"Intento de agregar jugador duplicado: {name} en guild {guild_id}")
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

def ban_player(guild_id: int, name: str):
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute('UPDATE players SET banned = 1 WHERE name = ?', (name,))
            conn.commit()
            database_logger.info(f"Jugador {name} baneado en guild {guild_id}.")
    except sqlite3.Error as e:
        database_logger.error(f"Error al banear jugador {name} en guild {guild_id}: {e}")

def unban_player(guild_id: int, name: str):
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute('UPDATE players SET banned = 0 WHERE name = ?', (name,))
            conn.commit()
            database_logger.info(f"Jugador {name} desbaneado en guild {guild_id}.")
    except sqlite3.Error as e:
        database_logger.error(f"Error al desbanear jugador {name} en guild {guild_id}: {e}")

def remove_player_from_team(guild_id: int, player_name: str) -> bool:
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute('UPDATE players SET team_id = NULL, contract_duration = NULL, release_clause = NULL WHERE name = ?', (player_name,))
            if cur.rowcount > 0:
                conn.commit()
                database_logger.info(f"Jugador {player_name} removido de su equipo en guild {guild_id}.")
                return True
            return False
    except sqlite3.Error as e:
        database_logger.error(f"Error al quitar jugador {player_name} del equipo en guild {guild_id}: {e}")
        return False

def get_transferable_players(guild_id: int) -> list:
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute('''
                SELECT p.name, p.team_id, p.release_clause 
                FROM players p
                LEFT JOIN teams t ON p.user_id = t.manager_id
                WHERE p.transferable = 1 AND t.manager_id IS NULL
            ''')
            rows = cur.fetchall()
        return [{'name': r['name'], 'team_id': r['team_id'], 'release_clause': r['release_clause']} for r in rows]
    except sqlite3.Error as e:
        database_logger.error(f"Error al obtener jugadores transferibles en guild {guild_id}: {e}")
        return []

def add_solicitud_amistoso(guild_id: int, solicitante_team_id: int, solicitado_team_id: int, hora: str, fecha: str, user_id: int) -> int:
    db_path = get_db_path(guild_id)
    team = get_team_by_id(guild_id, solicitante_team_id)
    if not team or (team['manager_id'] != user_id and not is_captain(guild_id, solicitante_team_id, user_id)):
        database_logger.warning(f"Usuario {user_id} no autorizado para solicitar amistoso para equipo {solicitante_team_id} en guild {guild_id}")
        return -1
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute('INSERT INTO solicitudes_amistosos (solicitante_team_id, solicitado_team_id, hora, fecha, status) VALUES (?, ?, ?, ?, ?)', 
                        (solicitante_team_id, solicitado_team_id, hora, fecha, 'pending'))
            conn.commit()
            cur.execute('SELECT last_insert_rowid()')
            solicitud_id = cur.fetchone()[0]
            database_logger.info(f"Solicitud de amistoso creada: ID {solicitud_id} en guild {guild_id}")
            return solicitud_id
    except sqlite3.Error as e:
        database_logger.error(f"Error al crear solicitud de amistoso en guild {guild_id}: {e}")
        return -1

def get_solicitudes_pendientes(guild_id: int, team_id: int) -> list:
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute('SELECT * FROM solicitudes_amistosos WHERE (solicitante_team_id = ? OR solicitado_team_id = ?) AND status = ?', (team_id, team_id, 'pending'))
            return [dict(row) for row in cur.fetchall()]
    except sqlite3.Error as e:
        database_logger.error(f"Error al obtener solicitudes pendientes para el equipo {team_id} en guild {guild_id}: {e}")
        return []

def get_solicitud_by_id(guild_id: int, solicitud_id: int) -> dict:
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute('SELECT * FROM solicitudes_amistosos WHERE id = ?', (solicitud_id,))
            row = cur.fetchone()
            return dict(row) if row else None
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
            database_logger.info(f"Solicitud {solicitud_id} actualizada a estado {status} en guild {guild_id}")
    except sqlite3.Error as e:
        database_logger.error(f"Error al actualizar solicitud {solicitud_id} en guild {guild_id}: {e}")

def add_amistoso(guild_id: int, team1_id: int, team2_id: int, hora: str, fecha: str) -> bool:
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute('INSERT INTO amistosos (team1_id, team2_id, hora, fecha) VALUES (?, ?, ?, ?)', (team1_id, team2_id, hora, fecha))
            conn.commit()
            database_logger.info(f"Amistoso agregado: {team1_id} vs {team2_id} a las {hora} el {fecha} en guild {guild_id}")
            return True
    except sqlite3.Error as e:
        database_logger.error(f"Error al agregar amistoso en guild {guild_id}: {e}")
        return False

def get_amistosos_del_dia(guild_id: int, fecha: str) -> list:
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute('SELECT * FROM amistosos WHERE fecha = ?', (fecha,))
            return [dict(row) for row in cur.fetchall()]
    except sqlite3.Error as e:
        database_logger.error(f"Error al obtener amistosos del día {fecha} en guild {guild_id}: {e}")
        return []

def delete_amistosos_del_dia(guild_id: int, fecha: str) -> bool:
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute('DELETE FROM amistosos WHERE fecha = ?', (fecha,))
            conn.commit()
            return True
    except sqlite3.Error as e:
        database_logger.error(f"Error al eliminar amistosos del día {fecha} en guild {guild_id}: {e}")
        return False

def set_player_transferable(guild_id: int, player_name: str, new_clause: int = None) -> bool:
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            if new_clause is not None:
                cur.execute('SELECT release_clause FROM players WHERE name = ?', (player_name,))
                current_clause = cur.fetchone()
                original_clause = current_clause[0] if current_clause else None
                cur.execute('UPDATE players SET transferable = 1, release_clause = ?, original_release_clause = ? WHERE name = ?', 
                           (new_clause, original_clause, player_name))
            else:
                cur.execute('UPDATE players SET transferable = 1 WHERE name = ?', (player_name,))
            if cur.rowcount > 0:
                conn.commit()
                database_logger.info(f"Jugador {player_name} marcado como transferible con cláusula {new_clause if new_clause else 'sin cambios'} en guild {guild_id}.")
                return True
            return False
    except sqlite3.Error as e:
        database_logger.error(f"Error al marcar jugador {player_name} como transferible en guild {guild_id}: {e}")
        return False

def unset_player_transferable(guild_id: int, player_name: str) -> bool:
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute('SELECT original_release_clause FROM players WHERE name = ?', (player_name,))
            original_clause = cur.fetchone()
            if original_clause and original_clause[0] is not None:
                cur.execute('UPDATE players SET transferable = 0, release_clause = ?, original_release_clause = NULL WHERE name = ?', 
                           (original_clause[0], player_name))
            else:
                cur.execute('UPDATE players SET transferable = 0 WHERE name = ?', (player_name,))
            if cur.rowcount > 0:
                conn.commit()
                database_logger.info(f"Jugador {player_name} removido de transferibles en guild {guild_id}.")
                return True
            return False
    except sqlite3.Error as e:
        database_logger.error(f"Error al quitar estado transferible a {player_name} en guild {guild_id}: {e}")
        return False

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
                            f.write(f"ID: {team['id']}, Name: {team['name']}, Manager ID: {team['manager_id'] or 'None'}\n")
                    else:
                        f.write("No hay equipos registrados.\n")
                    f.write("\n")
                    
                    f.write("=== Tabla 'players' ===\n")
                    cur.execute('SELECT * FROM players')
                    players = cur.fetchall()
                    if players:
                        for player in players:
                            f.write(f"Name: {player['name']}, User ID: {player['user_id']}, Team ID: {player['team_id'] or 'None'}, "
                                   f"Transferable: {player['transferable']}, Banned: {player['banned']}, "
                                   f"Contract Duration: {player['contract_duration'] or 'None'}, "
                                   f"Release Clause: {player['release_clause'] or 'None'}, "
                                   f"Original Release Clause: {player['original_release_clause'] or 'None'}\n")
                    else:
                        f.write("No hay jugadores registrados.\n")
                    f.write("\n")
                    
                    f.write("=== Tabla 'transfer_offers' ===\n")
                    cur.execute('SELECT * FROM transfer_offers')
                    offers = cur.fetchall()
                    if offers:
                        for offer in offers:
                            f.write(f"ID: {offer['id']}, Player: {offer['player_name']}, From Team ID: {offer['from_team_id'] or 'None'}, "
                                   f"To Team ID: {offer['to_team_id'] or 'None'}, From Manager ID: {offer['from_manager_id'] or 'None'}, "
                                   f"To Manager ID: {offer['to_manager_id'] or 'None'}, Price: {offer['price']}, "
                                   f"Status: {offer['status']}, Contract Duration: {offer['contract_duration'] or 'None'}, "
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
                        f.write("No hay balances de clubes registrados.\n")
                    f.write("\n")
                else:
                    f.write("=== Tabla 'banned_guilds' ===\n")
                    cur.execute('SELECT * FROM banned_guilds')
                    guilds = cur.fetchall()
                    if guilds:
                        for guild in guilds:
                            f.write(f"Guild ID: {guild['guild_id']}\n")
                    else:
                        f.write("No hay guilds baneados.\n")
                    f.write("\n")
                f.write("=====================================\n")
        
        database_logger.info(f"Copia de la base de datos guardada en {backup_file}")
    except sqlite3.Error as e:
        database_logger.error(f"Error al exportar la base de datos para {prefix}: {e}")
    except OSError as e:
        database_logger.error(f"Error al escribir el archivo de respaldo {backup_file}: {e}")

def create_transfer_offer(guild_id: int, player_name: str, from_team_id: int, to_team_id: int, from_manager_id: int, price: int, duration: int, clause: int) -> int:
    db_path = get_db_path(guild_id)
    if get_market_status(guild_id) == 'closed':
        database_logger.info(f"No se puede crear oferta en guild {guild_id}: mercado cerrado.")
        return -2
    if price <= 0 or duration <= 0 or clause <= 0:
        database_logger.warning(f"Parámetros inválidos para crear oferta en guild {guild_id}.")
        return -1
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute(
                '''INSERT INTO transfer_offers
                   (player_name, from_team_id, to_team_id, from_manager_id, price, contract_duration, release_clause, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                (player_name, from_team_id, to_team_id, from_manager_id, price, duration, clause, 'pending')
            )
            conn.commit()
            offer_id = cur.lastrowid
            database_logger.info(f"Oferta {offer_id} creada para {player_name} en guild {guild_id}.")
            return offer_id
    except sqlite3.Error as e:
        database_logger.error(f"Error al crear oferta para {player_name} en guild {guild_id}: {e}")
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

def update_offer_status(guild_id: int, offer_id: int, new_status: str) -> bool:
    db_path = get_db_path(guild_id)
    if new_status not in VALID_STATUSES:
        database_logger.warning(f"Estado inválido para oferta {offer_id} en guild {guild_id}: {new_status}")
        return False
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute('UPDATE transfer_offers SET status = ? WHERE id = ?', (new_status, offer_id))
            conn.commit()
            database_logger.info(f"Estado de oferta {offer_id} actualizado a {new_status} en guild {guild_id}.")
        return True
    except sqlite3.Error as e:
        database_logger.error(f"Error al actualizar estado de oferta {offer_id} en guild {guild_id}: {e}")
        return False

def accept_offer(guild_id: int, offer_id: int):
    db_path = get_db_path(guild_id)
    if get_market_status(guild_id) == 'closed':
        database_logger.info(f"No se puede aceptar oferta {offer_id} en guild {guild_id}: mercado cerrado.")
        return
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute('SELECT player_name, to_team_id, contract_duration, release_clause FROM transfer_offers WHERE id = ?', (offer_id,))
            offer = cur.fetchone()
            if offer:
                player_name, team_id, duration, clause = offer
                cur.execute('UPDATE players SET team_id = ?, contract_duration = ?, release_clause = ? WHERE name = ?', (team_id, duration, clause, player_name))
                cur.execute('UPDATE transfer_offers SET status = "accepted" WHERE id = ?', (offer_id,))
                conn.commit()
                database_logger.info(f"Oferta {offer_id} aceptada para {player_name} en guild {guild_id}.")
    except sqlite3.Error as e:
        database_logger.error(f"Error al aceptar oferta {offer_id} en guild {guild_id}: {e}")

def reject_offer(guild_id: int, offer_id: int):
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute('UPDATE transfer_offers SET status = "rejected" WHERE id = ?', (offer_id,))
            conn.commit()
            database_logger.info(f"Oferta {offer_id} rechazada en guild {guild_id}.")
    except sqlite3.Error as e:
        database_logger.error(f"Error al rechazar oferta {offer_id} en guild {guild_id}: {e}")

def accept_clause_payment(guild_id: int, offer_id: int) -> bool:
    db_path = get_db_path(guild_id)
    if get_market_status(guild_id) == 'closed':
        database_logger.info(f"No se puede aceptar pago de cláusula {offer_id} en guild {guild_id}: mercado cerrado.")
        return False
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute('SELECT player_name, to_team_id, price, from_team_id FROM transfer_offers WHERE id = ?', (offer_id,))
            offer = cur.fetchone()
            if not offer:
                return False
            player_name, to_team_id, clause_amount, from_team_id = offer
            cur.execute('SELECT balance FROM club_balance WHERE team_id = ?', (to_team_id,))
            row = cur.fetchone()
            balance = row[0] if row else 0
            if balance < clause_amount:
                database_logger.warning(f"Fondos insuficientes para oferta {offer_id} en guild {guild_id}.")
                return False
            cur.execute('UPDATE club_balance SET balance = balance - ? WHERE team_id = ?', (clause_amount, to_team_id))
            if from_team_id:
                cur.execute('UPDATE club_balance SET balance = balance + ? WHERE team_id = ?', (clause_amount, from_team_id))
            cur.execute('UPDATE players SET team_id = ? WHERE name = ?', (to_team_id, player_name))
            cur.execute('UPDATE transfer_offers SET status = "accepted" WHERE id = ?', (offer_id,))
            conn.commit()
            database_logger.info(f"Pago de cláusula aceptado para oferta {offer_id} en guild {guild_id}.")
            return True
    except sqlite3.Error as e:
        database_logger.error(f"Error al aceptar pago de cláusula para oferta {offer_id} en guild {guild_id}: {e}")
        return False

def has_pending_offer(guild_id: int, from_manager_id: int, to_player_user_id: int) -> bool:
    db_path = get_db_path(guild_id)
    player = get_player_by_id(guild_id, to_player_user_id)
    if not player:
        return False
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute(
                'SELECT COUNT(*) FROM transfer_offers WHERE from_manager_id = ? AND player_name = ? AND status IN (?, ?)',
                (from_manager_id, player['name'], 'pending', 'bought_clause')
            )
            return cur.fetchone()[0] > 0
    except sqlite3.Error as e:
        database_logger.error(f"Error al verificar oferta pendiente en guild {guild_id}: {e}")
        return False

def list_offers_by_manager(guild_id: int, manager_id: int, status: str) -> list:
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(
                'SELECT id, player_name, contract_duration AS duration, release_clause AS clause'
                ' FROM transfer_offers'
                ' WHERE from_manager_id = ? AND status = ?',
                (manager_id, status)
            )
            return [dict(row) for row in cur.fetchall()]
    except sqlite3.Error as e:
        database_logger.error(f"Error al listar ofertas por manager {manager_id} en guild {guild_id}: {e}")
        return []

def list_offers_for_player(guild_id: int, player_user_id: int, status: str) -> list:
    db_path = get_db_path(guild_id)
    player = get_player_by_id(guild_id, player_user_id)
    if not player:
        return []
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(
                'SELECT o.id, t.name AS manager_name, o.contract_duration AS duration, o.release_clause AS clause'
                ' FROM transfer_offers o'
                ' JOIN teams t ON o.from_team_id = t.id'
                ' WHERE o.player_name = ? AND o.status = ?',
                (player['name'], status)
            )
            return [dict(row) for row in cur.fetchall()]
    except sqlite3.Error as e:
        database_logger.error(f"Error al listar ofertas para jugador {player_user_id} en guild {guild_id}: {e}")
        return []

def get_players_by_team(guild_id: int, team_id: int) -> list:
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute('SELECT name, contract_duration, release_clause FROM players WHERE team_id = ?', (team_id,))
            return [{'name': r['name'], 'contract_details': f"{r['contract_duration']} temp. | cláusula {r['release_clause']:,}" if r['contract_duration'] and r['release_clause'] else None} for r in cur.fetchall()]
    except sqlite3.Error as e:
        database_logger.error(f"Error al obtener jugadores del equipo {team_id} en guild {guild_id}: {e}")
        return []

def pay_clause_and_transfer(guild_id: int, name: str, to_team_id: int, clause_amount: int, from_manager_id: int) -> int:
    db_path = get_db_path(guild_id)
    if get_market_status(guild_id) == 'closed':
        database_logger.info(f"No se puede pagar cláusula en guild {guild_id}: mercado cerrado.")
        return -2
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute('SELECT balance FROM club_balance WHERE team_id = ?', (to_team_id,))
            row = cur.fetchone()
            balance = row[0] if row else 0
            if balance < clause_amount:
                database_logger.warning(f"Fondos insuficientes para pagar cláusula de {name} en guild {guild_id}.")
                return -1
            cur.execute('SELECT team_id FROM players WHERE name = ?', (name,))
            player = cur.fetchone()
            from_team_id = player[0] if player and player[0] else None
            cur.execute(
                '''INSERT INTO transfer_offers
                   (player_name, from_team_id, to_team_id, from_manager_id, price, status, contract_duration, release_clause)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                (name, from_team_id, to_team_id, from_manager_id, clause_amount, 'bought_clause', None, None)
            )
            offer_id = cur.lastrowid
            conn.commit()
            database_logger.info(f"Oferta de cláusula {offer_id} creada para {name} en guild {guild_id}.")
            return offer_id
    except sqlite3.Error as e:
        database_logger.error(f"Error al crear oferta de cláusula para {name} en guild {guild_id}: {e}")
        return -1

def get_transfer_history_by_player(guild_id: int, name: str) -> list:
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute('SELECT from_team_id, to_team_id, price, status FROM transfer_offers WHERE player_name = ? ORDER BY id', (name,))
            rows = cur.fetchall()
        history = []
        for row in rows:
            from_team = get_team_by_id(guild_id, row['from_team_id'])
            to_team = get_team_by_id(guild_id, row['to_team_id'])
            from_name = from_team['name'] if from_team else 'Libre'
            to_name = to_team['name'] if to_team else 'Libre'
            history.append(f"{from_name} → {to_name} por {row['price']:,} [{row['status']}]")
        return history
    except sqlite3.Error as e:
        database_logger.error(f"Error al obtener historial de {name} en guild {guild_id}: {e}")
        return []

def get_transfer_history_by_team(guild_id: int, team_id: int) -> list:
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute('SELECT player_name, from_team_id, to_team_id, price, status FROM transfer_offers WHERE from_team_id = ? OR to_team_id = ? ORDER BY id', (team_id, team_id))
            rows = cur.fetchall()
        history = []
        for row in rows:
            from_team = get_team_by_id(guild_id, row['from_team_id'])
            to_team = get_team_by_id(guild_id, row['to_team_id'])
            from_name = from_team['name'] if from_team else 'Libre'
            to_name = to_team['name'] if to_team else 'Libre'
            history.append(f"{row['player_name']}: {from_name} → {to_name} por {row['price']:,} [{row['status']}]")
        return history
    except sqlite3.Error as e:
        database_logger.error(f"Error al obtener historial del equipo {team_id} en guild {guild_id}: {e}")
        return []

def get_club_balance(guild_id: int, team_id: int) -> int:
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute('SELECT balance FROM club_balance WHERE team_id = ?', (team_id,))
            row = cur.fetchone()
            return row[0] if row else 0
    except sqlite3.Error as e:
        database_logger.error(f"Error al obtener balance del equipo {team_id} en guild {guild_id}: {e}")
        return 0

def add_money_to_club(guild_id: int, team_id: int, amount: int):
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute('UPDATE club_balance SET balance = balance + ? WHERE team_id = ?', (amount, team_id))
            conn.commit()
            database_logger.info(f"{amount} añadido al balance del equipo {team_id} en guild {guild_id}.")
    except sqlite3.Error as e:
        database_logger.error(f"Error al añadir dinero al equipo {team_id} en guild {guild_id}: {e}")

def remove_money_from_club(guild_id: int, team_id: int, amount: int):
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute('UPDATE club_balance SET balance = balance - ? WHERE team_id = ?', (amount, team_id))
            conn.commit()
            database_logger.info(f"{amount} removido del balance del equipo {team_id} en guild {guild_id}.")
    except sqlite3.Error as e:
        database_logger.error(f"Error al quitar dinero del equipo {team_id} en guild {guild_id}: {e}")

def restore_database_from_file(guild_id: int, backup_file: str):
    db_path = get_db_path(guild_id)
    try:
        if not os.path.exists(backup_file):
            database_logger.error(f"El archivo de respaldo {backup_file} no existe.")
            return False
        
        with open(backup_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        
        current_table = None
        teams, players, transfer_offers, club_balances = [], [], [], []
        
        for line in lines:
            line = line.strip()
            if not line or line.startswith("===") or line.startswith("Fecha y hora") or line.startswith("Guild ID"):
                if line == "=== Tabla 'teams' ===":
                    current_table = "teams"
                elif line == "=== Tabla 'players' ===":
                    current_table = "players"
                elif line == "=== Tabla 'transfer_offers' ===":
                    current_table = "transfer_offers"
                elif line == "=== Tabla 'club_balance' ===":
                    current_table = "club_balance"
                continue
            
            if line.startswith("No hay"):
                continue
            
            if current_table == "teams":
                try:
                    parts = line.split(", ")
                    team = {
                        "id": int(parts[0].split(": ")[1]),
                        "name": parts[1].split(": ")[1],
                        "manager_id": None if parts[2].split(": ")[1] == "None" else int(parts[2].split(": ")[1])
                    }
                    teams.append(team)
                except (ValueError, IndexError) as e:
                    database_logger.warning(f"Error al parsear línea de teams: {line} - {e}")
            
            elif current_table == "players":
                try:
                    parts = line.split(", ")
                    player = {
                        "name": parts[0].split(": ")[1],
                        "user_id": int(parts[1].split(": ")[1]),
                        "team_id": None if parts[2].split(": ")[1] == "None" else int(parts[2].split(": ")[1]),
                        "transferable": int(parts[3].split(": ")[1]),
                        "banned": int(parts[4].split(": ")[1]),
                        "contract_duration": None if parts[5].split(": ")[1] == "None" else int(parts[5].split(": ")[1]),
                        "release_clause": None if parts[6].split(": ")[1] == "None" else int(parts[6].split(": ")[1]),
                        "original_release_clause": None if parts[7].split(": ")[1] == "None" else int(parts[7].split(": ")[1])
                    }
                    players.append(player)
                except (ValueError, IndexError) as e:
                    database_logger.warning(f"Error al parsear línea de players: {line} - {e}")
            
            elif current_table == "transfer_offers":
                try:
                    parts = line.split(", ")
                    offer = {
                        "id": int(parts[0].split(": ")[1]),
                        "player_name": parts[1].split(": ")[1],
                        "from_team_id": None if parts[2].split(": ")[1] == "None" else int(parts[2].split(": ")[1]),
                        "to_team_id": None if parts[3].split(": ")[1] == "None" else int(parts[3].split(": ")[1]),
                        "from_manager_id": None if parts[4].split(": ")[1] == "None" else int(parts[4].split(": ")[1]),
                        "to_manager_id": None if parts[5].split(": ")[1] == "None" else int(parts[5].split(": ")[1]),
                        "price": int(parts[6].split(": ")[1]),
                        "status": parts[7].split(": ")[1],
                        "contract_duration": None if parts[8].split(": ")[1] == "None" else int(parts[8].split(": ")[1]),
                        "release_clause": None if parts[9].split(": ")[1] == "None" else int(parts[9].split(": ")[1])
                    }
                    transfer_offers.append(offer)
                except (ValueError, IndexError) as e:
                    database_logger.warning(f"Error al parsear línea de transfer_offers: {line} - {e}")
            
            elif current_table == "club_balance":
                try:
                    parts = line.split(", ")
                    balance = {
                        "team_id": int(parts[0].split(": ")[1]),
                        "balance": int(parts[1].split(": ")[1])
                    }
                    club_balances.append(balance)
                except (ValueError, IndexError) as e:
                    database_logger.warning(f"Error al parsear línea de club_balance: {line} - {e}")
        
        if os.path.exists(db_path):
            os.remove(db_path)
            database_logger.info(f"Base de datos existente {db_path} eliminada.")
        
        create_tables(guild_id)
        
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            
            for team in teams:
                cur.execute('INSERT INTO teams (id, name, manager_id) VALUES (?, ?, ?)',
                           (team['id'], team['name'], team['manager_id']))
            
            for player in players:
                cur.execute('INSERT INTO players (name, user_id, team_id, transferable, banned, contract_duration, release_clause, original_release_clause) '
                           'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                           (player['name'], player['user_id'], player['team_id'], player['transferable'], player['banned'],
                            player['contract_duration'], player['release_clause'], player['original_release_clause']))
            
            for offer in transfer_offers:
                cur.execute('INSERT INTO transfer_offers (id, player_name, from_team_id, to_team_id, from_manager_id, to_manager_id, price, status, contract_duration, release_clause) '
                           'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                           (offer['id'], offer['player_name'], offer['from_team_id'], offer['to_team_id'], offer['from_manager_id'],
                            offer['to_manager_id'], offer['price'], offer['status'], offer['contract_duration'], offer['release_clause']))
            
            for balance in club_balances:
                cur.execute('INSERT INTO club_balance (team_id, balance) VALUES (?, ?)',
                           (balance['team_id'], balance['balance']))
            
            conn.commit()
            database_logger.info(f"Base de datos restaurada desde {backup_file} para guild {guild_id}.")
            return True
    
    except (sqlite3.Error, OSError) as e:
        database_logger.error(f"Error al restaurar la base de datos desde {backup_file} para guild {guild_id}: {e}")
        return False

# Obtener la configuración de un servidor
def get_server_config(guild_id: int) -> dict:
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute('SELECT * FROM server_config WHERE guild_id = ?', (guild_id,))
            return _row_to_dict(cur.fetchone())
    except sqlite3.Error as e:
        database_logger.error(f"Error al obtener configuración del servidor {guild_id}: {e}")
        return None

# Establecer el canal de capturas de pantalla
def set_ss_channel(guild_id: int, channel_id: int):
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute('INSERT OR REPLACE INTO server_config (guild_id, ss_channel_id) VALUES (?, ?)', (guild_id, channel_id))
            conn.commit()
            database_logger.info(f"Canal de SS establecido para guild {guild_id}: {channel_id}")
    except sqlite3.Error as e:
        database_logger.error(f"Error al establecer canal de SS para guild {guild_id}: {e}")

# Establecer el canal de tablas de amistosos
def set_amistosos_channel(guild_id: int, channel_id: int):
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute('INSERT OR REPLACE INTO server_config (guild_id, amistosos_channel_id) VALUES (?, ?)', (guild_id, channel_id))
            conn.commit()
            database_logger.info(f"Canal de amistosos establecido para guild {guild_id}: {channel_id}")
    except sqlite3.Error as e:
        database_logger.error(f"Error al establecer canal de amistosos para guild {guild_id}: {e}")
        
def get_free_agents(guild_id: int):
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute('SELECT name, user_id, contract_duration, release_clause FROM players WHERE team_id IS NULL ORDER BY name')
            players = cur.fetchall()
            database_logger.info(f"Encontrados {len(players)} agentes libres en guild {guild_id}.")
            return players
    except sqlite3.Error as e:
        database_logger.error(f"Error al obtener agentes libres en guild {guild_id}: {e}")
        return []

def advance_season(guild_id: int):
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute('UPDATE players SET contract_duration = contract_duration - 1 WHERE contract_duration IS NOT NULL AND contract_duration > 0')
            cur.execute('UPDATE players SET team_id = NULL, contract_duration = NULL, release_clause = NULL WHERE contract_duration = 0')
            conn.commit()
            database_logger.info(f"Temporada avanzada: contratos actualizados en guild {guild_id}.")
    except sqlite3.Error as e:
        database_logger.error(f"Error al avanzar temporada en guild {guild_id}: {e}")

def get_recent_transfers(guild_id: int, limit: int = 10) -> list:
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute('''
                SELECT o.id, o.player_name, o.from_team_id, o.to_team_id, o.price, o.status, t1.name as from_team_name, t2.name as to_team_name
                FROM transfer_offers o
                LEFT JOIN teams t1 ON o.from_team_id = t1.id
                LEFT JOIN teams t2 ON o.to_team_id = t2.id
                WHERE o.status IN ('accepted', 'finalized', 'bought_clause')
                ORDER BY o.id DESC
                LIMIT ?
            ''', (limit,))
            rows = cur.fetchall()
        return [dict(row) for row in rows]
    except sqlite3.Error as e:
        database_logger.error(f"Error al obtener fichajes recientes en guild {guild_id}: {e}")
        return []

def add_screenshot(guild_id: int, user_id: int, nicktag: str, discord_name: str, channel_id: int, image_url: str, screenshot_time: str = None) -> int:
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute('''INSERT INTO screenshots (user_id, nicktag, discord_name, channel_id, timestamp, screenshot_time, status, image_url)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                        (user_id, nicktag, discord_name, channel_id, datetime.now().isoformat(), screenshot_time, 'pending', image_url))
            screenshot_id = cur.lastrowid
            conn.commit()
            database_logger.info(f"Captura {screenshot_id} añadida para user_id {user_id} en guild {guild_id}.")
            return screenshot_id
    except sqlite3.Error as e:
        database_logger.error(f"Error al añadir captura en guild {guild_id}: {e}")
        return -1

def update_screenshot_status(guild_id: int, screenshot_id: int, status: str) -> bool:
    db_path = get_db_path(guild_id)
    if status not in {'pending', 'accepted', 'rejected'}:
        database_logger.warning(f"Estado inválido para captura {screenshot_id} en guild {guild_id}: {status}")
        return False
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute('UPDATE screenshots SET status = ? WHERE id = ?', (status, screenshot_id))
            conn.commit()
            database_logger.info(f"Estado de captura {screenshot_id} actualizado a {status} en guild {guild_id}.")
            return True
    except sqlite3.Error as e:
        database_logger.error(f"Error al actualizar estado de captura {screenshot_id} en guild {guild_id}: {e}")
        return False

def get_screenshots_by_user(guild_id: int, user_id: int) -> list:
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute('SELECT * FROM screenshots WHERE user_id = ? ORDER BY timestamp DESC', (user_id,))
            return [dict(row) for row in cur.fetchall()]
    except sqlite3.Error as e:
        database_logger.error(f"Error al obtener capturas para user_id {user_id} en guild {guild_id}: {e}")
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
        database_logger.warning(f"Intento de agregar capitán duplicado: {captain_id} en equipo {team_id} en guild {guild_id}")
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
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute('SELECT captain_id FROM team_captains WHERE team_id = ?', (team_id,))
            return [row['captain_id'] for row in cur.fetchall()]
    except sqlite3.Error as e:
        database_logger.error(f"Error al obtener capitanes del equipo {team_id} en guild {guild_id}: {e}")
        return []

def is_captain(guild_id: int, team_id: int, user_id: int) -> bool:
    captains = get_captains(guild_id, team_id)
    return user_id in captains

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

def get_all_screenshots(guild_id: int, status: str = None) -> list:
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            if status:
                cur.execute('SELECT * FROM screenshots WHERE status = ? ORDER BY timestamp DESC', (status,))
            else:
                cur.execute('SELECT * FROM screenshots ORDER BY timestamp DESC')
            return [dict(row) for row in cur.fetchall()]
    except sqlite3.Error as e:
        database_logger.error(f"Error al obtener todas las capturas en guild {guild_id}: {e}")
        return []

def get_amistoso_by_id(guild_id: int, amistoso_id: int):
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute('SELECT * FROM amistosos WHERE id = ?', (amistoso_id,))
            row = cur.fetchone()
            return dict(row) if row else None
    except sqlite3.Error as e:
        database_logger.error(f"Error al obtener amistoso {amistoso_id} en guild {guild_id}: {e}")
        return None

def delete_amistoso(guild_id: int, amistoso_id: int):
    db_path = get_db_path(guild_id)
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute('DELETE FROM amistosos WHERE id = ?', (amistoso_id,))
            conn.commit()
            database_logger.info(f"Amistoso {amistoso_id} eliminado en guild {guild_id}.")
            return True
    except sqlite3.Error as e:
        database_logger.error(f"Error al eliminar amistoso {amistoso_id} en guild {guild_id}: {e}")
        return False

def initialize_global():
    create_global_tables()

initialize_global()
