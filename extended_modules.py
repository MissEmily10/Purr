import io
import json
import urllib.request
import os
from datetime import datetime

import discord

from database import (
    save_form, get_form, get_forms, save_submission, get_submission,
    review_submission, save_template, get_template, get_templates,
    delete_template, save_webhook, get_webhook, get_webhooks,
    update_webhook_record, delete_webhook_record, log_webhook_event,
    get_webhook_history, log_audit, get_audit_logs,
)

COLOR = discord.Color.blurple()
MAX_QUESTIONS = 5
MAX_EMBEDS = 10
MAX_BUTTONS = 5


def E(title, description=""):
    return discord.Embed(title=title, description=description, color=COLOR)


def j(value, default):
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def url(value):
    value = (value or "").strip()
    if not value:
        return None
    return value if value.startswith(("http://", "https://")) else "https://" + value


def role_allowed(interaction, owner_id, visibility, role_ids):
    if interaction.user.id == owner_id:
        return True
    if visibility == "public":
        return True
    return any(r.id in set(role_ids) for r in getattr(interaction.user, "roles", []))


def build_embed(data):
    color = data.get("color", COLOR.value)
    try:
        color = int(color)
    except (TypeError, ValueError):
        color = COLOR.value
    e = discord.Embed(
        title=data.get("title") or discord.Embed.Empty,
        description=data.get("description") or discord.Embed.Empty,
        color=color,
    )
    if data.get("url"):
        e.url = url(data["url"])
    if data.get("thumbnail"):
        e.set_thumbnail(url=url(data["thumbnail"]))
    if data.get("image"):
        e.set_image(url=url(data["image"]))
    if data.get("author_name"):
        e.set_author(name=str(data["author_name"])[:256], url=url(data.get("author_url")), icon_url=url(data.get("author_icon")))
    if data.get("footer_text"):
        e.set_footer(text=str(data["footer_text"])[:2048], icon_url=url(data.get("footer_icon")))
    if data.get("timestamp"):
        e.timestamp = datetime.now()
    for field in data.get("fields", [])[:25]:
        e.add_field(name=str(field.get("name", "Field"))[:256], value=str(field.get("value", "\u200b"))[:1024], inline=bool(field.get("inline")))
    return e


def button_view(items):
    if not items:
        return None
    view = discord.ui.View(timeout=None)
    styles = {
        "primary": discord.ButtonStyle.primary,
        "secondary": discord.ButtonStyle.secondary,
        "success": discord.ButtonStyle.success,
        "danger": discord.ButtonStyle.danger,
    }
    for item in items[:MAX_BUTTONS]:
        action = item.get("action", "message")
        label = str(item.get("label", "Кнопка"))[:80]
        emoji = item.get("emoji") or None
        if action == "link":
            target = url(item.get("value"))
            if not target:
                continue
            b = discord.ui.Button(label=label, emoji=emoji, style=discord.ButtonStyle.link, url=target)
        else:
            b = discord.ui.Button(label=label, emoji=emoji, style=styles.get(item.get("style"), discord.ButtonStyle.primary))
            async def cb(interaction, action=action, value=item.get("value", "")):
                if action == "message":
                    await interaction.response.send_message(value or "РЕПЛИКА ОС — действие выполнено.", ephemeral=True)
                elif action == "confirm":
                    await interaction.response.send_message(value or "РЕПЛИКА ОС — подтверждение получено.", ephemeral=True)
                elif action == "ephemeral":
                    await interaction.response.send_message(value or "РЕПЛИКА ОС — это приватное сообщение.", ephemeral=True)
            b.callback = cb
        view.add_item(b)
    return view


# =========================
# FORMS
# =========================

class FormState:
    def __init__(self, guild_id, owner_id):
        self.guild_id = guild_id
        self.owner_id = owner_id
        self.name = "Новая форма"
        self.description = ""
        self.questions = []
        self.visibility = "public"
        self.category = "roles"
        self.allowed_roles = []
        self.destination = None
        self.reviewer_roles = []
        self.reviewer_users = []
        self.post_action = "review"
        self.post_role = None
        self.target_role = None


def form_text(s):
    qs = "\n".join(f"{i}. {q['label']} · {q['type']} · {'required' if q['required'] else 'optional'}" for i,q in enumerate(s.questions,1)) or "нет"
    return (f"**Название:** {s.name}\n**Категория:** {s.category}\n**Видимость:** {s.visibility}\n"
            f"**Канал заявок:** {s.destination or 'не задан'}\n"
            f"**Reviewers:** {len(s.reviewer_roles)} ролей / {len(s.reviewer_users)} пользователей\n"
            f"**После решения:** {s.post_action}\n**Роль после одобрения:** {s.post_role or 'не задана'}\n\n**Вопросы:**\n{qs}")


