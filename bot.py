import json
import os
import time
from datetime import datetime

import discord
from discord.ext import commands
from dotenv import load_dotenv

from database import (
    init_database,
    add_command_access,
    get_command_access,
    get_command_access_details,
    remove_command_access,
    set_access_level,
    get_access_level,
    get_member_info,
    set_role_access,
    remove_role_access,
    deny_user,
    is_user_denied,
    undeny_user,
    save_message_build,
    get_message_build,
    get_message_builds,
    delete_message_build,
    save_button_set,
    get_button_set,
    get_button_sets,
    delete_button_set,
)

from extended_modules import register_extended


load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))

# =========================
# CONSTANTS
# =========================

ACCESS_LEVELS = {
    "limited": 0,
    "member": 1,
    "staff": 2,
    "admin": 3,
    "owner": 4,
}

ACCESS_LABELS = {
    "limited": "◽ Ограниченный пользователь",
    "member": "👤 Пользователь",
    "staff": "🔧 Staff",
    "admin": "🛡️ Администратор бота",
    "owner": "👑 Владелец",
}

COMMAND_MIN_LEVELS = {
    "ping": "staff",
    "access": "staff",
    "embed": "staff",
    "buttons": "staff",
    "forms": "staff",
    "select": "staff",
    "templates": "staff",
    "messages": "staff",
    "webhooks": "admin",
}

EMBED_COLOR = discord.Color.blurple()

MAX_EMBEDS = 10
MAX_BUTTONS = 5

BUTTON_STYLES = {
    "primary": discord.ButtonStyle.primary,
    "secondary": discord.ButtonStyle.secondary,
    "success": discord.ButtonStyle.success,
    "danger": discord.ButtonStyle.danger,
    "link": discord.ButtonStyle.link,
}


# =========================
# DISCORD
# =========================

intents = discord.Intents.default()
intents.members = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


# =========================
# PERMISSIONS
# =========================

def is_owner(interaction):
    return interaction.user.id == OWNER_ID


def get_user_level(interaction):
    if is_owner(interaction):
        return "owner"

    if interaction.guild is None:
        return "member"

    return get_access_level(
        interaction.guild.id,
        interaction.user.id
    )


def level_value(level):
    return ACCESS_LEVELS.get(level, 0)


def can_manage_access(interaction):
    return level_value(get_user_level(interaction)) >= level_value("admin")


def can_view_access(interaction):
    return level_value(get_user_level(interaction)) >= level_value("staff")


def can_assign_level(interaction, target_level):
    actor_level = get_user_level(interaction)

    if target_level == "owner":
        return is_owner(interaction)

    if target_level in ("staff", "member", "limited"):
        return level_value(actor_level) >= level_value("admin")

    if target_level == "admin":
        return is_owner(interaction)

    return False


def has_command_access(interaction, command_name):
    if is_owner(interaction):
        return True

    if interaction.guild is None:
        return False

    users = get_command_access(
        interaction.guild.id,
        command_name
    )

    if interaction.user.id in users:
        return True

    current_level = get_user_level(interaction)
    required_level = COMMAND_MIN_LEVELS.get(command_name)

    if required_level is None:
        return False

    return level_value(current_level) >= level_value(required_level)


async def require_command_access(interaction, command_name):
    if has_command_access(interaction, command_name):
        return True

    await interaction.response.send_message(
        "РЕПЛИКА ОС — ДОСТУП ЗАПРЕЩЁН",
        ephemeral=True
    )
    return False


# =========================
# HELPERS
# =========================

def format_expiration(expires_at):
    if expires_at is None:
        return "Постоянный"

    return datetime.fromtimestamp(expires_at).strftime(
        "%d.%m.%Y %H:%M"
    )


def get_bot_commands():
    return [
        (command.name, command.description or "Без описания")
        for command in bot.tree.get_commands()
    ]


def safe_json_loads(value, fallback):
    try:
        result = json.loads(value)
        return result
    except (TypeError, json.JSONDecodeError):
        return fallback


def normalize_url(url):
    url = (url or "").strip()
    if not url:
        return None

    if not url.startswith(("http://", "https://")):
        return "https://" + url

    return url


def build_discord_embed(data):
    embed = discord.Embed(
        title=data.get("title") or discord.Embed.Empty,
        description=data.get("description") or discord.Embed.Empty,
        url=normalize_url(data.get("url")),
        color=int(data.get("color", 0x5865F2))
    )

    author_name = data.get("author_name")
    if author_name:
        embed.set_author(
            name=author_name,
            url=normalize_url(data.get("author_url")),
            icon_url=normalize_url(data.get("author_icon"))
        )

    thumbnail = normalize_url(data.get("thumbnail"))
    if thumbnail:
        embed.set_thumbnail(url=thumbnail)

    image = normalize_url(data.get("image"))
    if image:
        embed.set_image(url=image)

    footer_text = data.get("footer_text")
    if footer_text:
        embed.set_footer(
            text=footer_text,
            icon_url=normalize_url(data.get("footer_icon"))
        )

    if data.get("timestamp"):
        embed.timestamp = datetime.now()

    for field in data.get("fields", []):
        name = str(field.get("name", "‎"))[:256]
        value = str(field.get("value", "‎"))[:1024]
        embed.add_field(
            name=name,
            value=value,
            inline=bool(field.get("inline", False))
        )

    return embed


