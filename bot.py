from discord import app_commands
from dotenv import load_dotenv
import os
import discord
from discord import ui
import yt_dlp

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
            try:
                NEXT_SONGS.append(CURRENT[0])
                CURRENT[0] = PREV_SONGS.pop(-1)
                await _play(interaction, CURRENT[0])
            except IndexError:
                await interaction.response.send_message("Es gibt keinen vorherigen Song")
        else:
            await interaction.response.send_message("Es wird gerade nichts abgespielt.", ephemeral=True)

    @ui.button(label="Pause", style=discord.ButtonStyle.secondary, emoji="⏸️")
    async def pause_button(self, interaction: discord.Interaction, button: ui.Button):
        voice_client = interaction.guild.voice_client
        if voice_client and voice_client.is_connected():
            if voice_client.is_paused():
                voice_client.resume()
                await interaction.response.send_message("Wiedergabe läuft weiter", ephemeral=True)
            else:
                voice_client.pause()
                await interaction.response.send_message("Wiedergabe pausiert", ephemeral=True)
        else:
            await interaction.response.send_message("Ich bin in keinem Sprachkanal.", ephemeral=True)

    @ui.button(label="Skip", style=discord.ButtonStyle.secondary, emoji="⏩")
    async def skip_button(self, interaction: discord.Interaction, button: ui.Button):
        voice_client = interaction.guild.voice_client
        if voice_client or not voice_client.is_playing():
            try:
                PREV_SONGS.append(CURRENT[0])
                CURRENT[0] = NEXT_SONGS.pop(0)
                await _play(interaction, CURRENT[0])
            except IndexError:
                await interaction.response.send_message("Es gibt keinen nächsten Song")
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


async def _join(interaction: discord.Interaction):
    if not interaction.user.voice:
        await interaction.response.send_message("Du befindest dich in keinem Sprachkanal, dem ich beitreten könnte.",
                                                ephemeral=True)
        return

    voice_channel = interaction.user.voice.channel
    await voice_channel.connect()


async def _leave(interaction: discord.Interaction):
    voice_client = interaction.guild.voice_client
    if voice_client and voice_client.is_connected():
        await voice_client.disconnect()
        await interaction.response.send_message("Sprachkanal verlassen.", ephemeral=True)
    else:
        await interaction.response.send_message("Ich bin derzeit in keinem Sprachkanal.", ephemeral=True)



async def _play(interaction: discord.Interaction, query: str):
    voice_client = interaction.guild.voice_client
    if not voice_client:
        await _join(interaction)
        voice_client = interaction.guild.voice_client

    await interaction.response.defer()

    try:
        with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
            info = ydl.extract_info(f"ytsearch:{query}", download=False)['entries'][0]

        url = info['url']
        source = discord.FFmpegPCMAudio(url, **FFMPEG_OPTIONS)
        voice_client.play(source, bitrate=256)

        view = MusicControlsView()

        await interaction.followup.send(f"▶️ Spiele jetzt: **{info['title']}**", view=view)


    except Exception as e:
        print(f"Ein detaillierter Fehler ist aufgetreten: {repr(e)}")
        print(f"Fehlertyp: {type(e)}")
        await interaction.followup.send("Ein Fehler ist beim Verarbeiten des Songs aufgetreten. Bitte sieh im Terminal nach Details.")


@client.tree.command(name="join", description="Der Bot betritt deinen aktuellen Sprachkanal.")
async def join(interaction: discord.Interaction):
    await _join(interaction)
    await interaction.response.send_message(f"Erfolgreich dem Kanal `{voice_channel.name}` beigetreten!",
                                            ephemeral=True)

@client.tree.command(name="leave", description="Der Bot verlässt den Sprachkanal.")
async def leave(interaction: discord.Interaction):
    await _leave(interaction)


@client.tree.command(name="play", description="Spielt einen Song von YouTube ab.")
@app_commands.describe(query="Gib den YouTube-Link oder einen Suchbegriff ein.")
async def play(interaction: discord.Interaction, query: str):
    await _play(interaction, query)



if __name__ == '__main__':
    dc_token = os.getenv('DC_TOKEN')
    client.run(dc_token)
