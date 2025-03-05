import discord
from discord.ext import commands
import json

class Bot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix="!",
            intents=discord.Intents.all()
        )
    
    #module loading
    async def setup_hook(self):
        await self.load_extension("music_cog")
        await self.load_extension("cmds_cog")
        await self.load_extension("event_cog")
        
f = open('settings.json')
settings = json.load(f)
token = settings["token"]
Bot().run(token)