def build_button_view(buttons):
    if not buttons:
        return None

    view = discord.ui.View(timeout=None)

    for item in buttons[:MAX_BUTTONS]:
        label = str(item.get("label", "Кнопка"))[:80]
        emoji = item.get("emoji")
        style_name = item.get("style", "primary")
        action = item.get("action", "link")
        value = item.get("value")

        style = BUTTON_STYLES.get(
            style_name,
            discord.ButtonStyle.primary
        )

        if action == "link":
            url = normalize_url(value)
            if not url:
                continue

            button = discord.ui.Button(
                label=label,
                emoji=emoji,
                style=discord.ButtonStyle.link,
                url=url
            )
            view.add_item(button)
            continue

        button = discord.ui.Button(
            label=label,
            emoji=emoji,
            style=style
        )

        async def callback(
            interaction,
            action=action,
            value=value
        ):
            # Action system foundation.
            # Forms/selects/actions will plug in here later.
            if action == "message":
                await interaction.response.send_message(
                    value or "РЕПЛИКА ОС — действие выполнено.",
                    ephemeral=True
                )
            elif action == "confirm":
                await interaction.response.send_message(
                    value or "РЕПЛИКА ОС — подтверждение получено.",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    "РЕПЛИКА ОС — это действие пока находится "
                    "в разработке.",
                    ephemeral=True
                )

        button.callback = callback
        view.add_item(button)

    return view


# =========================
# READY
# =========================

@bot.event
async def on_ready():
    init_database()

    print(f"Бот запущен: {bot.user}")

    try:
        synced = await bot.tree.sync()
        print(f"Синхронизировано команд: {len(synced)}")
    except Exception as error:
        print(f"Ошибка синхронизации: {error}")


# =========================
# PING
# =========================

@bot.tree.command(
    name="ping",
    description="Проверка работы бота"
)
async def ping(interaction):
    if not await require_command_access(interaction, "ping"):
        return

    await interaction.response.send_message(
        "🏓 Pong!",
        ephemeral=True
    )


# ============================================================
# ACCESS MANAGER
# ============================================================

class AccessView(discord.ui.View):

    def __init__(self, access_level):
        super().__init__(timeout=300)
        self.access_level = access_level

    @discord.ui.button(
        label="Пользователи",
        emoji="👥",
        style=discord.ButtonStyle.secondary
    )
    async def users_button(self, interaction, button):
        if not can_view_access(interaction):
            await interaction.response.send_message(
                "РЕПЛИКА ОС — ДОСТУП ЗАПРЕЩЁН",
                ephemeral=True
            )
            return

        await interaction.response.edit_message(
            embed=discord.Embed(
                title="ПОЛЬЗОВАТЕЛИ",
                description="Выберите пользователя для просмотра уровня доступа.",
                color=EMBED_COLOR
            ),
            view=UserManagementView(self.access_level)
        )

    @discord.ui.button(
        label="Команды",
        emoji="🧩",
        style=discord.ButtonStyle.primary
    )
    async def commands_button(self, interaction, button):
        if not can_view_access(interaction):
            await interaction.response.send_message(
                "РЕПЛИКА ОС — ДОСТУП ЗАПРЕЩЁН",
                ephemeral=True
            )
            return

        await interaction.response.edit_message(
            embed=discord.Embed(
                title="КОМАНДЫ",
                description="Выберите команду для просмотра и настройки доступа.",
                color=EMBED_COLOR
            ),
            view=CommandSelectView(self.access_level)
        )

    @discord.ui.button(
        label="История",
        emoji="📜",
        style=discord.ButtonStyle.secondary
    )
    async def history_button(self, interaction, button):
        await interaction.response.send_message(
            "Раздел истории пока в разработке.",
            ephemeral=True
        )

    @discord.ui.button(
        label="Доступ по ролям",
        emoji="🎭",
        style=discord.ButtonStyle.secondary
    )
    async def role_access_button(self, interaction, button):
        if not can_manage_access(interaction):
            await interaction.response.send_message(
                "Нужны права администратора.", ephemeral=True
            )
            return
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="ДОСТУП ПО РОЛЯМ",
                description="Выберите Discord-роль и назначьте ей уровень доступа.",
                color=EMBED_COLOR
            ),
            view=RoleAccessView()
        )

    @discord.ui.button(
        label="Запреты",
        emoji="🚫",
        style=discord.ButtonStyle.danger
    )
    async def denials_button(self, interaction, button):
        if not can_manage_access(interaction):
            await interaction.response.send_message(
                "Нужны права администратора.", ephemeral=True
            )
            return
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="ЗАПРЕТ ДОСТУПА",
                description="Запрет полностью блокирует использование бота конкретным пользователем.",
                color=EMBED_COLOR
            ),
            view=DenialAccessView()
        )

    @discord.ui.button(
        label="Настройки",
        emoji="⚙️",
        style=discord.ButtonStyle.secondary
    )
    async def settings_button(self, interaction, button):
        if not is_owner(interaction):
            await interaction.response.send_message(
                "Настройки доступны только владельцу.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            "Раздел настроек пока в разработке.",
            ephemeral=True
        )


class UserManagementView(discord.ui.View):

    def __init__(self, access_level):
        super().__init__(timeout=300)
        self.access_level = access_level

        self.user_select = discord.ui.UserSelect(
            placeholder="Выберите пользователя",
            min_values=1,
            max_values=1
        )
        self.user_select.callback = self.user_selected
        self.add_item(self.user_select)

    async def user_selected(self, interaction):
        user = self.user_select.values[0]

        level, expires_at = get_member_info(
            interaction.guild.id,
            user.id
        )

        embed = discord.Embed(
            title="ПОЛЬЗОВАТЕЛЬ",
            description=(
                f"**Пользователь:** {user.mention}\n\n"
                f"**Уровень:** {ACCESS_LABELS.get(level, level)}\n"
                f"**Действует до:** {format_expiration(expires_at)}"
            ),
            color=EMBED_COLOR
        )

        await interaction.response.edit_message(
            embed=embed,
            view=UserLevelView(user.id, user.mention)
        )


