import lelnovo

import re
import configparser
import time
import json
from datetime import datetime,timezone,timedelta

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from discord.ext import commands
import discord

class FileHandler(FileSystemEventHandler):
    def on_modified(self, event):
        global db
        if event.src_path.endswith('db.json'):
            print(f'{event.src_path} modified')
            for i in range(5):
                try:
                    db = lelnovo.get_db('db.json')
                    print('database updated:')
                    print(lelnovo.get_status(db))
                    break
                except json.decoder.JSONDecodeError:
                    print(f'JSON load error. Retrying ({i}/5)...')
                    time.sleep(1)

BOT_PREFIX = ('!lelnovo ')
CFG_FILENAME = 'config.ini'
CFG = configparser.ConfigParser()
CFG.read(CFG_FILENAME)
TOKEN = CFG['discord']['token']
bot = discord.ext.commands.Bot(command_prefix=BOT_PREFIX)

db = lelnovo.get_db('db.json')
print(lelnovo.get_status(db))

file_handler = FileHandler()
observer = Observer()
observer.schedule(file_handler, path='./db.json')

@bot.event
async def on_ready():
    print('Logged in as {0}'.format(bot.user.name))
    observer.start()

@bot.command(name='status',
    brief=lelnovo.command_briefs['status'],
    description=lelnovo.command_helps['status'],
)
async def cmd_status(context):
    embed = discord.Embed(
        title='Database Status',
    )
    embed.set_footer(text = lelnovo.get_status(db))
    await context.send(embed=embed)

@bot.command(name='listspecs',
    brief=lelnovo.command_briefs['listspecs'],
    description=lelnovo.command_helps['listspecs'],
)
async def cmd_listspecs(context):
    embed = discord.Embed(
        title='Specs List',
        description='All specs that can be used in `search` and `specs` commands\n'
    )
    contents = ''
    specs = sorted(db['keys']['info'])
    contents = '```'
    for i in range(0, len(specs), 3):
        contents += ('  '+' '.join([f'{spec:20}' for spec in specs[i:i+3]])+'\n')
    contents += '```'
    embed.add_field(name='specs', value=contents, inline=False)

    specs = sorted(db['keys']['num_specs'])
    contents = 'These specs contain numbers that can be used in a numeric `search` condition\n'
    contents += '```'
    for i in range(0, len(specs), 2):
        contents += ('  '+' '.join([f'{spec:20}' for spec in specs[i:i+2]])+'\n')
    contents += '```'
    embed.add_field(name='number specs', value=contents, inline=False)

    await context.send(embed=embed)

@bot.command(name='specs',
    brief=lelnovo.command_briefs['specs'],
    description=lelnovo.command_helps['specs'],
)
async def cmd_specs(context, *args):
    args = ' '.join(args)
    if args:
        specs = []
        words = re.split('\s+', args, 1)
        part_num = words[0]
        # user-provided specs
        if len(words) > 1: specs = [s.strip() for s in words[1].split(',')]
        res = lelnovo.get_specs(part_num, db, specs)

        if res:
            info, ret_specs = res
            if info and ret_specs:
                embed = discord.Embed(
                    title=f'Specs for {info["name"]}',
                    description=lelnovo.format_specs(db, info, ret_specs)
                )
        else:
            embed = discord.Embed(
                title=f'Specs for \'{part_num}\' not found',
                description=f'Check that the part number is valid. Discontinued products are not in database.',
            )

        embed.set_footer(text = lelnovo.get_status(db))
        await context.send(embed=embed)

@bot.command(name='search',
    brief=lelnovo.command_briefs['search'],
    description=lelnovo.command_helps['search'],
)
async def cmd_search(context, *args):
    args = ' '.join(args)
    if args:
        embed = discord.Embed(
            title = f'Search Results for \'{args}\''
        )
        count = 0
        results = lelnovo.search(args, db)
        for result in results:
            contents = ''
            prod  = result[0]
            pn    = result[1]['part number']
            price = result[1]['num_specs']['price']
            contents += (
                f'[{pn}]({db["metadata"]["base url"]}/p/{pn}) --- **{price[1]}{price[0]}**\n'
            )
            for match in result[2]:
                contents += f'`{match[0]:12} {match[1]}`\n'
            embed.add_field(
                name = result[1]['name'],
                value = contents,
                inline = False,
            )
            count += 1
            if count == 10:
                break

        summary = f'Found **{len(results)}** results for `{args}`'
        if len(results) > 10: summary += ' (only showing first 10)'
        embed.add_field(
            name = '\u200b',
            value = summary,
        )
        embed.set_footer(text = lelnovo.get_status(db))
        await context.send(embed=embed)

if __name__ == '__main__':
    bot.run(TOKEN)
