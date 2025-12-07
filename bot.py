import os
import discord
from discord import app_commands, ui
from dotenv import load_dotenv
import yt_dlp

load_dotenv()

try:
    OPUS_PATH = os.getenv("OPUS_PATH")
    if not OPUS_PATH:
        print(">>> WARNUNG: OPUS_PATH ist in der .env-Datei nicht gesetzt. Versuche automatisches Laden.")
        discord.opus.load_opus(None)
    else:
        print(f"Versuche Opus von folgendem Pfad zu laden: {OPUS_PATH}")
        discord.opus.load_opus(OPUS_PATH)
    print(">>> Opus-Bibliothek erfolgreich geladen!")
except Exception as e:
    print(f">>> KRITISCHER FEHLER beim Laden von Opus: {repr(e)}")
    print(
        ">>> Stelle sicher, dass die Opus-Bibliothek installiert ist oder der OPUS_PATH in der .env-Datei korrekt ist.")
    exit(-1)


YDL_OPTIONS = {'format': 'bestaudio', 'noplaylist': 'True'}
FFMPEG_OPTIONS = {'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5', 'options': '-vn'}

music_queues = {}


# --- Helferfunktionen ---
def get_info(query: str):
    """Sucht nach einem Song auf YouTube und gibt die Metadaten zurück."""
    try:
        search_query = f"ytsearch:{query}" if not query.lower().startswith("https://") else query
        with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
            info = ydl.extract_info(search_query, download=False)
        # Wenn es eine Playlist ist (von ytsearch), nimm den ersten Eintrag
        if 'entries' in info:
            info = info['entries'][0]
        return info
    except Exception as e:
        print(f"Fehler bei yt-dlp: {e}")
        return None


def get_playlist_info(query: str):
    """Holt sich die Infos für eine Playlist oder einen einzelnen Song und gibt immer eine Liste zurück."""
    playlist_ydl_options = {'format': 'bestaudio', 'extract_flat': True, 'quiet': True}
    try:
        with yt_dlp.YoutubeDL(playlist_ydl_options) as ydl:
            info = ydl.extract_info(query, download=False)

        if 'entries' in info:
            title = info.get('title')
            channel = info.get('channel')
            # Es ist eine Playlist, gib die Liste der Video-Infos zurück
            return title + " - " + channel, info['entries']
        return None
    except Exception as e:
        print(f"Fehler beim Abrufen der Playlist-Info: {e}")
        return None


def minimize_info(info: dict) -> dict:
    """Reduziert die große Menge an Metadaten auf das Nötigste."""
    return {
        "url": info.get("url"),
        "title": info.get("title") or info.get("alt_title") or info.get("fulltitle"),
        "artist": info.get("artist") or info.get("creator") or info.get("uploader"),
        "duration_string": info.get("duration_string", "Unbekannt")
    }


# --- Die View-Klasse für die Steuerungs-Buttons ---
class MusicControlsView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Pause", style=discord.ButtonStyle.secondary, emoji="⏸️")
    async def pause_resume_button(self, interaction: discord.Interaction, button: ui.Button):
        voice_client = interaction.guild.voice_client
        if not voice_client or not (voice_client.is_playing() or voice_client.is_paused()):
            await interaction.response.send_message("Es wird gerade nichts abgespielt.", ephemeral=True)
            return

        if voice_client.is_paused():
            voice_client.resume()
            button.label = "Pause"
            button.emoji = "⏸️"
            await interaction.response.edit_message(view=self)
        else:
            voice_client.pause()
            button.label = "Fortsetzen"
            button.emoji = "▶️"
            await interaction.response.edit_message(view=self)

    @ui.button(label="Skip", style=discord.ButtonStyle.secondary, emoji="⏭️")
    async def skip_button(self, interaction: discord.Interaction, button: ui.Button):
        voice_client = interaction.guild.voice_client
        if voice_client and voice_client.is_playing():
            voice_client.stop()
            await interaction.response.send_message("Song übersprungen.", ephemeral=True)
        else:
            await interaction.response.send_message("Es wird gerade nichts abgespielt.", ephemeral=True)

    @ui.button(label="Stop", style=discord.ButtonStyle.danger, emoji="⏹️")
    async def stop_button(self, interaction: discord.Interaction, button: ui.Button):
        guild_id = interaction.guild.id
        if guild_id in music_queues:
            music_queues[guild_id]["queue"].clear()

        voice_client = interaction.guild.voice_client
        if voice_client and voice_client.is_connected():
            voice_client.stop()
            await voice_client.disconnect()
            await interaction.response.send_message("Wiedergabe gestoppt und Warteschlange geleert.", ephemeral=True)
        else:
            await interaction.response.send_message("Nichts zu stoppen.", ephemeral=True)