class UserLevelView(discord.ui.View):

    def __init__(self, user_id, user_mention):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.user_mention = user_mention

    async def set_level(self, interaction, level):
        if not can_assign_level(interaction, level):
            await interaction.response.send_message(
                "У вас недостаточно прав для назначения этого уровня.",
                ephemeral=True
            )
            return

        set_access_level(
            interaction.guild.id,
            self.user_id,
            level,
            None
        )

        await interaction.response.send_message(
            f"{self.user_mention} → {ACCESS_LABELS[level]}",
            ephemeral=True
        )

    @discord.ui.button(
        label="Ограниченный",
        style=discord.ButtonStyle.secondary
    )
    async def limited_button(self, interaction, button):
        await self.set_level(interaction, "limited")

    @discord.ui.button(
        label="Обычный участник",
        style=discord.ButtonStyle.secondary
    )
    async def member_button(self, interaction, button):
        await self.set_level(interaction, "member")

    @discord.ui.button(
        label="Staff",
        style=discord.ButtonStyle.primary
    )
    async def staff_button(self, interaction, button):
        await self.set_level(interaction, "staff")

    @discord.ui.button(
        label="Администратор",
        style=discord.ButtonStyle.success
    )
    async def admin_button(self, interaction, button):
        await self.set_level(interaction, "admin")

    @discord.ui.button(
        label="Временный уровень",
        emoji="⏳",
        style=discord.ButtonStyle.secondary
    )
    async def temporary_button(self, interaction, button):
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="ВРЕМЕННЫЙ УРОВЕНЬ",
                description=f"Выберите срок для {self.user_mention}.",
                color=EMBED_COLOR
            ),
            view=TemporaryLevelView(self.user_id, self.user_mention)
        )


class TemporaryLevelView(discord.ui.View):

    def __init__(self, user_id, user_mention):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.user_mention = user_mention

    async def apply(self, interaction, level, seconds):
        if not can_assign_level(interaction, level):
            await interaction.response.send_message(
                "У вас недостаточно прав.",
                ephemeral=True
            )
            return

        expires_at = int(time.time() + seconds)

        set_access_level(
            interaction.guild.id,
            self.user_id,
            level,
            expires_at
        )

        await interaction.response.send_message(
            f"{self.user_mention} получил {ACCESS_LABELS[level]} временно.",
            ephemeral=True
        )

    @discord.ui.button(
        label="Staff · 1 день",
        style=discord.ButtonStyle.primary
    )
    async def staff_day(self, interaction, button):
        await self.apply(interaction, "staff", 86400)

    @discord.ui.button(
        label="Staff · 7 дней",
        style=discord.ButtonStyle.primary
    )
    async def staff_week(self, interaction, button):
        await self.apply(interaction, "staff", 604800)

    @discord.ui.button(
        label="Admin · 1 день",
        style=discord.ButtonStyle.success
    )
    async def admin_day(self, interaction, button):
        await self.apply(interaction, "admin", 86400)


class CommandSelectView(discord.ui.View):

    def __init__(self, access_level):
        super().__init__(timeout=300)
        self.access_level = access_level

        for command_name, description in get_bot_commands():
            button = discord.ui.Button(
                label=f"/{command_name}",
                style=discord.ButtonStyle.secondary
            )

            async def command_callback(
                interaction,
                command_name=command_name,
                description=description
            ):
                if interaction.guild is None:
                    return

                details = get_command_access_details(
                    interaction.guild.id,
                    command_name
                )

                if details:
                    access_text = "\n".join(
                        f"<@{user_id}> — {format_expiration(expires_at)}"
                        for user_id, expires_at in details
                    )
                else:
                    access_text = "Индивидуального доступа нет."

                required = COMMAND_MIN_LEVELS.get(command_name)
                level_text = ACCESS_LABELS.get(required, "Не задан")

                embed = discord.Embed(
                    title="COMMAND ACCESS",
                    description=(
                        f"**Команда:** `/{command_name}`\n"
                        f"**Описание:** {description}\n\n"
                        f"**Минимальный уровень:** {level_text}\n\n"
                        f"**Индивидуальный доступ:**\n{access_text}"
                    ),
                    color=EMBED_COLOR
                )

                await interaction.response.edit_message(
                    embed=embed,
                    view=CommandAccessView(command_name, self.access_level)
                )

            button.callback = command_callback
            self.add_item(button)


class CommandAccessView(discord.ui.View):

    def __init__(self, command_name, access_level):
        super().__init__(timeout=300)
        self.command_name = command_name
        self.access_level = access_level

    async def denied(self, interaction):
        await interaction.response.send_message(
            "Изменять доступ могут только администратор и владелец.",
            ephemeral=True
        )

    @discord.ui.button(
        label="Добавить пользователя",
        emoji="➕",
        style=discord.ButtonStyle.success
    )
    async def add_user(self, interaction, button):
        if not can_manage_access(interaction):
            await self.denied(interaction)
            return

        await interaction.response.send_message(
            f"Выберите пользователя для доступа к `/{self.command_name}`:",
            view=UserSelectView(self.command_name),
            ephemeral=True
        )

    @discord.ui.button(
        label="Убрать пользователя",
        emoji="➖",
        style=discord.ButtonStyle.danger
    )
    async def remove_user(self, interaction, button):
        if not can_manage_access(interaction):
            await self.denied(interaction)
            return

        await interaction.response.send_message(
            f"Выберите пользователя, у которого нужно убрать доступ к "
            f"`/{self.command_name}`:",
            view=RemoveUserSelectView(self.command_name),
            ephemeral=True
        )

    @discord.ui.button(
        label="Временный доступ",
        emoji="⏳",
        style=discord.ButtonStyle.primary
    )
    async def temporary_access(self, interaction, button):
        if not can_manage_access(interaction):
            await self.denied(interaction)
            return

        await interaction.response.send_message(
            f"Выберите пользователя для временного доступа к "
            f"`/{self.command_name}`:",
            view=TemporaryCommandUserView(self.command_name),
            ephemeral=True
        )


