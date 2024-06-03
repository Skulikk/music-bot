from discord.ext import commands
from discord.utils import get
from youtubesearchpython import *
from spotipy.oauth2 import SpotifyClientCredentials

import os
import discord
import asyncio
import re
import yt_dlp
import random
import json
import spotipy
import threading

class music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        self.song_queue = []
        self.queue_for_queue = []

        #flags
        self.task_done = False
        self.predownloaded = False
        self.predownloading = False
        self.update_req = 0
        self.on_repeat = False
        self.change = None

        self.queue_message = None

        #global settings
        f = open('settings.json')
        settings = json.load(f)
        self.dj_channel = settings["dj_channel"]
        self.max_track_len = settings["max_track_len"]
        self.file_name = settings["file_name"]
        self.database_file = settings["database_file"]

        #Spotify authentication
        client_credentials_manager = SpotifyClientCredentials(client_id=settings["spotify_id"], client_secret=settings["spotify_secret"])
        self.sp = spotipy.Spotify(client_credentials_manager = client_credentials_manager)

    async def shuffle_queue(self):
        random.shuffle(self.song_queue)
        await self.send_queue_embed()

    async def error_message(self, message):
        msg = await self.ctx.send(message)
        await asyncio.sleep(3)
        msg.delete()

    def clear_queue(self):
        self.song_queue.clear()
        self.queue_message = None

    def YT_search(self, query, direct):
        #explicit url mode
        if re.match(r"^(?:https?:)?(?:\/\/)?(?:youtu\.be\/|(?:www\.|m\.)?youtube\.com\/(?:watch|v|embed)(?:\.php)?(?:\?.*v=|\/))([a-zA-Z0-9\_-]{7,15})(?:[\?&][a-zA-Z0-9\_-]+=[a-zA-Z0-9\_-]+)*(?:[&\/\#].*)?$", query):
            res = Video.getInfo(query)
            #no result
            if (not res):
                return 0
            res = res["link"], res["title"], int(res["duration"]["secondsText"]), res["thumbnails"][0]["url"]
        else:
            videosSearch = VideosSearch(query, limit = 1)
            #no result
            if (not videosSearch.result()["result"]):
                return 0
            res = videosSearch.result()["result"][0]

            #get song duration (from mm:ss format)
            mm , ss = map(int, res["duration"].split(':'))
            duration = mm*60 + ss
            res = res["link"], res["title"], duration, res["thumbnails"][0]["url"]
        if (direct):
            return res
        else:
            self.song_queue.append(res)
            self.update_req += 1

    def SPOT_fetch(self, URI, batch, mode):
        tracks = []
        i = 0

        fetched_data = self.sp.playlist_tracks(URI, offset=1+batch*25)["items"] if mode else self.sp.album_tracks(URI, offset=1+batch*25)["items"]
        for track in fetched_data:
            tracks.append(track)
            i += 1
            if (i == 25):
                break

        if (mode == 1):
            for track in tracks:
                track_name = track["track"]["name"]
                artist_uri = track["track"]["artists"][0]["uri"]
                artist_info = self.sp.artist(artist_uri)
                self.queue_for_queue.append(track_name + " " + artist_info["name"])    
        else:
            for track in tracks:
                track_name = track["name"]
                self.queue_for_queue.append(track_name + " " + track["artists"][0]["name"])    

    def YT_download(self, url, name='downloaded.m4a'):
        ydl_opts = {
            'format'            : 'm4a/bestaudio/best',
            'outtmpl'           : name,
            '--ffmpeg-location' : './ffmpeg/bin/ffmpeg.exe',
            '--no-continue'     : 1,
            'postprocessors'    : [{
                'key'           : 'FFmpegExtractAudio',
                'preferredcodec': 'm4a',
            }]
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                if (name == "predownloaded.m4a"):
                    try:
                        os.remove('predownloaded.m4a')
                    except:
                        pass
                    ydl.download(url[0])
                    self.predownloaded = True
                    self.predownloading = False
                else:
                    ydl.download(url[0])
        except:
            #download failed, try again
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download(url[0])
            except:
                #something fucked up
                return 1
        return 0
    
    async def send_queue_embed(self):
        i = 1
        try:
            self.embed_queue.clear_fields()
        except:
            pass
        self.embed_queue = discord.Embed(title="Queue", color=0x0000ff)

        if (len(self.song_queue) > 24):
            if (len(self.queue_for_queue) > 0):
                self.embed_queue.set_footer(text="Queued tracks: " + str(len(self.song_queue)) + "\nOnly first 24 tracks are shown.\nAdding to the queue in progress. Tracks left to add: " + str(len(self.queue_for_queue)))
            else:    
                self.embed_queue.set_footer(text="Queued tracks: " + str(len(self.song_queue)) + "\nOnly first 24 tracks are shown.")
        else:
            if (len(self.queue_for_queue) > 0):
                self.embed_queue.set_footer(text="Queued tracks: " + str(len(self.song_queue)) + "\nAdding to the queue in progress. Tracks left to add: " + str(len(self.queue_for_queue)))
        
        if (len(self.song_queue)) >= 1:
            for song in self.song_queue:
                if (i > 24):
                    break
                self.embed_queue.add_field(name=str(i)+"   "+song[1], value="", inline=False)
                i += 1
        else:
            self.embed_queue.add_field(name="The queue is empty. You can change it with \"!play ...\" command", value="", inline=False)

        #queue msg already exists
        if (self.queue_message):
            await self.queue_message.edit(embed=self.embed_queue)
        else:
            button_view=View_queue_buttons(self, self.bot, self.ctx.guild, self.song_queue, self.ctx, None, self.predownloaded, timeout=None)
            self.queue_message = await self.ctx.send(embed=self.embed_queue, view=button_view)
            button_view.queue_message = self.queue_message

    #sets "task_done" flag to True after song finishes
    def finished(self):
        self.task_done = True

    async def play_task(self, voice, duration, message, name, thumbnail):
        self.task_done = False
        voice.play(discord.FFmpegPCMAudio(self.file_name), after=lambda e: self.finished())

        whites = 1 #bruh
        skip_counter = 1
        skip_counter_limit = 9
        predownload_sent = 0
        line = "⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛"
        embed_player = discord.Embed(title="***" + name + "***", color=0x0000ff)
        embed_player.set_thumbnail(url=thumbnail)
        embed_player.add_field(name=line + " " + sec_min(duration) + " s", value="** **", inline=True)
        if(len(self.song_queue)):
            embed_player.set_footer(text="Next up: " + self.song_queue[0][1])
        await message.edit(embed=embed_player)

        skip = duration/200

        #wait here till the song finishes
        while(not self.task_done):

            if(not self.on_repeat):
                if(self.predownloaded and not predownload_sent):
                    embed_player.remove_footer()
                    if(len(self.song_queue)):
                        embed_player.set_footer(text="Next up: " + self.song_queue[0][1] + " (preloaded)")
                    await message.edit(embed=embed_player)
                    predownload_sent = 1


                #queue shuffled
                if(not self.predownloaded and predownload_sent):
                    embed_player.remove_footer()
                    if(len(self.song_queue)):
                        embed_player.set_footer(text="Next up: " + self.song_queue[0][1])
                    await message.edit(embed=embed_player)
                    predownload_sent = 0
                    embed_player.remove_footer
            else:
                embed_player.remove_footer()
                embed_player.set_footer(text="Next up: " + name)
                predownload_sent = 0

            if (self.update_req > 5 or (self.update_req and not len(self.queue_for_queue))):
                await self.send_queue_embed()
                self.update_req = 0

            if (len(self.queue_for_queue)):
                search = threading.Thread(target=self.YT_search, args=(self.queue_for_queue.pop(0), 0))
                search.start()

            if (not self.predownloaded and not self.predownloading and len(self.song_queue)):
                self.predownloading = True
                try:
                    os.remove('predownloaded.m4a')
                except:
                    pass
                download = threading.Thread(target=self.YT_download, args=(self.song_queue[0], "predownloaded.m4a", ))
                download.start()

            #some powerful magic happens here
            if(voice.is_playing()):
              
              if (skip_counter < skip_counter_limit):
                  await asyncio.sleep(skip)
                  skip_counter += 1
              else:
                    skip_counter = 0
                    await asyncio.sleep(skip)
                    line = "⬜"*whites + "⬛"*(19-whites)
                    embed_player.clear_fields()
                    embed_player.add_field(name=line + " " + sec_min(duration) + " s", value="** **", inline=True)
                    await message.edit(embed=embed_player)
                    whites += 1
            else:
               await asyncio.sleep(0.1)

    @commands.command(name="play")
    async def play(self, ctx:commands.Context, *args):

        #wrong text channel error msg
        if (ctx.channel.id != self.dj_channel):
            channel_name = self.bot.get_channel(int(self.dj_channel))
            await ctx.send("<:point_right:1013917029859868682> #" + str(channel_name))
            return
        
        self.ctx = ctx

        voice = discord.utils.get(self.bot.voice_clients, guild = ctx.guild)

        url     = None
        search  = ""

        #voice not connected -> prepare text channel
        if (not voice):
            try:
                await ctx.channel.purge()
            except:
                pass

        #prepare voice client
        if ((voice and voice.is_connected()) and not(voice.is_playing() or voice.is_paused())):
            await voice.disconnect()
            voice.cleanup()
            await ctx.channel.purge()

        if args[0] == "-q":
            if len(args) == 2:
                length = int(args[1])
                if (int(args[1]) > 20 or int(args[1]) < 2):
                    await self.error_message("***Wrong use of -q***")
                    return
            else:
                length = 10

            music_list = []
            music_list_to_play = []
            line_count = 0
                
            with open(self.database_file) as f:
                for line in f:
                    line_count += 1
                    line = [line.split("$")[0]]
                    music_list.append(line)

            if line_count < length:
                await self.error_message("***not enought database entries***")
                return
            
            #random numbers for list shuffle
            song_numbers = random.sample(range(0, (len(music_list) - 1)), length)
  
            #shuffle
            for i in song_numbers:
                music_list_to_play.append(music_list[i])

            #add the rest to the queue
            for song in music_list_to_play:
                self.queue_for_queue.append(song[0])

        else:
            for word in args:
                search = search + " " + word
            search = search.strip()

            if re.match(r"^(?:https:\/\/)((?:www\.)|(?:m\.))?soundcloud\.com\/[a-z0-9](?!.*?(-|_){2})[\w-]{1,23}[a-z0-9](?:\/.+)?$", search):
                await self.error_message("***Soundcloud ještě není podporován.***")
                return
            elif re.match(r"^https:\/\/open.spotify.com\/playlist\/[a-zA-Z0-9]*", search) or re.match(r"^https:\/\/open.spotify.com\/album\/[a-zA-Z0-9]*", search):
                #remove "?" in spotify url
                try:
                    search = search.split("?")[0]
                except:
                    search = search
                URI = search.split("/")[-1].split("?")[0]

                try:
                    if re.match(r"^https:\/\/open.spotify.com\/playlist\/[a-zA-Z0-9]*", search):
                        track = self.sp.playlist_tracks(URI)["items"][0]
                        artist_uri = track["track"]["artists"][0]["uri"]
                        self.queue_for_queue.append(track["track"]["name"] + " " + self.sp.artist(artist_uri)["name"])
                        for i in range (0, 50):
                            fetch = threading.Thread(target=self.SPOT_fetch, args=(URI, i, 1))
                            fetch.start()
                    else:
                        track = self.sp.album_tracks(URI)["items"][0]
                        self.queue_for_queue.append(track["name"] + " " + track["artists"][0]["name"])
                        for i in range (0, 50):
                            fetch = threading.Thread(target=self.SPOT_fetch, args=(URI, i, 2))
                            fetch.start()

                except Exception as e:
                    print(e)
                    return
            else:
                self.queue_for_queue.append(search)

        file = open(self.database_file,'r+')

        #first track, search for details directly
        if not(voice and voice.is_connected()):
            url = self.YT_search(self.queue_for_queue.pop(), 1)
            if url[0] not in file.read():
                try:
                    file.write(url[0]+"$"+url[1]+"\n")
                except:
                    file.write(url[0]+"$"+"encoding err\n")

            voiceChannel = ctx.author.voice.channel
            voice = await voiceChannel.connect()

            embed_player = discord.Embed(title="***" + url[1] + "***", color=0x0000ff)
            embed_player.add_field(name="Loading...", value="** **", inline=True)
            embed_player.set_thumbnail(url=url[3])
            await self.send_queue_embed()
            message = await ctx.send(embed=embed_player, view=View_buttons(self, self.bot.voice_clients, ctx.guild, self.song_queue, ctx, self.queue_message, timeout=None))

            try:
                os.remove('downloaded.m4a')
            except:
                pass

            self.YT_download(url)

            await self.play_task(voice, url[2], message, url[1], url[3])

            while (len(self.song_queue) >= 1):
                self.task_done = False
                if(not self.on_repeat):
                    try:
                        os.remove('downloaded.m4a')
                    except:
                        pass

                    url = self.song_queue.pop(0)

                    if url[0] not in file.read():
                        try:
                            file.write(url[0]+"$"+url[1]+"\n")
                        except:
                            file.write(url[0]+"$"+"encoding err\n")

                    if(self.predownloaded):
                        try:
                            os.rename('predownloaded.m4a', 'downloaded.m4a')
                        except:
                            pass
                        self.predownloaded = False 
                    else:
                        self.YT_download(url)

                line = "⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛"
                embed_player = discord.Embed(title="***" + url[1] + "***", color=0x0000ff)
                embed_player.add_field(name="Loading...", value="** **", inline=True)
                embed_player.set_thumbnail(url=url[3])
                await message.edit(embed=embed_player)
                await self.send_queue_embed()

                await self.play_task(voice, url[2], message, url[1], url[3])

class View_buttons(discord.ui.View, music):
    def __init__(self, parent, voice_clients, voice_guilt, song_queue, ctx, queue_message, *args, **kwargs):
        super(View_buttons, self).__init__(*args, **kwargs)
        self.voice = discord.utils.get(voice_clients, guild=voice_guilt)
        self.song_queue = song_queue
        self.ctx = ctx
        self.queue_message = queue_message
        self.queue_for_queue = []
        self.parent = parent

    # Na začátku to hraje, tak tam je hned Pause
    @discord.ui.button(label="Pause", style=discord.ButtonStyle.green, emoji="⏸️")
    async def play_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.voice.is_playing():
            self.voice.pause()
            button.label = "Play"
            button.emoji = "▶️"
        else:
            self.voice.resume()
            button.label = "Pause"
            button.emoji = "⏸️"

        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="Stop", style=discord.ButtonStyle.danger, emoji="⏹️")
    async def stop_callback(self, interaction: discord.Interaction, button: discord.ui.button):
        self.clear_queue()
        self.voice.stop()
        await interaction.response.defer()
        await self.voice.disconnect()
        self.voice.cleanup()
        try:
            await self.ctx.channel.purge()
        except:
            pass
    @discord.ui.button(label="Next", style=discord.ButtonStyle.blurple, emoji="⏭️")
    async def next_callback(self, interaction: discord.Interaction, button: discord.ui.button):
        if (not self.song_queue):
           await interaction.response.send_message(content="Queue is empty", ephemeral=True, delete_after = 5)
           return
        self.voice.stop()
        await interaction.response.defer()
    @discord.ui.button(label="Repeat", style=discord.ButtonStyle.grey, emoji="🔂")
    async def repeat_callback(self, interaction: discord.Interaction, button: discord.ui.button):
        if (not self.parent.on_repeat):
            button.style = discord.ButtonStyle.success
            self.parent.on_repeat = True
        else:
            button.style = discord.ButtonStyle.grey
            self.parent.on_repeat = False
        
        await interaction.response.edit_message(view=self)

class View_queue_buttons(discord.ui.View, music):
    def __init__(self, parent, bot, voice_guilt, song_queue, ctx, queue_message, predownloaded, *args, **kwargs):
        super(View_queue_buttons, self).__init__(*args, **kwargs)
        self.bot = bot
        self.voice = discord.utils.get(bot.voice_clients, guild=voice_guilt)
        self.song_queue = song_queue
        self.ctx = ctx
        self.queue_message = queue_message
        self.queue_for_queue = []
        self.parent = parent

    @discord.ui.button(label="Shuffle", style=discord.ButtonStyle.grey, emoji="🔀")
    async def shuffle_callback(self, interaction: discord.Interaction, button: discord.ui.button):
        if (not self.song_queue):
           await interaction.response.send_message(content="Queue is empty", ephemeral=True, delete_after = 5)
           return
        await music.shuffle_queue(self)
        self.parent.predownloaded = False
        await interaction.response.defer()

#converts seconds to MM:SS format
def sec_min(seconds):
    return str(int(seconds/60)) + ":" + (str(seconds%60) if (seconds%60) > 9 else "0" + str(seconds%60))

async def setup(bot):
    await bot.add_cog(music(bot=bot))
    