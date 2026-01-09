import discord
from discord.ext import commands
import re
import time
import asyncio
from collections import defaultdict
import yt_dlp

# ================= CONFIG =================

TOKEN = "MTQ1OTEzNjEwODY4NzI2NTgyMg.G02FDV.6MpFsnRFY4z0yzvV0HRrHMGxYx9TyyDXKCjmzo"
PREFIX = "!"

SPAM_TIME_WINDOW = 5
SPAM_MAX_MESSAGES = 5

TICKET_CATEGORY_NAME = "TICKETS"
SUPPORT_ROLE_NAME = "Support"

# =========================================

intents = discord.Intents.all()
bot = commands.Bot(command_prefix=PREFIX, intents=intents)

user_message_times = defaultdict(list)
URL_REGEX = re.compile(r"(https?://|discord\.gg)", re.IGNORECASE)

# ================= EVENTS =================

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    try:
        await bot.tree.sync()
        print("✅ Slash commands synced")
    except Exception as e:
        print(e)

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # ANTI LINK
    if URL_REGEX.search(message.content):
        await message.delete()
        await message.channel.send(
            f"{message.author.mention} ❌ Links are not allowed.",
            delete_after=5
        )

    # ANTI SPAM
    now = time.time()
    times = user_message_times[message.author.id]
    times.append(now)
    user_message_times[message.author.id] = [
        t for t in times if now - t <= SPAM_TIME_WINDOW
    ]

    if len(user_message_times[message.author.id]) > SPAM_MAX_MESSAGES:
        mute_role = discord.utils.get(message.guild.roles, name="Muted")
        if mute_role:
            await message.author.add_roles(mute_role)
        await message.channel.send(
            f"{message.author.mention} 🔇 muted for spamming.",
            delete_after=5
        )
        await message.delete()

    await bot.process_commands(message)

# ================= ANNOUNCEMENT =================

@bot.command()
@commands.has_permissions(manage_messages=True)
async def announce(ctx, channel: discord.TextChannel, *, msg):
    embed = discord.Embed(
        title="📢 Announcement",
        description=msg,
        color=discord.Color.gold()
    )
    embed.set_footer(text=f"By {ctx.author}")
    await channel.send(embed=embed)
    await ctx.reply("✅ Announcement sent")

# ================= ROLE SYSTEM =================

@bot.command()
@commands.has_permissions(manage_roles=True)
async def giverole(ctx, member: discord.Member, role: discord.Role):
    await member.add_roles(role)
    await ctx.reply(f"✅ {role.name} given to {member.mention}")

@bot.command()
@commands.has_permissions(manage_roles=True)
async def removerole(ctx, member: discord.Member, role: discord.Role):
    await member.remove_roles(role)
    await ctx.reply(f"✅ {role.name} removed from {member.mention}")

# ================= TICKET SYSTEM =================

@bot.command()
async def ticket(ctx):
    guild = ctx.guild

    category = discord.utils.get(guild.categories, name=TICKET_CATEGORY_NAME)
    if category is None:
        category = await guild.create_category(TICKET_CATEGORY_NAME)

    channel_name = f"ticket-{ctx.author.name}".lower()

    for ch in category.text_channels:
        if ch.name == channel_name:
            await ctx.reply("❌ You already have an open ticket.")
            return

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        ctx.author: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        guild.me: discord.PermissionOverwrite(read_messages=True)
    }

    support_role = discord.utils.get(guild.roles, name=SUPPORT_ROLE_NAME)
    if support_role:
        overwrites[support_role] = discord.PermissionOverwrite(
            read_messages=True,
            send_messages=True
        )

    channel = await guild.create_text_channel(
        channel_name,
        category=category,
        overwrites=overwrites
    )

    await channel.send(
        f"🎫 **Ticket Opened**\n"
        f"{ctx.author.mention}, explain your issue.\n"
        f"Staff will help you soon.\n\n"
        f"Type `!close` to close this ticket."
    )

    await ctx.reply(f"✅ Ticket created: {channel.mention}")

@bot.command()
@commands.has_permissions(manage_channels=True)
async def close(ctx):
    if ctx.channel.category and ctx.channel.category.name == TICKET_CATEGORY_NAME:
        await ctx.send("🔒 Closing ticket...")
        await asyncio.sleep(2)
        await ctx.channel.delete()
    else:
        await ctx.reply("❌ This is not a ticket channel.")

# ================= MUSIC SYSTEM =================

ytdl_opts = {
    "format": "bestaudio/best",
    "quiet": True,
    "default_search": "ytsearch",
    "noplaylist": True
}
ffmpeg_opts = {"options": "-vn"}
ytdl = yt_dlp.YoutubeDL(ytdl_opts)

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data):
        super().__init__(source)
        self.title = data.get("title")

    @classmethod
    async def from_query(cls, query):
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(
            None, lambda: ytdl.extract_info(query, download=False)
        )
        if "entries" in data:
            data = data["entries"][0]
        return cls(discord.FFmpegPCMAudio(data["url"], **ffmpeg_opts), data=data)

queues = {}

async def ensure_voice(ctx):
    if not ctx.author.voice:
        await ctx.reply("❌ Join a voice channel first")
        return None
    vc = ctx.guild.voice_client
    if not vc:
        vc = await ctx.author.voice.channel.connect()
    return vc

async def play_next(guild_id):
    vc = bot.get_guild(guild_id).voice_client
    if not vc or not queues[guild_id]:
        return
    query = queues[guild_id].pop(0)
    source = await YTDLSource.from_query(query)
    vc.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(
        play_next(guild_id), bot.loop))

@bot.command()
async def play(ctx, *, query):
    vc = await ensure_voice(ctx)
    if not vc:
        return
    gid = ctx.guild.id
    queues.setdefault(gid, []).append(query)
    if not vc.is_playing():
        await play_next(gid)
    await ctx.reply("🎵 Added to queue")

@bot.command()
async def skip(ctx):
    vc = ctx.guild.voice_client
    if vc and vc.is_playing():
        vc.stop()
        await ctx.reply("⏭ Skipped")

@bot.command()
async def stop(ctx):
    vc = ctx.guild.voice_client
    if vc:
        queues[ctx.guild.id] = []
        await vc.disconnect()
        await ctx.reply("⏹ Stopped")

# ================= SLASH =================

@bot.tree.command(name="ping")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("🏓 Pong!", ephemeral=True)

# ================= RUN =================

bot.run(TOKEN)