class FormBasicModal(discord.ui.Modal, title="ОСНОВНЫЕ ДАННЫЕ ФОРМЫ"):
    name = discord.ui.TextInput(label="Название", max_length=100)
    description = discord.ui.TextInput(label="Описание", style=discord.TextStyle.paragraph, required=False, max_length=1000)
    category = discord.ui.TextInput(label="Категория", max_length=50)
    visibility = discord.ui.TextInput(label="private/public", max_length=7)
    roles = discord.ui.TextInput(label="Разрешённые role ID через запятую", required=False, max_length=1000)
    def __init__(self, state):
        super().__init__(); self.state=state
        self.name.default=state.name; self.description.default=state.description; self.category.default=state.category; self.visibility.default=state.visibility; self.roles.default=",".join(map(str,state.allowed_roles))
    async def on_submit(self, interaction):
        v=self.visibility.value.strip().lower()
        if v not in {"private","public"}:
            await interaction.response.send_message("Видимость: private или public.",ephemeral=True); return
        self.state.name=self.name.value.strip(); self.state.description=self.description.value.strip(); self.state.category=self.category.value.strip() or "general"; self.state.visibility=v
        self.state.allowed_roles=[int(x.strip()) for x in self.roles.value.split(",") if x.strip().isdigit()]
        await interaction.response.edit_message(embed=E("FORM BUILDER",form_text(self.state)),view=FormView(self.state))


class FormQuestionModal(discord.ui.Modal, title="ВОПРОС ФОРМЫ"):
    label=discord.ui.TextInput(label="Вопрос",max_length=256)
    qtype=discord.ui.TextInput(label="short / long / yesno",max_length=10)
    required=discord.ui.TextInput(label="required? yes/no",max_length=3)
    def __init__(self,state): super().__init__(); self.state=state
    async def on_submit(self,interaction):
        t=self.qtype.value.strip().lower()
        if t not in {"short","long","yesno"}:
            await interaction.response.send_message("Тип: short, long или yesno.",ephemeral=True); return
        if len(self.state.questions)>=MAX_QUESTIONS:
            await interaction.response.send_message("Максимум 5 вопросов для одного Discord Modal.",ephemeral=True); return
        self.state.questions.append({"label":self.label.value.strip(),"type":t,"required":self.required.value.strip().lower() in {"yes","y","да","д"}})
        await interaction.response.edit_message(embed=E("FORM BUILDER",form_text(self.state)),view=FormView(self.state))


class FormRoutingModal(discord.ui.Modal, title="МАРШРУТИЗАЦИЯ ФОРМЫ"):
    destination=discord.ui.TextInput(label="ID канала заявок",max_length=30)
    reviewer_roles=discord.ui.TextInput(label="Reviewer role IDs через запятую",required=False,max_length=1000)
    reviewer_users=discord.ui.TextInput(label="Reviewer user IDs через запятую",required=False,max_length=1000)
    action=discord.ui.TextInput(label="review / role / none",max_length=10)
    role=discord.ui.TextInput(label="Role ID после одобрения",required=False,max_length=30)
    def __init__(self,state):
        super().__init__(); self.state=state
        self.destination.default=str(state.destination or ""); self.reviewer_roles.default=",".join(map(str,state.reviewer_roles)); self.reviewer_users.default=",".join(map(str,state.reviewer_users)); self.action.default=state.post_action; self.role.default=str(state.post_role or "")
    async def on_submit(self,interaction):
        action=self.action.value.strip().lower()
        if not self.destination.value.strip().isdigit() or action not in {"review","role","none"}:
            await interaction.response.send_message("Проверь ID канала и действие.",ephemeral=True); return
        self.state.destination=int(self.destination.value); self.state.reviewer_roles=[int(x.strip()) for x in self.reviewer_roles.value.split(",") if x.strip().isdigit()]; self.state.reviewer_users=[int(x.strip()) for x in self.reviewer_users.value.split(",") if x.strip().isdigit()]; self.state.post_action=action; self.state.post_role=int(self.role.value) if self.role.value.strip().isdigit() else None
        await interaction.response.edit_message(embed=E("FORM BUILDER",form_text(self.state)),view=FormView(self.state))


class FormTargetRoleView(discord.ui.View):
    def __init__(self,state):
        super().__init__(timeout=300); self.state=state
        s=discord.ui.RoleSelect(placeholder="Роль, на которую подаётся заявка",min_values=1,max_values=1); s.callback=self.selected; self.add_item(s)
    async def selected(self,interaction):
        self.state.target_role=self.children[0].values[0].id
        await interaction.response.edit_message(embed=E("FORM BUILDER",form_text(self.state)),view=FormView(self.state))


