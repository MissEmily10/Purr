import sqlite3
import time

DATABASE_NAME = "bot.db"


def _now():
    return int(time.time())


def get_connection():
    connection = sqlite3.connect(DATABASE_NAME)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_database():
    connection = get_connection()
    cursor = connection.cursor()

    # Existing access tables
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS command_access (
            guild_id INTEGER NOT NULL,
            command_name TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            expires_at INTEGER,
            PRIMARY KEY (guild_id, command_name, user_id)
        )
    """)

    cursor.execute("PRAGMA table_info(command_access)")
    columns = [row[1] for row in cursor.fetchall()]
    if "expires_at" not in columns:
        cursor.execute("""
            ALTER TABLE command_access
            ADD COLUMN expires_at INTEGER
        """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bot_members (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            access_level TEXT NOT NULL DEFAULT 'member',
            expires_at INTEGER,
            PRIMARY KEY (guild_id, user_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS role_access (
            guild_id INTEGER NOT NULL,
            role_id INTEGER NOT NULL,
            access_level TEXT NOT NULL,
            expires_at INTEGER,
            PRIMARY KEY (guild_id, role_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS denied_users (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            reason TEXT,
            created_at INTEGER NOT NULL,
            PRIMARY KEY (guild_id, user_id)
        )
    """)

    # Message Build storage.
    # One build can contain multiple embeds and up to five buttons.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS message_builds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            owner_id INTEGER NOT NULL,
            name TEXT,
            content TEXT,
            embeds_json TEXT NOT NULL DEFAULT '[]',
            buttons_json TEXT NOT NULL DEFAULT '[]',
            visibility TEXT NOT NULL DEFAULT 'private',
            category TEXT NOT NULL DEFAULT 'general',
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        )
    """)

    # Saved button sets are independent from message builds.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS button_sets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            owner_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            buttons_json TEXT NOT NULL DEFAULT '[]',
            visibility TEXT NOT NULL DEFAULT 'private',
            category TEXT NOT NULL DEFAULT 'general',
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        )
    """)

    connection.commit()
    connection.close()

    # Extended modules are initialized as part of the same database startup.
    _ensure_extended_tables()


# =========================
# COMMAND ACCESS
# =========================

