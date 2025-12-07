from discord import app_commands
from dotenv import load_dotenv
import os
import discord
from discord import ui
import yt_dlp
from openpyxl.styles.numbers import NumberFormat

load_dotenv()
try:
    OPUS_PATH = os.getenv("OPUS_PATH")

    print(f"Versuche Opus von folgendem Pfad zu laden: {OPUS_PATH}")
    discord.opus.load_opus(OPUS_PATH)
    print(">>> Opus-Bibliothek erfolgreich geladen!")
except Exception as e:
    print(f">>> FEHLER beim manuellen Laden von Opus: {repr(e)}")
    exit(-1)

class MyClient(discord.Client):
    def __init__(self, *, intents: discord.Intents):
        super().__init__(intents=intents)
        self.tree = discord.app_commands.CommandTree(self)

    async def on_ready(self):
        await self.tree.sync()
        print(f'Eingeloggt als {self.user} und Befehle synchronisiert!')


class MusicControlsView(ui.View):
    def __init__(self, *, timeout=180):
        super().__init__(timeout=timeout)
    @ui.button(label="Prev", style=discord.ButtonStyle.secondary, emoji="⏪")
    async def prev_button(self, interaction: discord.Interaction, button: ui.Button):
        voice_client = interaction.guild.voice_client
        if voice_client or not voice_client.is_playing():
            await skip_to_prev(interaction)
        else:
            await interaction.response.send_message("Es wird gerade nichts abgespielt.", ephemeral=True)

    @ui.button(label="Pause", style=discord.ButtonStyle.secondary, emoji="⏸️")
    async def pause_button(self, interaction: discord.Interaction, button: ui.Button):
        voice_client = interaction.guild.voice_client
        if voice_client and voice_client.is_connected():
            if voice_client.is_paused():
                button.label = "Pause"
                button.emoji = "⏸️"
                voice_client.resume()
                await interaction.response.edit_message(view=self)
            else:
                button.label = "Fortsetzen"
                button.emoji = "▶️"
                voice_client.pause()
                await interaction.response.edit_message(view=self)
        else:
            await interaction.response.send_message("Ich bin in keinem Sprachkanal.", ephemeral=True)

    @ui.button(label="Skip", style=discord.ButtonStyle.secondary, emoji="⏩")
    async def skip_button(self, interaction: discord.Interaction, button: ui.Button):
        voice_client = interaction.guild.voice_client
        if voice_client or not voice_client.is_playing():
            await skip_to_next(
                interaction)
        else:
            await interaction.response.send_message("Es wird gerade nichts abgespielt.", ephemeral=True)

    @ui.button(label="Stop", style=discord.ButtonStyle.danger, emoji="⏹️")
    async def stop_button(self, interaction: discord.Interaction, button: ui.Button):
        voice_client = interaction.guild.voice_client
        if voice_client and voice_client.is_connected():
            PREV_SONGS.clear()
            CURRENT.clear()
            NEXT_SONGS.clear()
            voice_client.stop()
            await voice_client.disconnect()
            await interaction.response.send_message("Wiedergabe gestoppt und Kanal verlassen.", ephemeral=True)
        else:
            await interaction.response.send_message("Ich bin in keinem Sprachkanal.", ephemeral=True)


intents = discord.Intents.default()
client = MyClient(intents=intents)
YDL_OPTIONS = {'format': 'bestaudio', 'noplaylist': 'True'}
FFMPEG_OPTIONS = {'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5', 'options': '-vn'}

PREV_SONGS = list()
CURRENT = list()
NEXT_SONGS = list()


def get_info(query: str):
    if query.lower().startswith("https://"):
        with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
            info = ydl.extract_info(query, download=False)
    else:
        with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
            info = ydl.extract_info(f"ytsearch:{query}", download=False)['entries']
        info = info[0]
    return info


async def _join(interaction: discord.Interaction):
    if not interaction.user.voice:
        await interaction.response.send_message("Du befindest dich in keinem Sprachkanal, dem ich beitreten könnte.",
                                                ephemeral=True)
        return None

    voice_channel = interaction.user.voice.channel
    await voice_channel.connect()
    return voice_channel


async def _leave(interaction: discord.Interaction):
    voice_client = interaction.guild.voice_client
    if voice_client and voice_client.is_connected():
        await voice_client.disconnect()
        await interaction.response.send_message("Sprachkanal verlassen.", ephemeral=True)
    else:
        await interaction.response.send_message("Ich bin derzeit in keinem Sprachkanal.", ephemeral=True)