class FormView(discord.ui.View):
    def __init__(self,state): super().__init__(timeout=900); self.state=state
    @discord.ui.button(label="Основные",emoji="✏️",style=discord.ButtonStyle.primary)
    async def basic(self,i,b): await i.response.send_modal(FormBasicModal(self.state))
    @discord.ui.button(label="Вопрос",emoji="➕",style=discord.ButtonStyle.secondary)
    async def question(self,i,b): await i.response.send_modal(FormQuestionModal(self.state))
    @discord.ui.button(label="Маршрутизация",emoji="📨",style=discord.ButtonStyle.secondary)
    async def routing(self,i,b): await i.response.send_modal(FormRoutingModal(self.state))
    @discord.ui.button(label="Роль для заявки",emoji="🎭",style=discord.ButtonStyle.secondary)
    async def target(self,i,b): await i.response.edit_message(embed=E("TARGET ROLE", "Выберите роль, на которую человек подаёт заявку."),view=FormTargetRoleView(self.state))
    @discord.ui.button(label="Сохранить",emoji="💾",style=discord.ButtonStyle.success)
    async def save(self,i,b):
        if not self.state.questions or not self.state.destination:
            await i.response.send_message("Нужны хотя бы один вопрос и канал заявок.",ephemeral=True); return
        fid=save_form(self.state.guild_id,self.state.owner_id,self.state.name,self.state.description,json.dumps(self.state.questions,ensure_ascii=False),self.state.visibility,self.state.category,json.dumps(self.state.allowed_roles),self.state.destination,json.dumps(self.state.reviewer_roles),json.dumps(self.state.reviewer_users),self.state.post_action,self.state.post_role,self.state.target_role)
        await i.response.edit_message(embed=E("ФОРМА СОХРАНЕНА",f"ID: `{fid}`\nКанал заявок: <#{self.state.destination}>\nРоль: {('<@&'+str(self.state.target_role)+'>') if self.state.target_role else 'не задана'}"),view=FormUseView(fid))


class FormUseView(discord.ui.View):
    def __init__(self,form_id): super().__init__(timeout=900); self.form_id=form_id
    @discord.ui.button(label="Подать заявку",emoji="📝",style=discord.ButtonStyle.primary)
    async def apply(self,i,b):
        row=get_form(self.form_id)
        if row: await i.response.send_modal(SubmissionModal(row))
        else: await i.response.send_message("Форма не найдена.",ephemeral=True)


class SubmissionModal(discord.ui.Modal):
    def __init__(self,row):
        self.row=row; super().__init__(title=row[3][:45]); self.fields=[]
        for q in j(row[5],[])[:MAX_QUESTIONS]:
            f=discord.ui.TextInput(label=q['label'][:45],required=q.get('required',True),style=discord.TextStyle.paragraph if q.get('type')=='long' else discord.TextStyle.short,max_length=4000 if q.get('type')=='long' else 1000); self.fields.append(f); self.add_item(f)
    async def on_submit(self,i):
        qs=j(self.row[5],[]); answers={q['label']:f.value for q,f in zip(qs,self.fields)}; sid=save_submission(self.row[0],i.guild.id,i.user.id,json.dumps(answers,ensure_ascii=False)); channel=i.guild.get_channel(self.row[9])
        if channel:
            e=E("НОВАЯ ЗАЯВКА",f"Форма: **{self.row[3]}**\nЗаявитель: {i.user.mention}\nID: `{sid}`")
            for k,v in answers.items(): e.add_field(name=k[:256],value=str(v)[:1024] or "\u200b",inline=False)
            await channel.send(embed=e,view=ReviewView(sid))
        await i.response.send_message("РЕПЛИКА ОС — заявка отправлена приватно. Reviewers получат её в настроенном канале.",ephemeral=True)