def add_command_access(guild_id, command_name, user_id, expires_at=None):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        INSERT INTO command_access
        (guild_id, command_name, user_id, expires_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(guild_id, command_name, user_id)
        DO UPDATE SET expires_at = excluded.expires_at
    """, (guild_id, command_name, user_id, expires_at))

    connection.commit()
    connection.close()


def get_command_access(guild_id, command_name):
    connection = get_connection()
    cursor = connection.cursor()
    now = int(time.time())

    cursor.execute("""
        DELETE FROM command_access
        WHERE expires_at IS NOT NULL
        AND expires_at <= ?
    """, (now,))

    cursor.execute("""
        SELECT user_id
        FROM command_access
        WHERE guild_id = ?
        AND command_name = ?
        AND (expires_at IS NULL OR expires_at > ?)
    """, (guild_id, command_name, now))

    users = [row[0] for row in cursor.fetchall()]
    connection.commit()
    connection.close()
    return users


def get_command_access_details(guild_id, command_name):
    connection = get_connection()
    cursor = connection.cursor()
    now = int(time.time())

    cursor.execute("""
        DELETE FROM command_access
        WHERE expires_at IS NOT NULL
        AND expires_at <= ?
    """, (now,))

    cursor.execute("""
        SELECT user_id, expires_at
        FROM command_access
        WHERE guild_id = ?
        AND command_name = ?
        AND (expires_at IS NULL OR expires_at > ?)
    """, (guild_id, command_name, now))

    users = cursor.fetchall()
    connection.commit()
    connection.close()
    return users


def remove_command_access(guild_id, command_name, user_id):
    connection = get_connection()
    connection.execute("""
        DELETE FROM command_access
        WHERE guild_id = ? AND command_name = ? AND user_id = ?
    """, (guild_id, command_name, user_id))
    connection.commit()
    connection.close()


# =========================
# ACCESS LEVELS
# =========================

def set_access_level(guild_id, user_id, access_level, expires_at=None):
    connection = get_connection()
    connection.execute("""
        INSERT INTO bot_members
        (guild_id, user_id, access_level, expires_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(guild_id, user_id)
        DO UPDATE SET
            access_level = excluded.access_level,
            expires_at = excluded.expires_at
    """, (guild_id, user_id, access_level, expires_at))
    connection.commit()
    connection.close()


def get_access_level(guild_id, user_id):
    connection = get_connection()
    cursor = connection.cursor()
    now = int(time.time())

    cursor.execute("""
        SELECT access_level, expires_at
        FROM bot_members
        WHERE guild_id = ? AND user_id = ?
    """, (guild_id, user_id))

    result = cursor.fetchone()

    if result is None:
        connection.close()
        return "member"

    access_level, expires_at = result

    if expires_at is not None and expires_at <= now:
        cursor.execute("""
            UPDATE bot_members
            SET access_level = 'member', expires_at = NULL
            WHERE guild_id = ? AND user_id = ?
        """, (guild_id, user_id))
        connection.commit()
        connection.close()
        return "member"

    connection.close()
    return access_level


def get_member_info(guild_id, user_id):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT access_level, expires_at
        FROM bot_members
        WHERE guild_id = ? AND user_id = ?
    """, (guild_id, user_id))

    result = cursor.fetchone()
    connection.close()

    if result is None:
        return "member", None

    return result


def remove_member(guild_id, user_id):
    connection = get_connection()
    connection.execute("""
        DELETE FROM bot_members
        WHERE guild_id = ? AND user_id = ?
    """, (guild_id, user_id))
    connection.commit()
    connection.close()


# =========================
# ROLE AND DENIAL ACCESS
# =========================

def set_role_access(guild_id, role_id, access_level, expires_at=None):
    connection = get_connection()
    connection.execute("""
        INSERT INTO role_access (guild_id, role_id, access_level, expires_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(guild_id, role_id)
        DO UPDATE SET access_level = excluded.access_level,
                      expires_at = excluded.expires_at
    """, (guild_id, role_id, access_level, expires_at))
    connection.commit()
    connection.close()


def remove_role_access(guild_id, role_id):
    connection = get_connection()
    connection.execute("""
        DELETE FROM role_access
        WHERE guild_id = ? AND role_id = ?
    """, (guild_id, role_id))
    connection.commit()
    connection.close()


def deny_user(guild_id, user_id, reason=None):
    connection = get_connection()
    connection.execute("""
        INSERT INTO denied_users (guild_id, user_id, reason, created_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(guild_id, user_id)
        DO UPDATE SET reason = excluded.reason,
                      created_at = excluded.created_at
    """, (guild_id, user_id, reason, int(time.time())))
    connection.commit()
    connection.close()


def is_user_denied(guild_id, user_id):
    connection = get_connection()
    row = connection.execute("""
        SELECT reason
        FROM denied_users
        WHERE guild_id = ? AND user_id = ?
    """, (guild_id, user_id)).fetchone()
    connection.close()
    return row[0] if row else None


def undeny_user(guild_id, user_id):
    connection = get_connection()
    connection.execute("""
        DELETE FROM denied_users
        WHERE guild_id = ? AND user_id = ?
    """, (guild_id, user_id))
    connection.commit()
    connection.close()


# =========================
# MESSAGE BUILDS
# =========================

def save_message_build(
    guild_id,
    owner_id,
    name,
    content,
    embeds_json,
    buttons_json,
    visibility="private",
    category="general",
):
    now = int(time.time())
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        INSERT INTO message_builds
        (guild_id, owner_id, name, content, embeds_json, buttons_json,
         visibility, category, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        guild_id, owner_id, name, content, embeds_json, buttons_json,
        visibility, category, now, now
    ))

    build_id = cursor.lastrowid
    connection.commit()
    connection.close()
    return build_id