class UserSelectView(discord.ui.View):

    def __init__(self, command_name):
        super().__init__(timeout=300)
        self.command_name = command_name

        self.user_select = discord.ui.UserSelect(
            placeholder="Выберите пользователя",
            min_values=1,
            max_values=1
        )
        self.user_select.callback = self.user_selected
        self.add_item(self.user_select)

    async def user_selected(self, interaction):
        user = self.user_select.values[0]

        add_command_access(
            interaction.guild.id,
            self.command_name,
            user.id,
            None
        )

        await interaction.response.send_message(
            f"Доступ к `/{self.command_name}` добавлен для "
            f"{user.mention} на постоянной основе.",
            ephemeral=True
        )


class RemoveUserSelectView(discord.ui.View):

    def __init__(self, command_name):
        super().__init__(timeout=300)
        self.command_name = command_name

        self.user_select = discord.ui.UserSelect(
            placeholder="Выберите пользователя",
            min_values=1,
            max_values=1
        )
        self.user_select.callback = self.user_selected
        self.add_item(self.user_select)

    async def user_selected(self, interaction):
        user = self.user_select.values[0]

        remove_command_access(
            interaction.guild.id,
            self.command_name,
            user.id
        )

        await interaction.response.send_message(
            f"Доступ к `/{self.command_name}` убран для {user.mention}.",
            ephemeral=True
        )


class TemporaryCommandUserView(discord.ui.View):

    def __init__(self, command_name):
        super().__init__(timeout=300)
        self.command_name = command_name

        self.user_select = discord.ui.UserSelect(
            placeholder="Выберите пользователя",
            min_values=1,
            max_values=1
        )
        self.user_select.callback = self.user_selected
        self.add_item(self.user_select)

    async def user_selected(self, interaction):
        user = self.user_select.values[0]

        await interaction.response.edit_message(
            embed=discord.Embed(
                title="ВРЕМЕННЫЙ ДОСТУП",
                description=(
                    f"Выберите срок доступа {user.mention} "
                    f"к `/{self.command_name}`."
                ),
                color=EMBED_COLOR
            ),
            view=TemporaryCommandDurationView(
                self.command_name,
                user.id,
                user.mention
            )
        )


class TemporaryCommandDurationView(discord.ui.View):

    def __init__(self, command_name, user_id, user_mention):
        super().__init__(timeout=300)
        self.command_name = command_name
        self.user_id = user_id
        self.user_mention = user_mention

    async def apply(self, interaction, seconds):
        expires_at = int(time.time() + seconds)

        add_command_access(
            interaction.guild.id,
            self.command_name,
            self.user_id,
            expires_at
        )

        await interaction.response.send_message(
            f"Временный доступ к `/{self.command_name}` выдан "
            f"{self.user_mention}.",
            ephemeral=True
        )

    @discord.ui.button(
        label="1 час",
        style=discord.ButtonStyle.secondary
    )
    async def hour(self, interaction, button):
        await self.apply(interaction, 3600)

    @discord.ui.button(
        label="1 день",
        style=discord.ButtonStyle.primary
    )
    async def day(self, interaction, button):
        await self.apply(interaction, 86400)

    @discord.ui.button(
        label="3 дня",
        style=discord.ButtonStyle.primary
    )
    async def three_days(self, interaction, button):
        await self.apply(interaction, 259200)

    @discord.ui.button(
        label="7 дней",
        style=discord.ButtonStyle.success
    )
    async def week(self, interaction, button):
        await self.apply(interaction, 604800)


@bot.tree.command(
    name="access",
    description="Управление доступом к функциям бота"
)
async def access(interaction):
    if not can_view_access(interaction):
        await interaction.response.send_message(
            "РЕПЛИКА ОС — ДОСТУП ЗАПРЕЩЁН",
            ephemeral=True
        )
        return

    access_level = get_user_level(interaction)

    embed = discord.Embed(
        title="ACCESS MANAGER",
        description=(
            f"Ваш уровень: {ACCESS_LABELS.get(access_level)}\n\n"
            "Управление пользователями, уровнями и доступом к командам."
        ),
        color=EMBED_COLOR
    )

    if bot.user:
        embed.set_thumbnail(url=bot.user.display_avatar.url)

    await interaction.response.send_message(
        embed=embed,
        view=AccessView(access_level),
        ephemeral=True
    )


# ============================================================
# MESSAGE BUILD / EMBED BUILDER
# ============================================================

class EmbedBuilderState:

    def __init__(self):
        self.content = ""
        self.embeds = []
        self.buttons = []
        self.name = "Новый Message Build"
        self.category = "general"
        self.visibility = "private"
        self.channel_id = None

    def preview_embed(self):
        if self.embeds:
            return build_discord_embed(self.embeds[0])

        return discord.Embed(
            title="ПРЕДПРОСМОТР",
            description="Embed пока пуст.",
            color=EMBED_COLOR
        )


