import lelnovo

import re
import configparser
import time
import json
import os, sys
import atexit
from datetime import datetime,timezone,timedelta

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from discord.ext import commands
import discord

def exit():
    print('Exiting...')
atexit.register(exit)

class FileHandler(FileSystemEventHandler):
    def on_modified(self, event):
        global db
        if event.src_path.endswith(DB_FILENAME):
            print(f'{event.src_path} modified')
            for i in range(5):
                try:
                    db = lelnovo.get_db(DB_FILENAME)
                    print('database updated:')
                    print(lelnovo.get_footer(db))
                    break
                except json.decoder.JSONDecodeError:
                    print(f'JSON load error. Retrying ({i}/5)...')
                    time.sleep(1)

CFG_FILENAME = 'config.ini'
DB_FILENAME = 'db.json'

BOT_PREFIX = ('!lelnovo ')
bot = discord.ext.commands.Bot(command_prefix=BOT_PREFIX)

db = {}

@bot.event
async def on_ready():
    global db
    print('Logged in as {0}'.format(bot.user.name))

    file_handler = FileHandler()
    observer = Observer()
    observer.schedule(file_handler, path=f'./{DB_FILENAME}')
    observer.start()
    print(f'Monitoring \'{DB_FILENAME}\'')

    db = lelnovo.get_db(DB_FILENAME)
    print(lelnovo.get_footer(db))

@bot.command(name='status',
    brief=lelnovo.command_briefs['status'],
    description=lelnovo.command_helps['status'],
)
async def cmd_status(context):
    embed = discord.Embed(
        title='Database Status',
        description=lelnovo.get_status(db),
    )
    embed.set_footer(text = lelnovo.get_footer(db))
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

        embed.set_footer(text = lelnovo.get_footer(db))
        await context.send(embed=embed)

@bot.command(name='search',
    brief=lelnovo.command_briefs['search'],
    description=lelnovo.command_helps['search'],
)
async def cmd_search(context, *args):
    args = ' '.join(args)
    if args:
        count = 0
        results, error = lelnovo.search(args, db)
        if error:
            embed = discord.Embed(
                title = f'Search Failed',
                description = f'Invalid query `{args}` (check commas!)',
            )
        else:
            embed = discord.Embed(
                title = f'Search Results for \'{args}\'',
            )
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
        embed.set_footer(text = lelnovo.get_footer(db))
        await context.send(embed=embed)

if __name__ == '__main__':
    cfg = configparser.ConfigParser()
    cfg.read(CFG_FILENAME)
    if not os.path.exists(CFG_FILENAME):
        cfg.add_section('discord')
        cfg.set('discord', 'token', '')
        with open(CFG_FILENAME, 'w') as cfg_file: cfg.write(cfg_file)
        print(f'Created template \'{CFG_FILENAME}\'. Add bot token and restart.')
        sys.exit()

    token = cfg['discord']['token']
    if token: bot.run(token)
    else:     print(f'Token not found in \'{CFG_FILENAME}\'')