def update_message_build(
    build_id,
    owner_id,
    name,
    content,
    embeds_json,
    buttons_json,
    visibility,
    category,
):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        UPDATE message_builds
        SET name = ?, content = ?, embeds_json = ?, buttons_json = ?,
            visibility = ?, category = ?, updated_at = ?
        WHERE id = ? AND owner_id = ?
    """, (
        name, content, embeds_json, buttons_json,
        visibility, category, int(time.time()), build_id, owner_id
    ))

    connection.commit()
    changed = cursor.rowcount > 0
    connection.close()
    return changed


def get_message_build(build_id):
    connection = get_connection()
    cursor = connection.cursor()
    cursor.execute("""
        SELECT id, guild_id, owner_id, name, content, embeds_json,
               buttons_json, visibility, category, created_at, updated_at
        FROM message_builds
        WHERE id = ?
    """, (build_id,))
    result = cursor.fetchone()
    connection.close()
    return result


def get_message_builds(guild_id, owner_id=None, include_public=True):
    connection = get_connection()
    cursor = connection.cursor()

    if owner_id is None:
        cursor.execute("""
            SELECT id, owner_id, name, visibility, category, updated_at
            FROM message_builds
            WHERE guild_id = ?
            ORDER BY updated_at DESC
        """, (guild_id,))
    elif include_public:
        cursor.execute("""
            SELECT id, owner_id, name, visibility, category, updated_at
            FROM message_builds
            WHERE guild_id = ?
              AND (owner_id = ? OR visibility = 'public')
            ORDER BY updated_at DESC
        """, (guild_id, owner_id))
    else:
        cursor.execute("""
            SELECT id, owner_id, name, visibility, category, updated_at
            FROM message_builds
            WHERE guild_id = ? AND owner_id = ?
            ORDER BY updated_at DESC
        """, (guild_id, owner_id))

    rows = cursor.fetchall()
    connection.close()
    return rows


def delete_message_build(build_id, owner_id):
    connection = get_connection()
    cursor = connection.cursor()
    cursor.execute("""
        DELETE FROM message_builds
        WHERE id = ? AND owner_id = ?
    """, (build_id, owner_id))
    connection.commit()
    changed = cursor.rowcount > 0
    connection.close()
    return changed


# =========================
# BUTTON SETS
# =========================

def save_button_set(
    guild_id,
    owner_id,
    name,
    buttons_json,
    visibility="private",
    category="general",
):
    now = int(time.time())
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        INSERT INTO button_sets
        (guild_id, owner_id, name, buttons_json, visibility, category,
         created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        guild_id, owner_id, name, buttons_json, visibility, category,
        now, now
    ))

    set_id = cursor.lastrowid
    connection.commit()
    connection.close()
    return set_id


def get_button_set(set_id):
    connection = get_connection()
    cursor = connection.cursor()
    cursor.execute("""
        SELECT id, guild_id, owner_id, name, buttons_json,
               visibility, category, created_at, updated_at
        FROM button_sets
        WHERE id = ?
    """, (set_id,))
    result = cursor.fetchone()
    connection.close()
    return result


def get_button_sets(guild_id, owner_id=None, include_public=True):
    connection = get_connection()
    cursor = connection.cursor()

    if owner_id is None:
        cursor.execute("""
            SELECT id, owner_id, name, visibility, category, updated_at
            FROM button_sets
            WHERE guild_id = ?
            ORDER BY updated_at DESC
        """, (guild_id,))
    elif include_public:
        cursor.execute("""
            SELECT id, owner_id, name, visibility, category, updated_at
            FROM button_sets
            WHERE guild_id = ?
              AND (owner_id = ? OR visibility = 'public')
            ORDER BY updated_at DESC
        """, (guild_id, owner_id))
    else:
        cursor.execute("""
            SELECT id, owner_id, name, visibility, category, updated_at
            FROM button_sets
            WHERE guild_id = ? AND owner_id = ?
            ORDER BY updated_at DESC
        """, (guild_id, owner_id))

    rows = cursor.fetchall()
    connection.close()
    return rows


def delete_button_set(set_id, owner_id):
    connection = get_connection()
    cursor = connection.cursor()
    cursor.execute("""
        DELETE FROM button_sets
        WHERE id = ? AND owner_id = ?
    """, (set_id, owner_id))
    connection.commit()
    changed = cursor.rowcount > 0
    connection.close()
    return changed


# =========================
# EXTENDED MODULE STORAGE
# =========================

def _ensure_extended_tables():
    connection = get_connection()
    c = connection.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS forms (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER NOT NULL, owner_id INTEGER NOT NULL,
        name TEXT NOT NULL, description TEXT, questions_json TEXT NOT NULL,
        visibility TEXT NOT NULL DEFAULT 'private', category TEXT NOT NULL DEFAULT 'general',
        allowed_role_ids_json TEXT NOT NULL DEFAULT '[]', destination_channel_id INTEGER,
        reviewer_role_ids_json TEXT NOT NULL DEFAULT '[]', reviewer_user_ids_json TEXT NOT NULL DEFAULT '[]',
        post_action TEXT NOT NULL DEFAULT 'review', post_role_id INTEGER, target_role_id INTEGER,
        created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS form_submissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, form_id INTEGER NOT NULL,
        guild_id INTEGER NOT NULL, applicant_id INTEGER NOT NULL,
        answers_json TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL DEFAULT 'pending',
        reviewer_id INTEGER, review_reason TEXT, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS templates (
        id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL, owner_id INTEGER NOT NULL,
        name TEXT NOT NULL, template_type TEXT NOT NULL, payload_json TEXT NOT NULL DEFAULT '{}',
        visibility TEXT NOT NULL DEFAULT 'private', category TEXT NOT NULL DEFAULT 'general',
        allowed_role_ids_json TEXT NOT NULL DEFAULT '[]', created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS webhooks (
        id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL, owner_id INTEGER NOT NULL,
        webhook_id INTEGER NOT NULL, channel_id INTEGER NOT NULL, name TEXT NOT NULL,
        url TEXT NOT NULL, avatar_url TEXT, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS webhook_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL, owner_id INTEGER NOT NULL,
        webhook_id INTEGER NOT NULL, action TEXT NOT NULL, channel_id INTEGER, details TEXT, created_at INTEGER NOT NULL
    )""")
    c.execute("PRAGMA table_info(forms)")
    form_columns = {row[1] for row in c.fetchall()}
    if "target_role_id" not in form_columns:
        c.execute("ALTER TABLE forms ADD COLUMN target_role_id INTEGER")
    c.execute("""CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL, actor_id INTEGER NOT NULL,
        action TEXT NOT NULL, target_type TEXT, target_id TEXT, details TEXT, created_at INTEGER NOT NULL
    )""")
    connection.commit(); connection.close()