class ReviewView(discord.ui.View):
    def __init__(self,sid): super().__init__(timeout=None); self.sid=sid
    def allowed(self,i,row,form):
        return i.user.id==form[2] or i.user.id in j(form[11],[]) or any(r.id in set(j(form[10],[])) for r in i.user.roles)
    @discord.ui.button(label="Одобрить",emoji="✅",style=discord.ButtonStyle.success)
    async def approve(self,i,b): await self.decide(i,"approved")
    @discord.ui.button(label="Отклонить",emoji="❌",style=discord.ButtonStyle.danger)
    async def reject(self,i,b): await self.decide(i,"rejected")
    async def decide(self,i,status):
        row=get_submission(self.sid); form=get_form(row[1]) if row else None
        if not row or not form: await i.response.send_message("Заявка не найдена.",ephemeral=True); return
        if not self.allowed(i,row,form): await i.response.send_message("У вас нет права рассматривать эту заявку.",ephemeral=True); return
        if row[5] != 'pending': await i.response.send_message(f"Уже обработано: {row[5]}.",ephemeral=True); return
        review_submission(self.sid,i.user.id,status)
        role_id=form[14] if len(form)>14 else form[13]
        if status=='approved' and form[12]=='role' and role_id:
            member=i.guild.get_member(row[3]); role=i.guild.get_role(role_id)
            if member and role:
                try: await member.add_roles(role,reason=f"Form #{self.sid} approved")
                except discord.Forbidden: pass
        await i.response.edit_message(embed=E("ЗАЯВКА ОБРАБОТАНА",f"Статус: **{status}**\nReviewer: {i.user.mention}"),view=None)


class FormStartView(discord.ui.View):
    def __init__(self,guild_id,user_id): super().__init__(timeout=900); self.guild_id=guild_id; self.user_id=user_id
    @discord.ui.button(label="Создать",emoji="➕",style=discord.ButtonStyle.success)
    async def create(self,i,b):
        state = FormState(self.guild_id, self.user_id)
        await i.response.edit_message(embed=E("FORM BUILDER",form_text(state)),view=FormView(state))
    @discord.ui.button(label="Сохранённые",emoji="📦",style=discord.ButtonStyle.secondary)
    async def saved(self,i,b): await i.response.edit_message(embed=E("FORMS","Выберите форму."),view=FormListView(i.guild.id,i.user.id))


class FormListView(discord.ui.View):
    def __init__(self,guild_id,user_id):
        super().__init__(timeout=900); rows=get_forms(guild_id,user_id,True)
        for fid,owner,name,visibility,category,roles,updated in rows[:20]:
            b=discord.ui.Button(label=name[:70],style=discord.ButtonStyle.secondary)
            async def cb(i,fid=fid):
                row=get_form(fid)
                if row and role_allowed(i,row[2],row[6],j(row[8],[])): await i.response.send_message(embed=E(row[3],row[4] or 'Без описания'),view=FormUseView(fid),ephemeral=True)
                else: await i.response.send_message('Форма недоступна.',ephemeral=True)
            b.callback=cb; self.add_item(b)
        if not rows:self.add_item(discord.ui.Button(label='Форм пока нет',disabled=True))


# =========================
# TEMPLATES
# =========================

class TemplateModal(discord.ui.Modal, title="СОХРАНИТЬ ШАБЛОН"):
    name=discord.ui.TextInput(label="Название",max_length=100); typ=discord.ui.TextInput(label="message / buttons / form",max_length=20); category=discord.ui.TextInput(label="Категория",max_length=50); visibility=discord.ui.TextInput(label="private / public",max_length=7); roles=discord.ui.TextInput(label="Role IDs через запятую",required=False,max_length=1000); payload=discord.ui.TextInput(label="JSON payload",style=discord.TextStyle.paragraph,max_length=4000)
    async def on_submit(self,i):
        typ=self.typ.value.strip().lower(); vis=self.visibility.value.strip().lower()
        if typ not in {'message','buttons','form'} or vis not in {'private','public'}:
            await i.response.send_message('Проверь тип и видимость.',ephemeral=True); return
        try: json.loads(self.payload.value)
        except json.JSONDecodeError: await i.response.send_message('JSON некорректен.',ephemeral=True); return
        roles=[int(x.strip()) for x in self.roles.value.split(',') if x.strip().isdigit()]
        tid=save_template(i.guild.id,i.user.id,self.name.value.strip(),typ,self.payload.value,vis,self.category.value.strip() or 'general',json.dumps(roles))
        await i.response.send_message(f'Шаблон сохранён: `{tid}`',ephemeral=True)


class TemplateListView(discord.ui.View):
    def __init__(self,guild_id,user_id):
        super().__init__(timeout=900); rows=get_templates(guild_id,user_id,include_public=True)
        for tid,owner,name,typ,payload,vis,cat,roles,updated in rows[:20]:
            b=discord.ui.Button(label=f'{name[:50]} · {typ}',style=discord.ButtonStyle.secondary)
            async def cb(i,tid=tid):
                row=get_template(tid)
                if not row or not role_allowed(i,row[2],row[6],j(row[8],[])): await i.response.send_message('Шаблон недоступен.',ephemeral=True); return
                await i.response.send_message(embed=E(row[3],f'Type: `{row[4]}`\nCategory: `{row[7]}`\nVisibility: `{row[6]}`'),view=TemplateActions(tid),ephemeral=True)
            b.callback=cb; self.add_item(b)
        if not rows:self.add_item(discord.ui.Button(label='Шаблонов нет',disabled=True))