# --- Bot-Klasse und Events ---
class MyClient(discord.Client):
    def __init__(self, *, intents: discord.Intents):
        super().__init__(intents=intents)
        self.tree = discord.app_commands.CommandTree(self)

    async def on_ready(self):
        await self.tree.sync()
        print(f'Eingeloggt als {self.user} und Befehle synchronisiert!')


intents = discord.Intents.default()
intents.voice_states = True
client = MyClient(intents=intents)


# --- Das Herzstück: Die Wiedergabefunktion ---
async def play_next_in_queue(guild: discord.Guild, initial_interaction: discord.Interaction = None):
    """Spielt den nächsten Song ab. Wird vom "after"-Callback immer wieder aufgerufen."""
    guild_id = guild.id
    if guild_id in music_queues and music_queues[guild_id]["queue"]:
        current_song_info = music_queues[guild_id]["queue"].pop(0)

        source = discord.FFmpegPCMAudio(current_song_info['url'], **FFMPEG_OPTIONS)
        voice_client = guild.voice_client

        if not voice_client:
            if initial_interaction and initial_interaction.user.voice:
                try:
                    voice_client = await initial_interaction.user.voice.channel.connect()
                except Exception as e:
                    print(f"Fehler beim Verbinden mit dem Sprachkanal: {e}")
                    return
            else:
                return

        after_callback = lambda e: client.loop.create_task(play_next_in_queue(guild, initial_interaction))
        voice_client.play(source, after=after_callback, bitrate=256)

        content = f"▶️ Spiele jetzt: **{current_song_info['title']} - {current_song_info['artist']}**  `[{current_song_info['duration_string']}]`"
        view = MusicControlsView()

        try:
            if initial_interaction and not initial_interaction.response.is_done():
                await initial_interaction.followup.send(content, view=view)
                msg = await initial_interaction.original_response()
                music_queues[guild_id]["now_playing_message"] = msg
            elif "now_playing_message" in music_queues[guild_id]:
                msg = music_queues[guild_id]["now_playing_message"]
                await msg.edit(content=content, view=view)
        except (discord.errors.NotFound, AttributeError) as e:
            print(f"Konnte 'Now Playing'-Nachricht nicht finden/bearbeiten, sende neue. Fehler: {e}")
            channel = initial_interaction.channel if initial_interaction else guild.text_channels[0]
            try:
                msg = await channel.send(content, view=view)
                music_queues[guild_id]["now_playing_message"] = msg
            except Exception as e:
                print(f"Konnte keine neue 'Now Playing'-Nachricht senden. Fehler: {e}")


# --- Slash-Befehle ---
@client.tree.command(name="join", description="Der Bot betritt deinen aktuellen Sprachkanal.")
async def join(interaction: discord.Interaction):
    if not interaction.user.voice:
        await interaction.response.send_message("Du befindest dich in keinem Sprachkanal.", ephemeral=True)
        return

    voice_channel = interaction.user.voice.channel
    await voice_channel.connect()
    await interaction.response.send_message(f"Erfolgreich dem Kanal `{voice_channel.name}` beigetreten!",
                                            ephemeral=True)


@client.tree.command(name="leave", description="Der Bot verlässt den Sprachkanal.")
async def leave(interaction: discord.Interaction):
    voice_client = interaction.guild.voice_client
    if voice_client and voice_client.is_connected():
        await voice_client.disconnect()
        await interaction.response.send_message("Sprachkanal verlassen.", ephemeral=True)
    else:
        await interaction.response.send_message("Ich bin derzeit in keinem Sprachkanal.", ephemeral=True)