def save_form(guild_id, owner_id, name, description, questions_json, visibility='private', category='general',
              allowed_role_ids_json='[]', destination_channel_id=None, reviewer_role_ids_json='[]',
              reviewer_user_ids_json='[]', post_action='review', post_role_id=None, target_role_id=None):
    _ensure_extended_tables(); now=_now(); connection=get_connection(); c=connection.cursor()
    c.execute("""INSERT INTO forms (guild_id,owner_id,name,description,questions_json,visibility,category,
        allowed_role_ids_json,destination_channel_id,reviewer_role_ids_json,reviewer_user_ids_json,post_action,post_role_id,target_role_id,created_at,updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (guild_id,owner_id,name,description,questions_json,visibility,category,
        allowed_role_ids_json,destination_channel_id,reviewer_role_ids_json,reviewer_user_ids_json,post_action,post_role_id,target_role_id,now,now))
    rid=c.lastrowid; connection.commit(); connection.close(); return rid


def get_form(form_id):
    _ensure_extended_tables(); connection=get_connection(); row=connection.execute("""SELECT id,guild_id,owner_id,name,description,questions_json,visibility,category,
        allowed_role_ids_json,destination_channel_id,reviewer_role_ids_json,reviewer_user_ids_json,post_action,post_role_id,target_role_id,created_at,updated_at FROM forms WHERE id=?""",(form_id,)).fetchone(); connection.close(); return row


def get_forms(guild_id, owner_id=None, include_public=True):
    _ensure_extended_tables(); connection=get_connection();
    if owner_id is None:
        rows=connection.execute("SELECT id,owner_id,name,visibility,category,allowed_role_ids_json,updated_at FROM forms WHERE guild_id=? ORDER BY updated_at DESC",(guild_id,)).fetchall()
    elif include_public:
        rows=connection.execute("SELECT id,owner_id,name,visibility,category,allowed_role_ids_json,updated_at FROM forms WHERE guild_id=? AND (owner_id=? OR visibility='public') ORDER BY updated_at DESC",(guild_id,owner_id)).fetchall()
    else:
        rows=connection.execute("SELECT id,owner_id,name,visibility,category,allowed_role_ids_json,updated_at FROM forms WHERE guild_id=? AND owner_id=? ORDER BY updated_at DESC",(guild_id,owner_id)).fetchall()
    connection.close(); return rows


def save_submission(form_id,guild_id,applicant_id,answers_json):
    _ensure_extended_tables(); connection=get_connection(); c=connection.cursor(); now=_now()
    c.execute("INSERT INTO form_submissions (form_id,guild_id,applicant_id,answers_json,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",(form_id,guild_id,applicant_id,answers_json,'pending',now,now))
    rid=c.lastrowid; connection.commit(); connection.close(); return rid


def get_submission(submission_id):
    _ensure_extended_tables(); connection=get_connection(); row=connection.execute("SELECT id,form_id,guild_id,applicant_id,answers_json,status,reviewer_id,review_reason,created_at,updated_at FROM form_submissions WHERE id=?",(submission_id,)).fetchone(); connection.close(); return row


def review_submission(submission_id, reviewer_id, status, reason=''):
    _ensure_extended_tables(); connection=get_connection(); connection.execute("UPDATE form_submissions SET status=?,reviewer_id=?,review_reason=?,updated_at=? WHERE id=?",(status,reviewer_id,reason,_now(),submission_id)); connection.commit(); connection.close()


def save_template(guild_id,owner_id,name,template_type,payload_json,visibility='private',category='general',allowed_role_ids_json='[]'):
    _ensure_extended_tables(); now=_now(); connection=get_connection(); c=connection.cursor(); c.execute("INSERT INTO templates (guild_id,owner_id,name,template_type,payload_json,visibility,category,allowed_role_ids_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",(guild_id,owner_id,name,template_type,payload_json,visibility,category,allowed_role_ids_json,now,now)); rid=c.lastrowid; connection.commit(); connection.close(); return rid


def get_template(template_id):
    _ensure_extended_tables(); connection=get_connection(); row=connection.execute("SELECT id,guild_id,owner_id,name,template_type,payload_json,visibility,category,allowed_role_ids_json,created_at,updated_at FROM templates WHERE id=?",(template_id,)).fetchone(); connection.close(); return row


def get_templates(guild_id,owner_id=None,template_type=None,include_public=True):
    _ensure_extended_tables(); connection=get_connection(); clauses=['guild_id=?']; params=[guild_id]
    if template_type: clauses.append('template_type=?'); params.append(template_type)
    if owner_id is not None:
        if include_public: clauses.append("(owner_id=? OR visibility='public')")
        else: clauses.append('owner_id=?')
        params.append(owner_id)
    rows=connection.execute("SELECT id,owner_id,name,template_type,payload_json,visibility,category,allowed_role_ids_json,updated_at FROM templates WHERE "+' AND '.join(clauses)+' ORDER BY updated_at DESC',params).fetchall(); connection.close(); return rows


def delete_template(template_id,owner_id):
    _ensure_extended_tables(); connection=get_connection(); c=connection.cursor(); c.execute('DELETE FROM templates WHERE id=? AND owner_id=?',(template_id,owner_id)); changed=c.rowcount>0; connection.commit(); connection.close(); return changed


def save_webhook(guild_id,owner_id,webhook_id,channel_id,name,url,avatar_url=None):
    _ensure_extended_tables(); now=_now(); connection=get_connection(); c=connection.cursor(); c.execute('INSERT INTO webhooks (guild_id,owner_id,webhook_id,channel_id,name,url,avatar_url,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)',(guild_id,owner_id,webhook_id,channel_id,name,url,avatar_url,now,now)); rid=c.lastrowid; connection.commit(); connection.close(); return rid


def get_webhook(record_id):
    _ensure_extended_tables(); connection=get_connection(); row=connection.execute('SELECT id,guild_id,owner_id,webhook_id,channel_id,name,url,avatar_url,created_at,updated_at FROM webhooks WHERE id=?',(record_id,)).fetchone(); connection.close(); return row


def get_webhooks(guild_id,owner_id=None):
    _ensure_extended_tables(); connection=get_connection();
    if owner_id is None: rows=connection.execute('SELECT id,owner_id,webhook_id,channel_id,name,avatar_url,created_at,updated_at FROM webhooks WHERE guild_id=? ORDER BY updated_at DESC',(guild_id,)).fetchall()
    else: rows=connection.execute('SELECT id,owner_id,webhook_id,channel_id,name,avatar_url,created_at,updated_at FROM webhooks WHERE guild_id=? AND owner_id=? ORDER BY updated_at DESC',(guild_id,owner_id)).fetchall()
    connection.close(); return rows


def update_webhook_record(record_id,name=None,channel_id=None,url=None,avatar_url=None):
    row=get_webhook(record_id)
    if not row: return False
    vals=(name if name is not None else row[5],channel_id if channel_id is not None else row[4],url if url is not None else row[6],avatar_url if avatar_url is not None else row[7],_now(),record_id)
    connection=get_connection(); connection.execute('UPDATE webhooks SET name=?,channel_id=?,url=?,avatar_url=?,updated_at=? WHERE id=?',vals); connection.commit(); connection.close(); return True


def delete_webhook_record(record_id):
    _ensure_extended_tables(); connection=get_connection(); c=connection.cursor(); c.execute('DELETE FROM webhooks WHERE id=?',(record_id,)); changed=c.rowcount>0; connection.commit(); connection.close(); return changed


def log_webhook_event(guild_id,owner_id,webhook_id,action,channel_id=None,details=None):
    _ensure_extended_tables(); connection=get_connection(); connection.execute('INSERT INTO webhook_history (guild_id,owner_id,webhook_id,action,channel_id,details,created_at) VALUES (?,?,?,?,?,?,?)',(guild_id,owner_id,webhook_id,action,channel_id,details,_now())); connection.commit(); connection.close()


def get_webhook_history(guild_id,webhook_id=None,limit=20):
    _ensure_extended_tables(); connection=get_connection();
    if webhook_id is None: rows=connection.execute('SELECT owner_id,webhook_id,action,channel_id,details,created_at FROM webhook_history WHERE guild_id=? ORDER BY id DESC LIMIT ?',(guild_id,limit)).fetchall()
    else: rows=connection.execute('SELECT owner_id,webhook_id,action,channel_id,details,created_at FROM webhook_history WHERE guild_id=? AND webhook_id=? ORDER BY id DESC LIMIT ?',(guild_id,webhook_id,limit)).fetchall()
    connection.close(); return rows


def log_audit(guild_id, actor_id, action, target_type=None, target_id=None, details=None):
    _ensure_extended_tables()
    connection = get_connection()
    connection.execute("""
        INSERT INTO audit_logs
        (guild_id, actor_id, action, target_type, target_id, details, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (guild_id, actor_id, action, target_type, str(target_id) if target_id is not None else None,
           details, _now()))
    connection.commit()
    connection.close()


def get_audit_logs(guild_id, limit=50):
    _ensure_extended_tables()
    connection = get_connection()
    rows = connection.execute("""
        SELECT actor_id, action, target_type, target_id, details, created_at
        FROM audit_logs
        WHERE guild_id = ?
        ORDER BY id DESC
        LIMIT ?
    """, (guild_id, limit)).fetchall()
    connection.close()
    return rows