def minimize_info(info: dict) -> dict:
    return {
        "url": info.get("url"),
        "title": info.get("title"),
        "artist": info.get("artist"),
        "alt_title": info.get("alt_title"),
        "uploader": info.get("uploader"),
        "fulltitle": info.get("fulltitle"),
        "creator": info.get("creator"),
        "duration_string": info.get("duration_string")
    }


async def _add_next(query: str):
    info = get_info(query)
    if not info:
        await interaction.followup.send(f"Ich konnte den Song leider nicht finden")
        return
    NEXT_SONGS.insert(0, minimize_info(info))


async def _add_last(query: str):
    info = get_info(query)
    if not info:
        await interaction.followup.send(f"Ich konnte den Song leider nicht finden")
        return
    NEXT_SONGS.append(minimize_info(info))


async def skip_to_next(interaction: discord.Interaction):
    if NEXT_SONGS:
        if CURRENT:
            PREV_SONGS.insert(0, CURRENT.pop(0))
        CURRENT.insert(0, NEXT_SONGS.pop(0))
    else:
        await interaction.response.send_message("Es gibt keinen nächsten Song")
        return
    await _play(interaction)


async def skip_to_prev(interaction: discord.Interaction):
    if PREV_SONGS:
        if CURRENT:
            NEXT_SONGS.insert(0, CURRENT.pop(0))
        CURRENT.insert(0, PREV_SONGS.pop(0))
    else:
        await interaction.response.send_message("Es gibt keinen vorherigen Song")
        return
    await _play(interaction)


async def _play(interaction: discord.Interaction):
    info = CURRENT[0]
    voice_client = interaction.guild.voice_client
    if not voice_client:
        await _join(interaction)
        voice_client = interaction.guild.voice_client

    try:

        url = info['url']
        source = discord.FFmpegPCMAudio(url, **FFMPEG_OPTIONS)

        if voice_client.is_playing():
            voice_client.stop()
        voice_client.play(source, bitrate=256)

        view = MusicControlsView()
        artist = info.get("artist")
        if not artist:
            artist = info.get("creator")
        if not artist:
            artist = info.get("uploader")
        title = info.get("title")
        if not title:
            title = info.get("alt_title")
        if not title:
            title = info.get("fulltitle")
        duration = info.get("duration_string", "")
        try:
            await interaction.followup.send(f"▶️ Spiele jetzt: **{title} - {artist}**  `[{duration}]`", view=view)
        except discord.errors.NotFound:
            await interaction.response.edit_message(content=f"▶️ Spiele jetzt: **{title} - {artist}**  `[{duration}]`")



    except Exception as e:
        print(f"Ein detaillierter Fehler ist aufgetreten: {repr(e)}")
        print(f"Fehlertyp: {type(e)}")
        await interaction.followup.send("Ein Fehler ist beim Verarbeiten des Songs aufgetreten. Bitte sieh im Terminal nach Details.")


@client.tree.command(name="join", description="Der Bot betritt deinen aktuellen Sprachkanal.")
async def join(interaction: discord.Interaction):
    voice_channel = await _join(interaction)
    if not voice_channel:
        return
    await interaction.response.send_message(f"Erfolgreich dem Kanal `{voice_channel.name}` beigetreten!",
                                            ephemeral=True)

@client.tree.command(name="leave", description="Der Bot verlässt den Sprachkanal.")
async def leave(interaction: discord.Interaction):
    await _leave(interaction)


@client.tree.command(name="play", description="Spielt einen Song von YouTube ab.")
@app_commands.describe(query="Gib den YouTube-Link oder einen Suchbegriff ein.")
async def play(interaction: discord.Interaction, query: str):
    await interaction.response.defer()
    await _add_next(query)
    await skip_to_next(interaction)


@client.tree.command(name="play-next", description="Fügt einen Song am Anfang der Warteschlange ein")
@app_commands.describe(query="Gib den YouTube-Link oder einen Suchbegriff ein.")
async def play_next(interaction: discord.Interaction, query: str):
    await _add_next(query)


@client.tree.command(name="play-last", description="Fügt einen Song am Ende der Warteschlange ein")
@app_commands.describe(query="Gib den YouTube-Link oder einen Suchbegriff ein.")
async def play_last(interaction: discord.Interaction, query: str):
    await _add_last(query)


@client.tree.command(name="skip", description="Überspringe den aktuellen Song")
async def skip(interaction: discord.Interaction):
    await skip_to_next(interaction)


@client.tree.command(name="prev", description="Springe zum vorherigen Song")
async def prev(interaction: discord.Interaction):
    await skip_to_next(interaction)



if __name__ == '__main__':
    dc_token = os.getenv('DC_TOKEN')
    client.run(dc_token)