class TemplateActions(discord.ui.View):
    def __init__(self,tid): super().__init__(timeout=900); self.tid=tid
    @discord.ui.button(label='Использовать',emoji='▶️',style=discord.ButtonStyle.success)
    async def use(self,i,b):
        row=get_template(self.tid); p=j(row[5],{}) if row else {}
        if not row: await i.response.send_message('Шаблон не найден.',ephemeral=True); return
        if row[4]=='message':
            await i.response.send_message(content=p.get('content') or None,embeds=[build_embed(x) for x in p.get('embeds',[])[:MAX_EMBEDS]],view=button_view(p.get('buttons',[])),ephemeral=True)
        elif row[4]=='buttons': await i.response.send_message(embed=E(row[3],'Набор кнопок.'),view=button_view(p.get('buttons',[])),ephemeral=True)
        else: await i.response.send_message('Для формы используй сохранённый Form ID в payload.',ephemeral=True)
    @discord.ui.button(label='Удалить',emoji='🗑️',style=discord.ButtonStyle.danger)
    async def delete(self,i,b):
        row=get_template(self.tid)
        if row and (row[2]==i.user.id or i.user.id==int(os.getenv('OWNER_ID','0'))):
            delete_template(self.tid,row[2]); await i.response.edit_message(embed=E('ШАБЛОН УДАЛЁН'),view=None)
        else: await i.response.send_message('Удалять может создатель или владелец.',ephemeral=True)


# =========================
# WEBHOOKS
# =========================

async def avatar_bytes(value):
    if not value:return None
    try:
        with urllib.request.urlopen(value,timeout=8) as r:return r.read()
    except Exception:return None


class WebhookCreateModal(discord.ui.Modal, title='СОЗДАТЬ WEBHOOK'):
    name=discord.ui.TextInput(label='Название',max_length=80); avatar=discord.ui.TextInput(label='Avatar URL',required=False,max_length=1000)
    async def on_submit(self,i): await i.response.send_message('Выберите канал.',view=WebhookChannelView(self.name.value.strip(),self.avatar.value.strip()),ephemeral=True)


class WebhookChannelView(discord.ui.View):
    def __init__(self,name,avatar):
        super().__init__(timeout=300); self.name=name; self.avatar=avatar; s=discord.ui.ChannelSelect(placeholder='Канал',channel_types=[discord.ChannelType.text]); s.callback=self.selected; self.add_item(s)
    async def selected(self,i):
        ch=self.children[0].values[0]
        try: wh=await ch.create_webhook(name=self.name,avatar=await avatar_bytes(self.avatar),reason='Webhook Manager')
        except discord.Forbidden: await i.response.send_message('Нужны права Manage Webhooks.',ephemeral=True); return
        except discord.HTTPException as e: await i.response.send_message(f'Ошибка Discord: `{e}`',ephemeral=True); return
        rid=save_webhook(i.guild.id,i.user.id,wh.id,ch.id,wh.name,wh.url,self.avatar or None); log_webhook_event(i.guild.id,i.user.id,wh.id,'created',ch.id); log_audit(i.guild.id,i.user.id,'webhook.created','webhook',wh.id)
        await i.response.edit_message(embed=E('WEBHOOK СОЗДАН',f'Канал: {ch.mention}\nИмя: **{wh.name}**\nID: `{wh.id}`\n\n🔒 URL скрыт.'),view=WebhookActions(rid))


class WebhookListView(discord.ui.View):
    def __init__(self,guild_id,user_id):
        super().__init__(timeout=900); rows=get_webhooks(guild_id,user_id)
        for rid,owner,wid,cid,name,avatar,created,updated in rows[:20]:
            b=discord.ui.Button(label=name[:70],style=discord.ButtonStyle.secondary)
            async def cb(i,rid=rid):
                row=get_webhook(rid)
                if row: await i.response.edit_message(embed=E('WEBHOOK',f'Имя: **{row[5]}**\nКанал: <#{row[4]}>\nID: `{row[3]}`\n\n🔒 URL скрыт.'),view=WebhookActions(rid))
                else: await i.response.send_message('Webhook не найден.',ephemeral=True)
            b.callback=cb; self.add_item(b)
        if not rows:self.add_item(discord.ui.Button(label='Webhook нет',disabled=True))