@client.tree.command(name="play", description="Spielt einen Song ab oder fügt ihn zur Warteschlange hinzu.")
@app_commands.describe(query="Gib den YouTube-Link oder einen Suchbegriff ein.")
async def play(interaction: discord.Interaction, query: str):
    await interaction.response.defer(ephemeral=True, thinking=True)

    info = get_info(query)
    if not info:
        await interaction.followup.send("Konnte den Song nicht finden.")
        return

    guild_id = interaction.guild.id
    if guild_id not in music_queues:
        music_queues[guild_id] = {"queue": [], "now_playing_message": None}

    music_queues[guild_id]["queue"].append(minimize_info(info))
    await interaction.followup.send(f"Zur Warteschlange hinzugefügt: **{info.get('title')}**")

    voice_client = interaction.guild.voice_client
    if not voice_client or not voice_client.is_playing():
        await play_next_in_queue(interaction.guild, initial_interaction=interaction)


@client.tree.command(name="play-album", description="Spielt einen Song ab oder fügt ihn zur Warteschlange hinzu.")
@app_commands.describe(query="Gib den YouTube-Link oder einen Suchbegriff ein.")
async def play(interaction: discord.Interaction, query: str):
    await interaction.response.defer(ephemeral=True, thinking=True)

    info = get_playlist_info(query)
    if not info:
        return

    guild_id = interaction.guild.id
    if guild_id not in music_queues:
        music_queues[guild_id] = {"queue": [], "now_playing_message": None}

    for entry in info[1]:
        song_info = get_info(entry["url"])
        music_queues[guild_id]["queue"].append(minimize_info(song_info))

        voice_client = interaction.guild.voice_client
        if not voice_client or not voice_client.is_playing():
            await play_next_in_queue(interaction.guild, initial_interaction=interaction)

    await interaction.followup.send(f"Zur Warteschlange hinzugefügt: **{info[0]}**")


@client.tree.command(name="play-next", description="Spielt einen Song ab oder fügt ihn als nächstes zur Warteschlange hinzu.")
@app_commands.describe(query="Gib den YouTube-Link oder einen Suchbegriff ein.")
async def play_next(interaction: discord.Interaction, query: str):
    await interaction.response.defer(ephemeral=True, thinking=True)
    info = get_info(query)
    if not info:
        await interaction.followup.send("Konnte den Song nicht finden.")
        return

    guild_id = interaction.guild.id
    if guild_id not in music_queues:
        music_queues[guild_id] = {"queue": [], "now_playing_message": None}

    music_queues[guild_id]["queue"].insert(0, minimize_info(info))
    await interaction.followup.send(f"Als nächstes zur Warteschlange hinzugefügt: **{info.get('title')}**")

    voice_client = interaction.guild.voice_client
    if not voice_client or not voice_client.is_playing():
        await play_next_in_queue(interaction.guild, initial_interaction=interaction)


@client.tree.command(name="skip", description="Überspringt den aktuellen Song.")
async def skip(interaction: discord.Interaction):
    voice_client = interaction.guild.voice_client
    if voice_client and voice_client.is_playing():
        voice_client.stop()
        await interaction.response.send_message("Song übersprungen.", ephemeral=True)
    else:
        await interaction.response.send_message("Es wird gerade nichts abgespielt.", ephemeral=True)


@client.tree.command(name="stop", description="Stoppt die Wiedergabe und leert die Warteschlange.")
async def stop(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    if guild_id in music_queues:
        music_queues[guild_id]["queue"].clear()

    voice_client = interaction.guild.voice_client
    if voice_client and voice_client.is_connected():
        voice_client.stop()
        await voice_client.disconnect()
        await interaction.response.send_message("Wiedergabe gestoppt und Warteschlange geleert.", ephemeral=True)
    else:
        await interaction.response.send_message("Nichts zu stoppen.", ephemeral=True)


if __name__ == '__main__':
    dc_token = os.getenv('DC_TOKEN')
    if not dc_token:
        print("KRITISCHER FEHLER: DC_TOKEN wurde nicht in der .env-Datei gefunden.")
    else:
        client.run(dc_token)