class EmbedBasicModal(discord.ui.Modal, title="ОСНОВНОЙ EMBED"):

    title_input = discord.ui.TextInput(
        label="Title",
        placeholder="Заголовок embed",
        required=False,
        max_length=256
    )

    description_input = discord.ui.TextInput(
        label="Description",
        placeholder="Основной текст",
        required=False,
        style=discord.TextStyle.paragraph,
        max_length=4000
    )

    url_input = discord.ui.TextInput(
        label="URL",
        placeholder="https://...",
        required=False,
        max_length=1000
    )

    color_input = discord.ui.TextInput(
        label="Цвет HEX",
        placeholder="#5865F2",
        required=False,
        max_length=7
    )

    def __init__(self, state):
        super().__init__()
        self.state = state

        existing = state.embeds[0] if state.embeds else {}

        self.title_input.default = existing.get("title", "")
        self.description_input.default = existing.get("description", "")
        self.url_input.default = existing.get("url", "")
        self.color_input.default = existing.get("color_hex", "#5865F2")

    async def on_submit(self, interaction):
        color_text = self.color_input.value.strip().replace("#", "")

        try:
            color_value = int(color_text, 16) if color_text else 0x5865F2
            if not 0 <= color_value <= 0xFFFFFF:
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "HEX-цвет указан некорректно. Используй формат вроде `#5865F2`.",
                ephemeral=True
            )
            return

        data = {
            "title": self.title_input.value.strip(),
            "description": self.description_input.value.strip(),
            "url": normalize_url(self.url_input.value),
            "color": color_value,
            "color_hex": f"#{color_value:06X}",
            "fields": [],
        }

        if self.state.embeds:
            old = self.state.embeds[0]
            for key in (
                "author_name", "author_url", "author_icon",
                "thumbnail", "image", "footer_text", "footer_icon",
                "timestamp", "fields"
            ):
                if key in old:
                    data[key] = old[key]

        self.state.embeds = [data]

        await interaction.response.edit_message(
            embed=render_build_preview(self.state),
            view=EmbedDesignView(self.state)
        )


class EmbedMediaModal(discord.ui.Modal, title="ИЗОБРАЖЕНИЯ EMBED"):

    thumbnail_input = discord.ui.TextInput(
        label="Thumbnail URL",
        placeholder="Прямая HTTPS-ссылка на изображение",
        required=False,
        max_length=1000
    )

    image_input = discord.ui.TextInput(
        label="Image URL",
        placeholder="Прямая HTTPS-ссылка на изображение",
        required=False,
        max_length=1000
    )

    def __init__(self, state):
        super().__init__()
        self.state = state
        existing = state.embeds[0] if state.embeds else {}

        self.thumbnail_input.default = existing.get("thumbnail", "")
        self.image_input.default = existing.get("image", "")

    async def on_submit(self, interaction):
        if not self.state.embeds:
            self.state.embeds = [{
                "title": "",
                "description": "",
                "color": 0x5865F2,
                "fields": []
            }]

        self.state.embeds[0]["thumbnail"] = normalize_url(
            self.thumbnail_input.value
        )
        self.state.embeds[0]["image"] = normalize_url(
            self.image_input.value
        )

        await interaction.response.edit_message(
            embed=render_build_preview(self.state),
            view=EmbedDesignView(self.state)
        )


class EmbedAuthorFooterModal(discord.ui.Modal, title="AUTHOR / FOOTER"):

    author_input = discord.ui.TextInput(
        label="Author name",
        required=False,
        max_length=256
    )

    author_url_input = discord.ui.TextInput(
        label="Author URL",
        required=False,
        max_length=1000
    )

    author_icon_input = discord.ui.TextInput(
        label="Author icon URL",
        required=False,
        max_length=1000
    )

    footer_input = discord.ui.TextInput(
        label="Footer",
        required=False,
        max_length=2048
    )

    footer_icon_input = discord.ui.TextInput(
        label="Footer icon URL",
        required=False,
        max_length=1000
    )

    def __init__(self, state):
        super().__init__()
        self.state = state
        existing = state.embeds[0] if state.embeds else {}

        self.author_input.default = existing.get("author_name", "")
        self.author_url_input.default = existing.get("author_url", "")
        self.author_icon_input.default = existing.get("author_icon", "")
        self.footer_input.default = existing.get("footer_text", "")
        self.footer_icon_input.default = existing.get("footer_icon", "")

    async def on_submit(self, interaction):
        if not self.state.embeds:
            self.state.embeds = [{
                "title": "",
                "description": "",
                "color": 0x5865F2,
                "fields": []
            }]

        data = self.state.embeds[0]
        data["author_name"] = self.author_input.value.strip()
        data["author_url"] = normalize_url(self.author_url_input.value)
        data["author_icon"] = normalize_url(self.author_icon_input.value)
        data["footer_text"] = self.footer_input.value.strip()
        data["footer_icon"] = normalize_url(self.footer_icon_input.value)

        await interaction.response.edit_message(
            embed=render_build_preview(self.state),
            view=EmbedDesignView(self.state)
        )


class EmbedFieldModal(discord.ui.Modal, title="FIELD"):

    name_input = discord.ui.TextInput(
        label="Название поля",
        required=True,
        max_length=256
    )

    value_input = discord.ui.TextInput(
        label="Значение",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=1024
    )

    inline_input = discord.ui.TextInput(
        label="Inline? yes / no",
        required=False,
        max_length=3
    )

    def __init__(self, state):
        super().__init__()
        self.state = state

    async def on_submit(self, interaction):
        if not self.state.embeds:
            self.state.embeds = [{
                "title": "",
                "description": "",
                "color": 0x5865F2,
                "fields": []
            }]

        inline = self.inline_input.value.strip().lower() in {
            "yes", "y", "да", "д"
        }

        self.state.embeds[0].setdefault("fields", []).append({
            "name": self.name_input.value,
            "value": self.value_input.value,
            "inline": inline
        })

        await interaction.response.edit_message(
            embed=render_build_preview(self.state),
            view=EmbedDesignView(self.state)
        )