class WebhookActions(discord.ui.View):
    def __init__(self,rid): super().__init__(timeout=900); self.rid=rid
    def admin(self,i): return i.user.id==int(__import__('os').getenv('OWNER_ID','0')) or getattr(i.user,'guild_permissions',None) and i.user.guild_permissions.manage_webhooks
    @discord.ui.button(label='Показать URL',emoji='🔑',style=discord.ButtonStyle.secondary)
    async def show(self,i,b):
        row=get_webhook(self.rid)
        if not row or not self.admin(i): await i.response.send_message('Доступ запрещён.',ephemeral=True); return
        await i.response.send_message(f'🔑 `{row[6]}`\n\nНе публикуй этот URL.',ephemeral=True)
    @discord.ui.button(label='Отправить',emoji='📨',style=discord.ButtonStyle.primary)
    async def send(self,i,b): await i.response.send_modal(WebhookMessageModal(self.rid))
    @discord.ui.button(label='Переименовать',emoji='✏️',style=discord.ButtonStyle.secondary)
    async def rename(self,i,b): await i.response.send_modal(WebhookRenameModal(self.rid))
    @discord.ui.button(label='Аватар',emoji='🖼️',style=discord.ButtonStyle.secondary)
    async def avatar(self,i,b): await i.response.send_modal(WebhookAvatarModal(self.rid))
    @discord.ui.button(label='Тест',emoji='🧪',style=discord.ButtonStyle.success)
    async def test(self,i,b):
        row=get_webhook(self.rid)
        try:
            wh=await i.client.fetch_webhook(row[3]); await wh.send('Webhook Manager · тестовое сообщение.',wait=False); log_webhook_event(i.guild.id,i.user.id,row[3],'test',row[4]); await i.response.send_message('Тест отправлен.',ephemeral=True)
        except discord.HTTPException as e: await i.response.send_message(f'Ошибка: `{e}`',ephemeral=True)
    @discord.ui.button(label='История',emoji='📜',style=discord.ButtonStyle.secondary)
    async def history(self,i,b):
        row=get_webhook(self.rid); rows=get_webhook_history(i.guild.id,row[3] if row else None); text='\n'.join(f'`{a}` · {d or ""}' for _,_,a,_,d,_ in rows) or 'История пуста.'; await i.response.send_message(embed=E('WEBHOOK HISTORY',text),ephemeral=True)
    @discord.ui.button(label='Удалить',emoji='🗑️',style=discord.ButtonStyle.danger)
    async def delete(self,i,b):
        if not self.admin(i): await i.response.send_message('Недостаточно прав.',ephemeral=True); return
        await i.response.send_message('⚠️ Webhook будет удалён. Подтвердить?',view=WebhookDeleteView(self.rid),ephemeral=True)
    @discord.ui.button(label='Пересоздать URL',emoji='♻️',style=discord.ButtonStyle.danger)
    async def regenerate(self,i,b):
        if i.user.id!=int(__import__('os').getenv('OWNER_ID','0')): await i.response.send_message('Пересоздавать URL может только владелец.',ephemeral=True); return
        await i.response.send_message('⚠️ Старый URL перестанет работать. Подтвердить?',view=WebhookRegenerateView(self.rid),ephemeral=True)


class WebhookDeleteView(discord.ui.View):
    def __init__(self,rid): super().__init__(timeout=300); self.rid=rid
    @discord.ui.button(label='Удалить',emoji='🗑️',style=discord.ButtonStyle.danger)
    async def yes(self,i,b):
        row=get_webhook(self.rid)
        try: wh=await i.client.fetch_webhook(row[3]); await wh.delete(reason='Webhook Manager'); log_webhook_event(i.guild.id,i.user.id,row[3],'deleted',row[4]); delete_webhook_record(self.rid); await i.response.send_message('Webhook удалён. Старый URL больше не работает.',ephemeral=True)
        except discord.HTTPException as e: await i.response.send_message(f'Ошибка: `{e}`',ephemeral=True)
    @discord.ui.button(label='Отмена',style=discord.ButtonStyle.secondary)
    async def no(self,i,b): await i.response.send_message('Отменено.',ephemeral=True)


class WebhookRegenerateView(discord.ui.View):
    def __init__(self,rid): super().__init__(timeout=300); self.rid=rid
    @discord.ui.button(label='Да, пересоздать',emoji='♻️',style=discord.ButtonStyle.danger)
    async def yes(self,i,b):
        row=get_webhook(self.rid); old_id=row[3]; ch=i.guild.get_channel(row[4])
        try:
            old=await i.client.fetch_webhook(old_id); await old.delete(reason='Webhook URL regeneration'); new=await ch.create_webhook(name=row[5],reason='Webhook URL regeneration'); update_webhook_record(self.rid,name=new.name,channel_id=ch.id,url=new.url); log_webhook_event(i.guild.id,i.user.id,new.id,'regenerated',ch.id,f'old_webhook_id={old_id}'); await i.response.send_message('♻️ URL пересоздан. Старый URL больше не работает.',ephemeral=True)
        except (discord.HTTPException,discord.Forbidden) as e: await i.response.send_message(f'Ошибка: `{e}`',ephemeral=True)
    @discord.ui.button(label='Отмена',style=discord.ButtonStyle.secondary)
    async def no(self,i,b): await i.response.send_message('Отменено.',ephemeral=True)


