from cachetools.func import ttl_cache
from discord import app_commands, ui
from dotenv import load_dotenv
import asyncio
import discord
import os
import random
import time
import yt_dlp
import yt_dlp_plugins

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


YDL_OPTIONS = {'format': 'bestaudio', 'noplaylist': 'True', "plugin_dirs": yt_dlp_plugins.__path__}
FFMPEG_OPTIONS = {'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5', 'options': '-vn'}

music_queues = {}
MAX_PREV_SONGS_SIZE = 500


# --- Helferfunktionen ---
@ttl_cache(ttl=24 * 60 * 60)  # 24h
def get_info(query: str):
    """Sucht nach einem Song auf YouTube und gibt die Metadaten zurück."""
    try:
        search_query = f"ytsearch:{query}" if not query.lower().startswith("https://") else query
        print("getting new url")
        with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
            info = ydl.extract_info(search_query, download=False)
        if 'entries' in info:
            info = info['entries'][0]
        return info
    except Exception as e:
        print(f"Fehler bei yt-dlp: {e}")
        return None

@ttl_cache(ttl=24 * 60 * 60)  # 24h
def get_playlist_info(query: str):
    """Holt sich die Infos für eine Playlist oder einen einzelnen Song und gibt immer eine Liste zurück."""
    playlist_ydl_options = {'format': 'bestaudio', 'extract_flat': True, 'quiet': True}
    try:
        search_query = f"ytsearch:{query}" if not query.lower().startswith("https://") else query
        with yt_dlp.YoutubeDL(playlist_ydl_options) as ydl:
            info = ydl.extract_info(search_query, download=False)

        if 'entries' in info:
            title = info.get('title', "")
            channel = info.get('channel', "")
            # Es ist eine Playlist, gib die Liste der Video-Infos zurück
            return (f"{title if title else ''}{' - ' if title and channel else ''}{channel if channel else ''}",
                    info['entries'])
        return None
    except Exception as e:
        print(f"Fehler beim Abrufen der Playlist-Info: {e}")
        return None


def minimize_info(info: dict) -> dict:
    """Reduziert die große Menge an Metadaten auf das Nötigste."""
    url: str = info.get("url")
    title: str =  info.get("title") or info.get("alt_title") or info.get("fulltitle", "")
    artist: str = info.get("artist") or info.get("creator") or info.get("uploader", "")
    duration_string: str =  info.get("duration_string", "")

    if title and artist:
        title = title.replace(artist, "")
        title = title.strip()
        if title.startswith("-") or title.endswith("-"):
            title = title.replace("-", "")
            title = title.strip()

    return {
        "url": url,
        "title": title,
        "artist": artist,
        "duration_string": duration_string
    }


