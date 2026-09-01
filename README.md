# 🤖 Discord Welcome Bot

A friendly, configurable Discord bot that **welcomes new members** (and says goodbye
when they leave). Everything can be configured live in Discord — no code edits needed.

![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB) ![discord.py](https://img.shields.io/badge/discord.py-2.x-5865F2)

---

## ✨ Features

| Feature | Description |
|---|---|
| 👋 **Welcome embeds** | Colorful welcome card with avatar, mention, member counter & bottom banner |
| 🪪 **Custom icon** | Choose your own profile photo (icon) — or use each member's avatar |
| 💔 **Goodbye messages** | Posts a farewell when someone leaves |
| 🎭 **Auto-role** | Assigns a role to every new member automatically |
| 📨 **Welcome DMs** | Privately DMs each new member (skips users with DMs closed) |
| 📢 **Smart channel** | Posts to your chosen channel, or falls back to the system channel |
| ⚙️ **All slash commands** | Configure everything in Discord — no editing code |
| 🗃️ **Persistent settings** | Per-server config saved to `settings.json` |

---

## 🚀 Setup — 5 minutes

### Step 1: Create the bot application

1. Go to **[discord.com/developers/applications](https://discord.com/developers/applications)** → **New Application** → give it a name.
2. Left menu → **Bot** → **Reset Token** → copy the token. *(This is `DISCORD_TOKEN`.)*
3. Under **Privileged Gateway Intents**, toggle **ON** → **SERVER MEMBERS INTENT**.
   > ⚠️ **This step is critical.** Without the Members intent, the bot will not see
   > people joining/leaving, and nothing will be posted.
4. *(Optional)* Under **Bot → Authorization Flow**, uncheck "Public Bot" so only you can invite it.

### Step 2: Invite the bot to your server

Use this invite link (replace `YOUR_CLIENT_ID` with the ID from **OAuth2 → General**):

```
https://discord.com/api/oauth2/authorize?client_id=YOUR_CLIENT_ID&permissions=268520448&scope=bot%20applications.commands
```

Or build your own at **OAuth2 → URL Generator**:
- **Scopes:** `bot` + `applications.commands`
- **Bot permissions:** View Channels, Send Messages, Embed Links, Read Message History, **Manage Roles** (needed for auto-role)

### Step 3: Configure environment variables

```bash
cd discord-welcome-bot
cp .env.example .env        # (a ready .env is already included)
```

Open `.env` and fill in at least `DISCORD_TOKEN`:

| Variable | Required | What it does |
|---|---|---|
| `DISCORD_TOKEN` | ✅ Yes | Your bot token from the Developer Portal |
| `WELCOME_CHANNEL_ID` | No | Channel ID where welcomes are posted (else system channel) |
| `AUTO_ROLE_ID` | No | Role ID auto-assigned to new members |
| `SYNC_GUILD_ID` | No | Your server ID → slash commands appear instantly |
| `WELCOME_COLOR` | No | Welcome embed color, hex (default `#5865F2`) |
| `GOODBYE_COLOR` | No | Goodbye embed color, hex (default `#EB459E`) |
| `WELCOME_BANNER` | No | Banner image URL shown at the bottom of the welcome embed |
| `WELCOME_ICON` | No | Custom icon/profile photo URL (else each member's avatar) |
| `RULES_CHANNEL_ID` | No | Channel linked as "check out to keep The Community safe" |
| `ROLES_CHANNEL1_ID` | No | First channel linked for picking self & gaming roles |
| `ROLES_CHANNEL2_ID` | No | Second channel linked for picking self & gaming roles |

**How to get IDs:** User Settings → Advanced → **Developer Mode** ON → right-click a
channel / role / server → **Copy ID**.

### Step 4: Install & run

```bash
pip install -r requirements.txt
python bot.py
```

You should see `Logged in as ... connected to N guild(s)`. Keep it running
(use a VPS, Raspberry Pi, or a free host like Railway/Render/Replit for 24/7).

---

## ⚙️ Slash commands (in Discord)

All commands require **Manage Server** permission and reply privately:

| Command | What it does |
|---|---|
| `/welcome channel <#channel>` | Set where welcome/goodbye messages go |
| `/welcome channel clear:True` | Reset to the system channel |
| `/welcome role <@role>` | Set auto-assigned role for new members |
| `/welcome role clear:True` | Remove the auto-role |
| `/welcome message <text>` | Customize the welcome message |
| `/welcome goodbye <text>` | Customize the goodbye message |
| `/welcome dm <True/False>` | Turn the welcome DM on/off |
| `/welcome dm-message <text>` | Customize the DM text |
| `/welcome banner <url>` | Set the banner image shown at the bottom of the embed |
| `/welcome banner reset:True` | Restore the default banner |
| `/welcome icon <url>` | Set the icon/profile photo (else each member's avatar is used) |
| `/welcome icon clear:True` | Clear the custom icon, back to each member's avatar |
| `/welcome preview` | Preview the embed before anyone joins |
| `/welcome settings` | Show the full current config |

**Message placeholders** (use in `/welcome message` etc.):

| Placeholder | Replaced with |
|---|---|
| `{mention}` | @Mention of the new member |
| `{name}` | The member's display name |
| `{user}` | Full username (name + tag) |
| `{server}` | Your server's name |
| `{count}` | New member count of the server |
| `{avatar}` | The member's profile photo URL |
| `{rules}` | The "rules" channel mention |
| `{roles1}` | First role-picking channel mention |
| `{roles2}` | Second role-picking channel mention |

Example: `Welcome {mention}! You are member #{count} of {server} 🎉`

---

## 🔧 Troubleshooting

| Problem | Fix |
|---|---|
| Bot doesn't respond to join/leave | Enable **SERVER MEMBERS INTENT** in the Developer Portal and restart the bot |
| Slash commands don't appear | Set `SYNC_GUILD_ID` in `.env` and restart; global sync can take ~1 hour |
| Auto-role not assigned | The bot's role must be **above** the role you assign in Server Settings → Roles |
| No welcome posted | No channel set → bot uses the system channel; if none exists, run `/welcome channel` |
| Commands say "can't use" | You need **Manage Server** permission |
| Welcome DM not sent | The user has DMs closed (the bot skips silently — this is normal) |

---

## 📁 Project structure

```
discord-welcome-bot/
├── bot.py            # The bot itself (single file)
├── .env              # Your environment variables (secrets — never share!)
├── .env.example      # Template with all variables documented
├── requirements.txt  # Python dependencies
├── settings.json     # Created at runtime — per-server settings
└── .gitignore        # Keeps secrets out of git
```
