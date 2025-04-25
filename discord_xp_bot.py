import discord
from discord.ext import commands, tasks
import json
import os
from webserver import keep_alive
from datetime import time, timedelta

# Load XP data
try:
    with open('xp_data.json', 'r') as f:
        xp_data = json.load(f)
except FileNotFoundError:
    xp_data = {}

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents)

# XP Role thresholds
xp_roles = {
    100: "🏑 Rookie",
    500: "🥉 Member",
    1000: "🏅 Local Leader",
    2000: "🏇 Core Leader",
    3500: "🏆 Mentor"
}

# Save XP data to file
def save_xp():
    with open('xp_data.json', 'w') as f:
        json.dump(xp_data, f)

@bot.event
async def on_ready():
    print(f'Bot connected as {bot.user}')
    if not daily_leaderboard.is_running():
        daily_leaderboard.start()

@bot.event
async def on_member_join(member):
    announcement_channel = discord.utils.get(member.guild.text_channels, name="📢│announcement")
    if announcement_channel:
        embed = discord.Embed(
            title="🎉 Welcome to the Server! 🎉",
            description=f"Welcome `{member.display_name}` to our amazing community! ✨\n\nBe active, earn XP, and level up your skills! 🚀",
            color=discord.Color.green()
        )
        embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)
        embed.set_footer(text="We're happy you're here! ❤️")
        await announcement_channel.send(embed=embed)

# Helper: Assign highest eligible role and remove lower ones
async def assign_role_by_xp(member, xp):
    roles_to_assign = [role_name for required_xp, role_name in xp_roles.items() if xp >= required_xp]
    if roles_to_assign:
        target_role_name = roles_to_assign[-1]
        target_role = discord.utils.get(member.guild.roles, name=target_role_name)

        if target_role and target_role not in member.roles:
            lower_roles = [discord.utils.get(member.guild.roles, name=name)
                           for name in xp_roles.values()
                           if name != target_role_name and discord.utils.get(member.guild.roles, name=name) in member.roles]
            if lower_roles:
                await member.remove_roles(*lower_roles)
            await member.add_roles(target_role)

            announcement_channel = discord.utils.get(member.guild.text_channels, name="📢│announcement")
            if announcement_channel:
                await announcement_channel.send(
                    f"🎉 `{member.display_name}` just leveled up to **{target_role_name}**!")

# Helper: Find member by display name (case-insensitive)
def find_member_by_display_name(guild, name):
    name = name.lower()
    for member in guild.members:
        if member.display_name.lower() == name:
            return member
    return None



@bot.command()
@commands.has_role("XP Manager")
async def givexp(ctx, member: discord.Member, amount: int, *, reason: str = None):
    allowed_channel = "🔒│admin-xp-give"
    if ctx.channel.name != allowed_channel:
        return

    user_id = str(member.id)
    xp_data[user_id] = xp_data.get(user_id, 0) + amount
    save_xp()

    # Send confirmation to current channel
    await ctx.send(f"✅ {member.mention} received {amount} XP! {'📝 ' + reason if reason else ''}")

    # 💬 Send XP notice to 📢│announcement
    announcement_channel = discord.utils.get(ctx.guild.text_channels, name="📢│announcement")
    if announcement_channel:
        await announcement_channel.send(
            f"✨ {member.mention} just gained **{amount} XP**! {'📝 ' + reason if reason else ''}"
        )

    # 🎖 Try to assign new role and announce level up if needed
    await assign_role_by_xp(member, xp_data[user_id])


@bot.command()
async def removexp(ctx, *, args: str):
    if ctx.channel.name != "🔒│admin-xp-give":
        return

    if "XP Manager" not in [role.name for role in ctx.author.roles]:
        await ctx.send("❌ You need the 'XP Manager' role to use this command.")
        return

    try:
        parts = args.rsplit(' ', 1)
        display_name = parts[0].strip()
        amount = int(parts[1].strip())
    except (ValueError, IndexError):
        await ctx.send("❌ Invalid command format. Use `!removexp DisplayName XP`.")
        return

    await ctx.guild.chunk()
    member = find_member_by_display_name(ctx.guild, display_name)

    if not member:
        await ctx.send(f"❌ Could not find a member with display name '{display_name}'.")
        return

    user_id = str(member.id)
    xp_data[user_id] = max(xp_data.get(user_id, 0) - amount, 0)
    save_xp()

    print(f"[DEBUG] Removed {amount} XP from {member.display_name} ({member.id})")
    await assign_role_by_xp(member, xp_data[user_id])
    print(f"[DEBUG] Reassigned role if necessary.")

    await ctx.send(f"✅ `{member.display_name}` lost **{amount} XP**.")

@bot.command()
async def xp(ctx, member: discord.Member = None):
    allowed_channel = "📈│xp-levels"
    if ctx.channel.name != allowed_channel:
        return

    if not member:
        member = ctx.author

    user_id = str(member.id)
    xp = xp_data.get(user_id, 0)
    await ctx.send(f"🎯 {member.display_name} has {xp} XP!")

@bot.command()
async def leaderboard(ctx):
    allowed_channel_name = "🏆||leaderboard"
    if ctx.channel.name != allowed_channel_name:
        return

    if not xp_data:
        await ctx.send("No XP data available yet!")
        return

    await ctx.guild.chunk()
    sorted_xp = sorted(xp_data.items(), key=lambda x: x[1], reverse=True)
    message = "🏆 **Top 10 XP Players:**\n"
    for idx, (user_id, xp) in enumerate(sorted_xp[:10], start=1):
        member = ctx.guild.get_member(int(user_id))
        if member:
            message += f"{idx}. {member.display_name} — {xp} XP\n"
    await ctx.send(message)

@tasks.loop(time=time(hour=8, minute=0))
async def daily_leaderboard():
    for guild in bot.guilds:
        leaderboard_channel = discord.utils.get(guild.text_channels, name="🏆||leaderboard")
        if leaderboard_channel:
            sorted_xp = sorted(xp_data.items(), key=lambda x: x[1], reverse=True)
            embed = discord.Embed(
                title="🏆 Daily XP Leaderboard",
                description="Top 10 XP holders",
                color=discord.Color.gold()
            )
            for idx, (user_id, xp) in enumerate(sorted_xp[:10], start=1):
                member = guild.get_member(int(user_id))
                if member:
                    embed.add_field(
                        name=f"{idx}. {member.display_name}",
                        value=f"XP: {xp}",
                        inline=False
                    )
            icon = bot.user.avatar.url if bot.user.avatar else None
            embed.set_footer(text="Updated daily at 8AM", icon_url=icon)
            await leaderboard_channel.send(embed=embed)

keep_alive()
bot.run(os.environ['DISCORD_TOKEN'])