class EmbedDesignView(discord.ui.View):

    def __init__(self, state):
        super().__init__(timeout=900)
        self.state = state

    @discord.ui.button(
        label="Основное",
        emoji="✏️",
        style=discord.ButtonStyle.primary
    )
    async def basic(self, interaction, button):
        await interaction.response.send_modal(
            EmbedBasicModal(self.state)
        )

    @discord.ui.button(
        label="Изображения",
        emoji="🖼️",
        style=discord.ButtonStyle.secondary
    )
    async def media(self, interaction, button):
        await interaction.response.send_modal(
            EmbedMediaModal(self.state)
        )

    @discord.ui.button(
        label="Author / Footer",
        emoji="🏷️",
        style=discord.ButtonStyle.secondary
    )
    async def author_footer(self, interaction, button):
        await interaction.response.send_modal(
            EmbedAuthorFooterModal(self.state)
        )

    @discord.ui.button(
        label="Добавить поле",
        emoji="➕",
        style=discord.ButtonStyle.secondary
    )
    async def add_field(self, interaction, button):
        if self.state.embeds and len(
            self.state.embeds[0].get("fields", [])
        ) >= 25:
            await interaction.response.send_message(
                "В одном embed максимум 25 полей.",
                ephemeral=True
            )
            return

        await interaction.response.send_modal(
            EmbedFieldModal(self.state)
        )

    @discord.ui.button(
        label="Добавить embed",
        emoji="🧩",
        style=discord.ButtonStyle.secondary
    )
    async def add_embed(self, interaction, button):
        if len(self.state.embeds) >= MAX_EMBEDS:
            await interaction.response.send_message(
                "Discord позволяет максимум 10 embed'ов в одном сообщении.",
                ephemeral=True
            )
            return

        self.state.embeds.append({
            "title": f"Embed {len(self.state.embeds) + 1}",
            "description": "",
            "color": 0x5865F2,
            "fields": []
        })

        await interaction.response.edit_message(
            embed=render_build_preview(self.state),
            view=self
        )

    @discord.ui.button(
        label="Подтвердить дизайн",
        emoji="✅",
        style=discord.ButtonStyle.success
    )
    async def confirm(self, interaction, button):
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="ПОНАДОБЯТСЯ КНОПКИ?",
                description=(
                    "Дизайн сообщения подтверждён.\n\n"
                    "Теперь отдельно соберём интерактив."
                ),
                color=EMBED_COLOR
            ),
            view=ButtonDecisionView(self.state)
        )


class ButtonDecisionView(discord.ui.View):

    def __init__(self, state):
        super().__init__(timeout=900)
        self.state = state

    @discord.ui.button(
        label="Назад",
        emoji="↩️",
        style=discord.ButtonStyle.secondary
    )
    async def back(self, interaction, button):
        await interaction.response.edit_message(
            embed=render_build_preview(self.state),
            view=EmbedDesignView(self.state)
        )

    @discord.ui.button(
        label="Да, создать форму",
        emoji="📝",
        style=discord.ButtonStyle.primary
    )
    async def form(self, interaction, button):
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="FORM BUILDER",
                description="Настройка формы, вопросов, канала заявок, reviewers и действия после решения.",
                color=EMBED_COLOR
            ),
            view=__import__("extended_modules").FormStartView(interaction.guild.id, interaction.user.id)
        )

    @discord.ui.button(
        label="Да, создать список",
        emoji="📋",
        style=discord.ButtonStyle.primary
    )
    async def select_menu(self, interaction, button):
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="SELECT MENU",
                description="Выберите тип интерактивного списка.",
                color=EMBED_COLOR
            ),
            view=__import__("extended_modules").SelectHome()
        )

    @discord.ui.button(
        label="Да, обычная кнопка",
        emoji="🔘",
        style=discord.ButtonStyle.primary
    )
    async def ordinary(self, interaction, button):
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="BUTTON BUILDER",
                description="Создай до 5 кнопок для этого Message Build.",
                color=EMBED_COLOR
            ),
            view=InlineButtonBuilderView(self.state)
        )

    @discord.ui.button(
        label="Нет, кнопки не нужны",
        emoji="❌",
        style=discord.ButtonStyle.secondary
    )
    async def none(self, interaction, button):
        await finish_message_build(interaction, self.state)


class InlineButtonModal(discord.ui.Modal, title="НОВАЯ КНОПКА"):

    label_input = discord.ui.TextInput(
        label="Текст кнопки",
        required=True,
        max_length=80
    )

    emoji_input = discord.ui.TextInput(
        label="Emoji",
        placeholder="Например: ✨ или :my_emoji:",
        required=False,
        max_length=100
    )

    style_input = discord.ui.TextInput(
        label="Стиль: primary / secondary / success / danger",
        required=True,
        max_length=10
    )

    action_input = discord.ui.TextInput(
        label="Действие: link / message / confirm",
        required=True,
        max_length=20
    )

    value_input = discord.ui.TextInput(
        label="URL или текст действия",
        required=False,
        style=discord.TextStyle.paragraph,
        max_length=1000
    )

    def __init__(self, state):
        super().__init__()
        self.state = state

    async def on_submit(self, interaction):
        if len(self.state.buttons) >= MAX_BUTTONS:
            await interaction.response.send_message(
                "В одном Message Build сейчас максимум 5 кнопок.",
                ephemeral=True
            )
            return

        style = self.style_input.value.strip().lower()
        action = self.action_input.value.strip().lower()

        if style not in {"primary", "secondary", "success", "danger"}:
            await interaction.response.send_message(
                "Стиль должен быть: primary, secondary, success или danger.",
                ephemeral=True
            )
            return

        if action not in {"link", "message", "confirm"}:
            await interaction.response.send_message(
                "Действие должно быть: link, message или confirm.",
                ephemeral=True
            )
            return

        if action == "link" and not normalize_url(self.value_input.value):
            await interaction.response.send_message(
                "Для link нужен URL.",
                ephemeral=True
            )
            return

        self.state.buttons.append({
            "label": self.label_input.value,
            "emoji": self.emoji_input.value.strip() or None,
            "style": style,
            "action": action,
            "value": (
                normalize_url(self.value_input.value)
                if action == "link"
                else self.value_input.value
            )
        })

        await interaction.response.edit_message(
            embed=render_button_preview(self.state),
            view=InlineButtonBuilderView(self.state)
        )