class WebhookMessageModal(discord.ui.Modal,title='WEBHOOK MESSAGE'):
    text=discord.ui.TextInput(label='Текст',required=False,style=discord.TextStyle.paragraph,max_length=2000); title=discord.ui.TextInput(label='Embed title',required=False,max_length=256); description=discord.ui.TextInput(label='Embed description',required=False,style=discord.TextStyle.paragraph,max_length=4000); image=discord.ui.TextInput(label='Image URL',required=False,max_length=1000); thumbnail=discord.ui.TextInput(label='Thumbnail URL',required=False,max_length=1000)
    def __init__(self,rid): super().__init__(); self.rid=rid
    async def on_submit(self,i):
        row=get_webhook(self.rid); e=None
        if self.title.value.strip() or self.description.value.strip():
            e=discord.Embed(title=self.title.value.strip() or discord.Embed.Empty,description=self.description.value.strip() or discord.Embed.Empty,color=COLOR)
            if url(self.image.value): e.set_image(url=url(self.image.value))
            if url(self.thumbnail.value): e.set_thumbnail(url=url(self.thumbnail.value))
        try:
            wh=await i.client.fetch_webhook(row[3]); await wh.send(self.text.value or None,embed=e,wait=False); log_webhook_event(i.guild.id,i.user.id,row[3],'send',row[4],'message+embed' if e else 'message'); await i.response.send_message('Отправлено через webhook.',ephemeral=True)
        except discord.HTTPException as ex: await i.response.send_message(f'Ошибка: `{ex}`',ephemeral=True)


class WebhookRenameModal(discord.ui.Modal,title='ПЕРЕИМЕНОВАТЬ WEBHOOK'):
    name=discord.ui.TextInput(label='Новое имя',max_length=80)
    def __init__(self,rid): super().__init__(); self.rid=rid
    async def on_submit(self,i):
        row=get_webhook(self.rid)
        try: wh=await i.client.fetch_webhook(row[3]); await wh.edit(name=self.name.value.strip()); update_webhook_record(self.rid,name=self.name.value.strip()); log_webhook_event(i.guild.id,i.user.id,row[3],'rename',row[4],self.name.value.strip()); await i.response.send_message('Имя изменено.',ephemeral=True)
        except discord.HTTPException as e: await i.response.send_message(f'Ошибка: `{e}`',ephemeral=True)


class WebhookAvatarModal(discord.ui.Modal,title='ИЗМЕНИТЬ АВАТАР'):
    avatar=discord.ui.TextInput(label='Прямая URL-ссылка',max_length=1000)
    def __init__(self,rid): super().__init__(); self.rid=rid
    async def on_submit(self,i):
        row=get_webhook(self.rid); data=await avatar_bytes(self.avatar.value.strip())
        if not data: await i.response.send_message('Не удалось получить изображение.',ephemeral=True); return
        try: wh=await i.client.fetch_webhook(row[3]); await wh.edit(avatar=data); update_webhook_record(self.rid,avatar_url=self.avatar.value.strip()); log_webhook_event(i.guild.id,i.user.id,row[3],'avatar',row[4]); await i.response.send_message('Аватар изменён.',ephemeral=True)
        except discord.HTTPException as e: await i.response.send_message(f'Ошибка: `{e}`',ephemeral=True)


class WebhookHome(discord.ui.View):
    @discord.ui.button(label='Создать',emoji='➕',style=discord.ButtonStyle.success)
    async def create(self,i,b): await i.response.send_modal(WebhookCreateModal())
    @discord.ui.button(label='Список',emoji='📚',style=discord.ButtonStyle.secondary)
    async def list(self,i,b): await i.response.edit_message(embed=E('WEBHOOKS','Сохранённые webhook. URL скрыты.'),view=WebhookListView(i.guild.id,i.user.id))
    @discord.ui.button(label='История',emoji='📜',style=discord.ButtonStyle.secondary)
    async def history(self,i,b):
        rows=get_webhook_history(i.guild.id); text='\n'.join(f'<@{o}> · `{a}` · webhook `{w}`' for o,w,a,_,_,_ in rows) or 'История пуста.'; await i.response.edit_message(embed=E('WEBHOOK HISTORY',text),view=WebhookBack())