def format_queue(prev: list[dict], queue: list[dict], max_len: int = 30, max_width: int = 35) -> str:
    if not prev and not queue:
        return "Die Wiedergabeliste ist leer"
    prev: list[str] = [f"{x['title']} - {x['artist']}" for x in prev]
    prev = [x[:max_width - 3] for x in prev]

    queue: list[str] = [f"{x['title']} - {x['artist']}" for x in queue]
    queue = [x[:max_width - 3] for x in queue]

    current = ""
    if prev:
        current = prev.pop(-1)

    prev = prev[::-1]

    prev_short = prev[:max_len // 3]
    queue_short = queue[:2 * max_len // 3]

    message = ""
    if len(prev) != len(prev_short):
        message += f"... {len(prev) - len(prev_short)} - weitere Songs\n"
    for element in prev_short:
        message += f"- {element}\n"
    if current:
        message += f"▶ {current}\n"
    for element in queue_short:
        message += f"- {element}\n"

    if len(queue) != len(queue_short):
        message += f"... {len(queue) - len(queue_short)} - weitere Songs\n"

    return message


# --- Die View-Klasse für die Steuerungs-Buttons ---
class MusicControlsView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)


    @ui.button(label="Loop", style=discord.ButtonStyle.secondary, emoji="🔄")
    async def loop_button(self, interaction: discord.Interaction, button: ui.Button):
        voice_client = interaction.guild.voice_client
        if not voice_client or not (voice_client.is_playing() or voice_client.is_paused()) or not music_queues.get(interaction.guild.id):
            await interaction.response.send_message("Es wird gerade nichts abgespielt.", ephemeral=True)
            return

        loop = music_queues[interaction.guild.id].get("Loop")
        if loop is not True:
            music_queues[interaction.guild.id]["Loop"] = True
            await interaction.response.send_message("Endlosschleife ist jetzt aktiviert", ephemeral=True)
        else:
            music_queues[interaction.guild.id]["Loop"] = False
            await interaction.response.send_message("Endlosschleife ist jetzt deaktiviert", ephemeral=True)

    @ui.button(label="Prev", style=discord.ButtonStyle.secondary, emoji="⏮️")
    async def prev_button(self, interaction: discord.Interaction, button: ui.Button):
        voice_client = interaction.guild.voice_client
        if voice_client:
            if len(music_queues[interaction.guild.id]["prev_songs"]) < 2:
                await interaction.response.send_message("Es gibt keinen vorherigen Song", ephemeral=True)
                return
            music_queues[interaction.guild.id]["queue"].insert(0, music_queues[interaction.guild.id]["prev_songs"].pop(-1))
            if voice_client and voice_client.is_playing():
                music_queues[interaction.guild.id]["queue"].insert(0, music_queues[interaction.guild.id]["prev_songs"].pop(-1))
                voice_client.stop()
            await interaction.response.send_message("Zum vorherigen Song gesprungen", ephemeral=True)
        else:
            await interaction.response.send_message("Etwas ist schiefgelaufen")

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
            music_queues[guild_id]["prev_songs"].clear()

        voice_client = interaction.guild.voice_client
        if voice_client and voice_client.is_connected():
            voice_client.stop()
            await voice_client.disconnect()
            await interaction.response.send_message("Wiedergabe gestoppt und Warteschlange geleert.", ephemeral=True)
            msg = music_queues[guild_id]["now_playing_message"]
            await msg.unpin()
            await msg.edit(view=None)
            music_queues[guild_id].pop("now_playing_message")
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


# --- Die Wiedergabefunktion ---
async def play_next_in_queue(guild: discord.Guild, initial_interaction: discord.Interaction = None):
    """Spielt den nächsten Song ab. Wird vom "after"-Callback immer wieder aufgerufen."""
    guild_id = guild.id
    if not music_queues[guild_id].get("prev_songs"):
        music_queues[guild_id]["prev_songs"] = []
    if guild_id in music_queues and music_queues[guild_id]["queue"] or music_queues[guild_id].get("current_song"):
        if music_queues[guild_id].get("Loop") is not True:
            current_song_info = music_queues[guild_id]["queue"].pop(0)
            music_queues[guild_id]["prev_songs"].append(current_song_info)
            if len(music_queues[guild_id]["prev_songs"]) >= MAX_PREV_SONGS_SIZE:
                music_queues[guild_id]["prev_songs"].pop(0)
        else:
            current_song_info = music_queues[guild_id]["prev_songs"][-1]

        if current_song_info["url"].startswith("temp_audio/"):
            source = discord.FFmpegPCMAudio(current_song_info['url'])
        else:
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
        voice_client.play(source, after=after_callback, bitrate=256, signal_type="music")

        content = f"▶️ Spiele jetzt: **{current_song_info['title']} - {current_song_info['artist']}**  `[{current_song_info['duration_string']}]`"
        view = MusicControlsView()

        try:
            if initial_interaction and not initial_interaction.response.is_done():
                await initial_interaction.followup.send(content, view=view)
                msg = await initial_interaction.original_response()
                music_queues[guild_id]["now_playing_message"] = msg
                await msg.pin()
            elif "now_playing_message" in music_queues[guild_id]:
                msg = music_queues[guild_id]["now_playing_message"]
                await msg.edit(content=content, view=view)
        except (discord.errors.NotFound, AttributeError) as e:
            print(f"Konnte 'Now Playing'-Nachricht nicht finden/bearbeiten, sende neue. Fehler: {e}")
            channel = initial_interaction.channel if initial_interaction else guild.text_channels[0]
            try:
                msg = await channel.send(content, view=view)
                music_queues[guild_id]["now_playing_message"] = msg
                await msg.pin()
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


@client.tree.command(name="play", description="Spielt einen Song ab oder fügt ihn zur Warteschlange hinzu.")
@app_commands.describe(query="Gib den YouTube-Link oder einen Suchbegriff ein.")
async def play(interaction: discord.Interaction, query: str):
    await interaction.response.defer(thinking=True)

    info = get_info(query)
    if not info:
        await interaction.followup.send("Konnte den Song nicht finden oder der Song ist Altersbeschränkt.", ephemeral=True)
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
        x = time.time()
        song_info = get_info(entry["url"])
        time_delta = time.time() - x
        print(f"Ladezeit {time_delta:.2f} sekunden")
        if not song_info:
            await interaction.followup.send("Konnte den Song nicht finden oder der Song ist Altersbeschränkt.", ephemeral=True)
            if time_delta > 0.1:
                await asyncio.sleep(5 + random.randint(-50, 50) / 100)
            continue
        music_queues[guild_id]["queue"].append(minimize_info(song_info))

        voice_client = interaction.guild.voice_client
        if not voice_client or not voice_client.is_playing():
            await play_next_in_queue(interaction.guild, initial_interaction=interaction)
        if time_delta > 0.1:
            await asyncio.sleep(5 + random.randint(-50, 50) / 100)

    await interaction.followup.send(f"Zur Warteschlange hinzugefügt: **{info[0]}**")


@client.tree.command(name="play-next", description="Spielt einen Song ab oder fügt ihn als nächstes zur Warteschlange hinzu.")
@app_commands.describe(query="Gib den YouTube-Link oder einen Suchbegriff ein.")
async def play_next(interaction: discord.Interaction, query: str):
    await interaction.response.defer(ephemeral=True, thinking=True)
    info = get_info(query)
    if not info:
        await interaction.followup.send("Konnte den Song nicht finden oder der Song ist Altersbeschränkt.", ephemeral=True)
        return

    guild_id = interaction.guild.id
    if guild_id not in music_queues:
        music_queues[guild_id] = {"queue": [], "now_playing_message": None}

    music_queues[guild_id]["queue"].insert(0, minimize_info(info))
    await interaction.followup.send(f"Als nächstes zur Warteschlange hinzugefügt: **{info.get('title')}**")

    voice_client = interaction.guild.voice_client
    if not voice_client or not voice_client.is_playing():
        await play_next_in_queue(interaction.guild, initial_interaction=interaction)

@client.tree.command(name="play-file", description="Spielt eine hochgeladene Audiodatei ab.")
# Hier definieren wir den Parameter 'datei', den der Nutzer hochladen muss.
@app_commands.describe(datei="Die Audiodatei, die du abspielen möchtest.")
async def play_file(interaction: discord.Interaction, datei: discord.Attachment):
    await interaction.response.defer(ephemeral=True, thinking=True)
    file_path = f"temp_audio/{datei.filename}"
    await datei.save(file_path)
    if not music_queues.get(interaction.guild.id):
        music_queues[interaction.guild.id] = {"queue": [], "now_playing_message": None}
    music_queues[interaction.guild.id]["queue"].append(minimize_info({
        "url": file_path,
        "title": file_path.split("/")[-1].split(".")[0],
        "uploader": interaction.user.name,
        "duration": datei.duration
    }))
    await interaction.followup.send(f"Als nächstes zur Warteschlange hinzugefügt: **{file_path.split('/')[-1].split('.')[0]}**")
    voice_client = interaction.guild.voice_client
    if not voice_client or not voice_client.is_playing():
        await play_next_in_queue(interaction.guild, initial_interaction=interaction)


@client.tree.command(name="skip", description="Überspringt den aktuellen Song.")
async def skip(interaction: discord.Interaction):
    voice_client = interaction.guild.voice_client
    if voice_client and voice_client.is_playing():
        voice_client.stop()
        await interaction.response.send_message("Song übersprungen", ephemeral=True)
    else:
        await interaction.response.send_message("Es wird gerade nichts abgespielt", ephemeral=True)


@client.tree.command(name="prev", description="Springt zum vorherigen Song.")
async def skip(interaction: discord.Interaction):
    voice_client = interaction.guild.voice_client
    if voice_client:
        if len(music_queues[interaction.guild.id]["prev_songs"]) < 2:
            await interaction.response.send_message("Es gibt keinen vorherigen Song", ephemeral=True)
            return

        music_queues[interaction.guild.id]["queue"].insert(0, music_queues[interaction.guild.id]["prev_songs"].pop(-1))
        if voice_client and voice_client.is_playing():
            music_queues[interaction.guild.id]["queue"].insert(0, music_queues[interaction.guild.id]["prev_songs"].pop(-1))
            voice_client.stop()

        await interaction.response.send_message("Zum vorherigen Song gesprungen", ephemeral=True)
    else:
        await interaction.response.send_message("Etwas ist schiefgelaufen")



@client.tree.command(name="leave", description="Stoppt die Wiedergabe und leert die Warteschlange.")
async def leave(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    if guild_id in music_queues:
        music_queues[guild_id]["queue"].clear()
        music_queues[guild_id]["prev_songs"].clear()

    voice_client = interaction.guild.voice_client
    if voice_client and voice_client.is_connected():
        voice_client.stop()
        await voice_client.disconnect()
        await interaction.response.send_message("Wiedergabe gestoppt und Warteschlange geleert.")
        msg = music_queues[guild_id]["now_playing_message"]
        await msg.unpin()
        await msg.edit(view=None)
        music_queues[guild_id].pop("now_playing_message")
    else:
        await interaction.response.send_message("Nichts zu stoppen.", ephemeral=True)


@client.tree.command(name="loop-on", description="Stoppt die Wiedergabe und leert die Warteschlange.")
async def loop_on(interaction: discord.Interaction):
    music_queues[interaction.guild.id]["Loop"] = True
    await interaction.response.send_message("Endlosschleife ist aktiviert", ephemeral=True)


@client.tree.command(name="loop-off", description="Stoppt die Wiedergabe und leert die Warteschlange.")
async def loop_off(interaction: discord.Interaction):
    music_queues[interaction.guild.id]["Loop"] = False
    await interaction.response.send_message("Endlosschleife ist deaktiviert", ephemeral=True)


@client.tree.command(name="loop-status", description="Stoppt die Wiedergabe und leert die Warteschlange.")
async def loop_status(interaction: discord.Interaction):
    loop = music_queues[interaction.guild.id].get("Loop")
    await interaction.response.send_message(f"Endlosschleife ist {'de' if loop is not True else ''}aktiviert", ephemeral=True)


@client.tree.command(name="queue", description="Zeigt bis zu 30 Elemente der aktuellen Wiedergabeliste an")
async def queue(interaction: discord.Interaction):
    if not music_queues.get(interaction.guild.id):
        await interaction.response.send_message("Es gibt keine Wiedergabeliste", ephemeral=True)
        return
    prev = music_queues[interaction.guild.id].get("prev_songs")
    queue = music_queues[interaction.guild.id].get("queue")


    message = format_queue(prev, queue)
    await interaction.response.send_message(message)


if __name__ == '__main__':
    if not os.path.isdir("temp_audio"):
        os.mkdir("temp_audio")
    dc_token = os.getenv('DC_TOKEN')
    if not dc_token:
        print("KRITISCHER FEHLER: DC_TOKEN wurde nicht in der .env-Datei gefunden.")
    else:
        client.run(dc_token)