class InlineButtonBuilderView(discord.ui.View):

    def __init__(self, state):
        super().__init__(timeout=900)
        self.state = state

    @discord.ui.button(
        label="Добавить кнопку",
        emoji="➕",
        style=discord.ButtonStyle.success
    )
    async def add(self, interaction, button):
        if len(self.state.buttons) >= MAX_BUTTONS:
            await interaction.response.send_message(
                "Лимит достигнут: максимум 5 кнопок.",
                ephemeral=True
            )
            return

        await interaction.response.send_modal(
            InlineButtonModal(self.state)
        )

    @discord.ui.button(
        label="Готово",
        emoji="✅",
        style=discord.ButtonStyle.primary
    )
    async def done(self, interaction, button):
        await finish_message_build(interaction, self.state)

    @discord.ui.button(
        label="Без кнопок",
        emoji="❌",
        style=discord.ButtonStyle.secondary
    )
    async def clear(self, interaction, button):
        self.state.buttons = []
        await finish_message_build(interaction, self.state)


def render_build_preview(state):
    if not state.embeds:
        return discord.Embed(
            title="MESSAGE BUILD",
            description="Добавь первый embed.",
            color=EMBED_COLOR
        )

    embed = build_discord_embed(state.embeds[0])

    if len(state.embeds) > 1:
        embed.set_footer(
            text=f"Предпросмотр: {len(state.embeds)} embed'ов"
        )

    return embed


def render_button_preview(state):
    embed = render_build_preview(state)
    embed.title = "BUTTON BUILDER"

    button_lines = []
    for index, item in enumerate(state.buttons, start=1):
        button_lines.append(
            f"{index}. {item.get('emoji') or ''} "
            f"{item.get('label', 'Кнопка')} · "
            f"{item.get('action', 'action')}"
        )

    embed.description = (
        "\n".join(button_lines)
        if button_lines
        else "Кнопок пока нет."
    )

    return embed


async def finish_message_build(interaction, state):
    if interaction.guild is None:
        await interaction.response.send_message(
            "Эта функция работает только на сервере.",
            ephemeral=True
        )
        return

    build_id = save_message_build(
        guild_id=interaction.guild.id,
        owner_id=interaction.user.id,
        name=state.name,
        content=state.content,
        embeds_json=json.dumps(state.embeds, ensure_ascii=False),
        buttons_json=json.dumps(state.buttons, ensure_ascii=False),
        visibility=state.visibility,
        category=state.category,
    )

    await interaction.response.edit_message(
        content=None,
        embed=discord.Embed(
            title="MESSAGE BUILD СОХРАНЁН",
            description=(
                f"ID: `{build_id}`\n\n"
                f"Embed'ов: **{len(state.embeds)}**\n"
                f"Кнопок: **{len(state.buttons)}**\n"
                f"Видимость: **{state.visibility}**\n\n"
                "Само сохранение уже объединяет дизайн и кнопки."
            ),
            color=EMBED_COLOR
        ),
        view=MessageBuildActionsView(build_id)
    )


class MessageBuildActionsView(discord.ui.View):

    def __init__(self, build_id):
        super().__init__(timeout=900)
        self.build_id = build_id

    @discord.ui.button(
        label="Предпросмотр",
        emoji="👁️",
        style=discord.ButtonStyle.secondary
    )
    async def preview(self, interaction, button):
        row = get_message_build(self.build_id)

        if not row:
            await interaction.response.send_message(
                "Message Build не найден.",
                ephemeral=True
            )
            return

        content = row[4] or None
        embeds_data = safe_json_loads(row[5], [])
        buttons_data = safe_json_loads(row[6], [])

        embeds = [
            build_discord_embed(item)
            for item in embeds_data[:MAX_EMBEDS]
        ]

        await interaction.response.send_message(
            content=content,
            embeds=embeds,
            view=build_button_view(buttons_data),
            ephemeral=True
        )

    @discord.ui.button(
        label="Отправить",
        emoji="📤",
        style=discord.ButtonStyle.success
    )
    async def send(self, interaction, button):
        await interaction.response.send_message(
            "Отправку в выбранный канал подключим поверх Message Build "
            "следующим шагом.",
            ephemeral=True
        )

    @discord.ui.button(
        label="Удалить",
        emoji="🗑️",
        style=discord.ButtonStyle.danger
    )
    async def delete(self, interaction, button):
        if delete_message_build(
            self.build_id,
            interaction.user.id
        ):
            await interaction.response.edit_message(
                content=None,
                embed=discord.Embed(
                    title="MESSAGE BUILD УДАЛЁН",
                    color=EMBED_COLOR
                ),
                view=None
            )
        else:
            await interaction.response.send_message(
                "Удалить этот Message Build может только его создатель.",
                ephemeral=True
            )


@bot.tree.command(
    name="embed",
    description="Создать Message Build с embed'ами и кнопками"
)
async def embed_command(interaction):
    if not await require_command_access(interaction, "embed"):
        return

    state = EmbedBuilderState()

    await interaction.response.send_message(
        embed=discord.Embed(
            title="EMBED BUILDER",
            description=(
                "Сначала собираем дизайн.\n\n"
                "Можно создать до **10 отдельных embed'ов** "
                "в одном сообщении.\n"
                "Изображения задаются отдельными URL для thumbnail и image.\n\n"
                "После подтверждения дизайна кнопки настраиваются отдельно."
            ),
            color=EMBED_COLOR
        ),
        view=EmbedDesignView(state),
        ephemeral=True
    )


# ============================================================
# BUTTON BUILDER
# ============================================================