class WebhookBack(discord.ui.View):
    @discord.ui.button(label='Назад',emoji='↩️',style=discord.ButtonStyle.secondary)
    async def back(self,i,b): await i.response.edit_message(embed=E('WEBHOOK MANAGER','Создание · список · отправка · тест · история · удаление · URL regeneration.'),view=WebhookHome())


# =========================
# REGISTRATION
# =========================

def register_extended(bot, require_access):
    @bot.tree.command(name='forms',description='Создание и управление формами')
    async def forms(i):
        if not await require_access(i,'forms'): return
        await i.response.send_message(embed=E('FORM BUILDER','Создание форм, приватных заявок, reviewers и действий после решения.'),view=FormStartView(i.guild.id,i.user.id),ephemeral=True)

    @bot.tree.command(name='select',description='Создание и проверка Select Menu')
    async def select(i):
        if not await require_access(i,'select'): return
        await i.response.send_message(embed=E('SELECT MENU','Роли, каналы и пользователи. Выбор роли можно связать с Forms.'),view=SelectHome(),ephemeral=True)

    @bot.tree.command(name='templates',description='Библиотека публичных и приватных шаблонов')
    async def templates(i):
        if not await require_access(i,'templates'): return
        await i.response.send_message(embed=E('TEMPLATE MANAGER','Публичные / приватные шаблоны. Владелец видит все; доступ можно ограничить ролями.'),view=TemplateHome(),ephemeral=True)

    @bot.tree.command(name='messages',description='Управление сохранёнными Message Build')
    async def messages(i):
        if not await require_access(i,'messages'): return
        await i.response.send_message(embed=E('MESSAGE MANAGER','Предпросмотр, отправка и удаление сохранённых Message Build.'),view=MessageList(i.guild.id,i.user.id),ephemeral=True)

    @bot.tree.command(name='webhooks',description='Полноценное управление вебхуками')
    async def webhooks(i):
        if not await require_access(i,'webhooks'): return
        await i.response.send_message(embed=E('WEBHOOK MANAGER','Создать · удалить · переименовать · аватар · отправка · тест · история · безопасный URL.'),view=WebhookHome(),ephemeral=True)


class SelectHome(discord.ui.View):
    @discord.ui.button(label='Выбор роли',emoji='🎭',style=discord.ButtonStyle.primary)
    async def role(self,i,b):
        s=discord.ui.RoleSelect(placeholder='Выберите роль',min_values=1,max_values=1); s.callback=lambda x: x.response.send_message(f'Выбрано: {s.values[0].mention}',ephemeral=True); self.clear_items(); self.add_item(s); await i.response.edit_message(embed=E('ROLE SELECT','Выберите роль в списке.'),view=self)
    @discord.ui.button(label='Выбор канала',emoji='📁',style=discord.ButtonStyle.secondary)
    async def channel(self,i,b): await i.response.send_message('Выбор каналов используется в Message/Webhook/Forms панелях.',ephemeral=True)
    @discord.ui.button(label='Выбор пользователя',emoji='👤',style=discord.ButtonStyle.secondary)
    async def user(self,i,b): await i.response.send_message('Выбор пользователей используется в Access Manager и Forms.',ephemeral=True)


class TemplateHome(discord.ui.View):
    @discord.ui.button(label='Список',emoji='📚',style=discord.ButtonStyle.primary)
    async def list(self,i,b): await i.response.edit_message(embed=E('ШАБЛОНЫ','Доступные вам шаблоны.'),view=TemplateListView(i.guild.id,i.user.id))
    @discord.ui.button(label='Сохранить JSON',emoji='💾',style=discord.ButtonStyle.secondary)
    async def save(self,i,b): await i.response.send_modal(TemplateModal())


class MessageList(discord.ui.View):
    def __init__(self,guild_id,user_id):
        super().__init__(timeout=900)
        from database import get_message_builds
        rows=get_message_builds(guild_id,user_id,True)
        for bid,owner,name,vis,cat,roles,updated in rows[:20]:
            b=discord.ui.Button(label=name[:70],style=discord.ButtonStyle.secondary)
            async def cb(i,bid=bid):
                from database import get_message_build
                row=get_message_build(bid)
                if not row: await i.response.send_message('Build не найден.',ephemeral=True); return
                await i.response.send_message(content=row[4] or None,embeds=[build_embed(x) for x in j(row[5],[])[:MAX_EMBEDS]],view=button_view(j(row[6],[])),ephemeral=True)
            b.callback=cb; self.add_item(b)
        if not rows:self.add_item(discord.ui.Button(label='Build пока нет',disabled=True))