class StandaloneButtonStartView(discord.ui.View):

    def __init__(self, guild_id, owner_id):
        super().__init__(timeout=900)
        self.guild_id = guild_id
        self.owner_id = owner_id
        self.state = EmbedBuilderState()

    @discord.ui.button(
        label="Создать набор",
        emoji="➕",
        style=discord.ButtonStyle.success
    )
    async def create(self, interaction, button):
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="BUTTON BUILDER",
                description="Можно добавить до 5 кнопок.",
                color=EMBED_COLOR
            ),
            view=InlineButtonBuilderView(self.state)
        )

    @discord.ui.button(
        label="Сохранённые наборы",
        emoji="📦",
        style=discord.ButtonStyle.secondary
    )
    async def saved(self, interaction, button):
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="BUTTON SETS",
                description="Выберите сохранённый набор.",
                color=EMBED_COLOR
            ),
            view=ButtonSetListView(
                self.guild_id,
                self.owner_id
            )
        )


class ButtonSetListView(discord.ui.View):

    def __init__(self, guild_id, owner_id):
        super().__init__(timeout=900)
        self.guild_id = guild_id
        self.owner_id = owner_id

        rows = get_button_sets(
            guild_id,
            owner_id,
            include_public=True
        )

        for set_id, creator_id, name, visibility, category, updated_at in rows[:25]:
            button = discord.ui.Button(
                label=f"{name[:70]}",
                style=discord.ButtonStyle.secondary
            )

            async def callback(
                interaction,
                set_id=set_id
            ):
                row = get_button_set(set_id)
                if not row:
                    await interaction.response.send_message(
                        "Набор не найден.",
                        ephemeral=True
                    )
                    return

                buttons = safe_json_loads(row[4], [])

                await interaction.response.send_message(
                    embed=discord.Embed(
                        title=row[2],
                        description=(
                            f"Категория: `{row[6]}`\n"
                            f"Видимость: `{row[5]}`\n"
                            f"Кнопок: `{len(buttons)}`"
                        ),
                        color=EMBED_COLOR
                    ),
                    view=build_button_view(buttons),
                    ephemeral=True
                )

            button.callback = callback
            self.add_item(button)

        if not rows:
            self.add_item(
                discord.ui.Button(
                    label="Сохранённых наборов нет",
                    disabled=True
                )
            )


@bot.tree.command(
    name="buttons",
    description="Создать и управлять наборами кнопок"
)
async def buttons_command(interaction):
    if not await require_command_access(interaction, "buttons"):
        return

    await interaction.response.send_message(
        embed=discord.Embed(
            title="BUTTON BUILDER",
            description=(
                "Отдельный конструктор кнопок.\n\n"
                "Максимум **5 кнопок** в одном наборе.\n"
                "Набор можно будет подключать к Message Build."
            ),
            color=EMBED_COLOR
        ),
        view=StandaloneButtonStartView(
            interaction.guild.id,
            interaction.user.id
        ),
        ephemeral=True
    )


class RoleAccessView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=900)
        select = discord.ui.RoleSelect(placeholder="Выберите роль", min_values=1, max_values=1)
        select.callback = self.selected
        self.add_item(select)

    async def selected(self, interaction):
        role = self.children[0].values[0]
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="ДОСТУП РОЛИ",
                description=f"{role.mention}\n\nВыберите уровень доступа для обладателей этой роли.",
                color=EMBED_COLOR
            ),
            view=RoleLevelAccessView(role.id, role.mention)
        )


class RoleLevelAccessView(discord.ui.View):
    def __init__(self, role_id, mention):
        super().__init__(timeout=900)
        self.role_id = role_id
        self.mention = mention

    async def apply(self, interaction, level):
        if not can_manage_access(interaction):
            await interaction.response.send_message("Недостаточно прав.", ephemeral=True)
            return
        set_role_access(interaction.guild.id, self.role_id, level, None)
        await interaction.response.send_message(
            f"{self.mention} → {ACCESS_LABELS[level]}", ephemeral=True
        )

    @discord.ui.button(label="Ограниченный", style=discord.ButtonStyle.secondary)
    async def limited(self, i, b): await self.apply(i, "limited")
    @discord.ui.button(label="Пользователь", style=discord.ButtonStyle.secondary)
    async def member(self, i, b): await self.apply(i, "member")
    @discord.ui.button(label="Staff", style=discord.ButtonStyle.primary)
    async def staff(self, i, b): await self.apply(i, "staff")
    @discord.ui.button(label="Администратор", style=discord.ButtonStyle.success)
    async def admin(self, i, b): await self.apply(i, "admin")
    @discord.ui.button(label="Убрать", emoji="🗑️", style=discord.ButtonStyle.danger)
    async def remove(self, i, b):
        if not can_manage_access(i):
            await i.response.send_message("Недостаточно прав.", ephemeral=True); return
        remove_role_access(i.guild.id, self.role_id)
        await i.response.send_message(f"Привязка {self.mention} удалена.", ephemeral=True)


class DenialAccessView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=900)
        select = discord.ui.UserSelect(placeholder="Выберите пользователя", min_values=1, max_values=1)
        select.callback = self.selected
        self.add_item(select)

    async def selected(self, interaction):
        user = self.children[0].values[0]
        reason = is_user_denied(interaction.guild.id, user.id)
        if reason is None:
            deny_user(interaction.guild.id, user.id, "Access Manager")
            result = "запрещён"
        else:
            undeny_user(interaction.guild.id, user.id)
            result = "запрет снят"
        await interaction.response.send_message(f"{user.mention}: {result}.", ephemeral=True)


register_extended(bot, require_command_access)


# =========================
# START
# =========================

if not TOKEN:
    raise RuntimeError(
        "Токен не найден. Проверь файл .env"
    )

bot.run(TOKEN)
