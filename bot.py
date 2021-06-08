import lelnovo

import re
import configparser
import json, time
import os, sys
import atexit
#from datetime import datetime,timezone,timedelta

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from discord.ext import commands
import discord

def exit():
    print('Exiting...')
atexit.register(exit)

CFG_FILENAME = 'config.ini'
DB_DIR = './dbs'
BOT_PREFIX = ('!lelnovo ')
EMBED_COLOR = 0xe41c1c
DISABLED_REGIONS = {
    851248442864173057: ['tck'], # lbt2
    361360173530480640: ['tck'], # SAL
}

CMD_ALIASES = {
    'h': 'help',
    'lr': 'listregions',
    'st': 'status',
}
REGCMD_ALIASES = {
    'st': 'status',
    'ls': 'listspecs',
    's':  'search',
    'sp': 'specs',
}

class FileHandler(FileSystemEventHandler):
    def on_modified(self, event):
        global dbs
        if event.src_path.endswith('.json'):
            print(f'{event.src_path} modified')
            for i in range(5):
                try:
                    dbs = lelnovo.get_dbs(DB_DIR)
                    print('\n'.join([lelnovo.get_footer(db) for db in dbs.values()]))
                    break
                except json.decoder.JSONDecodeError:
                    print(f'JSON load error. Retrying ({i+1}/5)...')
                    time.sleep(1)

bot = discord.ext.commands.Bot(
    command_prefix=BOT_PREFIX,
    help_command=None
)

#dbs = {
#    short_region : db,
#}
dbs = {}

@bot.event
async def on_ready():
    global dbs
    print('Logged in as {0}'.format(bot.user.name))

    file_handler = FileHandler()
    observer = Observer()
    observer.schedule(file_handler, path=DB_DIR)
    observer.start()
    print(f'Monitoring \'{DB_DIR}\'')

    dbs = lelnovo.get_dbs(DB_DIR)

    print('\n'.join([lelnovo.get_footer(db) for db in dbs.values()]))

async def try_send(context, content=None, embed=None):
    try:
        await context.send(content=content, embed=embed)
    except discord.errors.Forbidden:
        print(f'No permission to send to server \'{context.guild}\': \'#{context.channel}\'')

# need to add command for every region
@bot.command()
async def tck(context, *args):
    embed = parse_command(context, args, region='tck')
    if embed: await try_send(context, embed=embed)

@bot.command()
async def us(context, *args):
    embed = parse_command(context, args, region='us')
    if embed: await try_send(context, embed=embed)

@bot.command()
async def gb(context, *args):
    embed = parse_command(context, args, region='gb')
    if embed: await try_send(context, embed=embed)

def parse_command(context, args, region):
    guild_id = context.guild.id
    embed = None

    if guild_id in DISABLED_REGIONS and region in DISABLED_REGIONS[guild_id]:
        print(f'Guild \'{context.guild}\' got disabled region command \'{region}\'. Ignoring...')
    else:
        command = args[0]
        params = args[1:]

        db = dbs[region]
        region_emoji = lelnovo.get_region_emoji(db['metadata']['short region'])

        if command in ['status', 'st']:
            embed = discord.Embed(
                title='Database Status',
                description=lelnovo.get_status(db),
                color=EMBED_COLOR,
            )
            embed.set_footer(text = lelnovo.get_footer(db))
        elif command in ['listspecs', 'ls']:
            embed = discord.Embed(
                title=f'{region_emoji} Specs List',
                description='All specs that can be used in `search` and `specs` commands\n',
                color=EMBED_COLOR,
            )
            specs = sorted(db['keys']['info'])
            # convert {'alias': 'spec'} to {'spec': ['alias', ...]}
            spec_aliases = {}
            for k, v in dict(sorted(lelnovo.SPEC_ALIASES.items())).items():
                if v in spec_aliases: spec_aliases[v].append(k)
                else:                 spec_aliases[v] = [k]
            # add aliases to spec
            for i in range(len(specs)):
                if specs[i] in spec_aliases:
                    specs[i] = '|'.join([specs[i]] + spec_aliases[specs[i]])
            contents = '```'
            for i in range(0, len(specs), 3):
                contents += (' '.join([f'{spec:20}' for spec in specs[i:i+3]])+'\n')
            contents += '```'
            embed.add_field(name='specs', value=contents, inline=False)

            specs = sorted(db['keys']['num_specs'])
            # convert {'alias': 'spec'} to {'spec': ['alias', ...]}
            spec_aliases = {}
            for k, v in dict(sorted(lelnovo.NUM_SPEC_ALIASES.items())).items():
                if v in spec_aliases: spec_aliases[v].append(k)
                else:                 spec_aliases[v] = [k]
            # add aliases to spec
            for i in range(len(specs)):
                if specs[i] in spec_aliases:
                    specs[i] = '|'.join([specs[i]] + spec_aliases[specs[i]])
            contents = 'These specs contain numbers that can be used in a numeric `search` condition\n'
            contents += '```'
            for i in range(0, len(specs), 2):
                contents += (' '.join([f'{spec:26}' for spec in specs[i:i+2]])+'\n')
            contents += '```'
            embed.add_field(name='number specs', value=contents, inline=False)

            embed.set_footer(text = lelnovo.get_footer(db))
        elif command in ['search', 's']:
            params = ' '.join(params)
            if params:
                count = 0

                results, error = lelnovo.search(params, db)
                if error:
                    embed = discord.Embed(
                        title = f'{region_emoji} Search Failed',
                        description = f'Invalid query `{params}` (check commas!)',
                        color=EMBED_COLOR,
                    )
                else:
                    embed = discord.Embed(
                        title = f'{region_emoji} Search Results for \'{params}\'',
                        color=EMBED_COLOR,
                    )
                    for result in results:
                        prod   = result[0]
                        pn     = result[1]['part number']
                        price  = result[1]['num_specs']['price']
                        status = result[1]['status']
                        spec_matches = result[2]

                        contents = f'{pn} ([link]({db["metadata"]["base url"]}/p/{pn}))'

                        price_str = f'{price[1]}{price[0]:.2f}'
                        if status.lower() == 'unavailable':
                            contents += f' **~~{price_str}~~ (unavailable)**\n'
                        elif status.lower() == 'customize':
                            contents += f' **{price_str} (customize)**\n'
                        else:
                            contents += f' **{price_str}**\n'

                        added = [] # keep track of added spec matches to avoid duplicates
                        spacing = max([len(k[0]) for k in spec_matches])
                        for match in result[2]:
                            if match[0] not in added:
                                contents += lelnovo.multiline(f'{match[0]:{spacing}}  {match[1]}', indent=spacing+2) + '\n'
                                added.append(match[0])
                        embed.add_field(
                            name = result[1]['name'],
                            value = contents,
                            inline = False,
                        )
                        count += 1
                        if count == 10:
                            break

                    summary = f'Found **{len(results)}** results for `{params}`'
                    if len(results) > 10: summary += ' (only showing first 10)'
                    embed.add_field(
                        name = '\u200b',
                        value = summary,
                    )
                embed.set_footer(text = lelnovo.get_footer(db))
        elif command in ['specs', 'sp']:
            params = ' '.join(params)
            if params:
                specs = []
                words = re.split('\s+', params, 1)
                part_num = words[0]
                # user-provided specs
                if len(words) > 1: specs = [s.strip() for s in words[1].split(',')]

                info, ret_specs = lelnovo.get_specs(part_num, db, specs)
                # Found part
                if info:
                    embed = discord.Embed(
                        title=f'{region_emoji} Specs for {info["name"]}',
                        description=lelnovo.format_specs(db, info, ret_specs)[:2048],
                        color=EMBED_COLOR,
                    )
                else:
                    embed = discord.Embed(
                        title=f'{region_emoji} Specs for \'{part_num}\' not found',
                        description=f'Check that the part number is valid. Discontinued or upcoming products are not in database.',
                        color=EMBED_COLOR,
                    )

                embed.set_footer(text = lelnovo.get_footer(db))
        else:
            print(f'Unrecognized command \'{" ".join(args)}\'')

    return embed

@bot.command(name='help',
    aliases = ['h'],
)
async def cmd_help(context, *args):
    arg = ' '.join(args)
    # searching in non-region commands first
    # so conflicting name in region commands are inaccessible
    if arg == 'help':
        msg = 'haha nice try'
    elif arg in CMD_ALIASES.values():
        msg = ''.join(lelnovo.COMMAND_DESCRS[arg])
    elif arg in CMD_ALIASES.keys():
        msg = ''.join(lelnovo.COMMAND_DESCRS[CMD_ALIASES[arg]])
    elif arg in REGCMD_ALIASES.values():
        msg = ''.join(lelnovo.COMMAND_DESCRS[f'reg_{arg}'])
    elif arg in REGCMD_ALIASES.keys():
        msg = ''.join(lelnovo.COMMAND_DESCRS[f'reg_{REGCMD_ALIASES[arg]}'])
    else:
        msg = lelnovo.USAGE_STR

    await try_send(context, content=f'```\n{msg}```')

@bot.command(name='listregions',
    aliases     = ['lr'],
    brief       = lelnovo.COMMAND_BRIEFS['listregions'],
    description = lelnovo.COMMAND_DESCRS['listregions'],
)
async def cmd_listregions(context):
    guild_id = context.guild.id

    contents = ''
    for _, db in dbs.items():
        region = db['metadata']['region']
        region_short = db['metadata']['short region']

        if not (guild_id in DISABLED_REGIONS and region_short in DISABLED_REGIONS[guild_id]):
            contents += f'`{region_short:3}` {lelnovo.get_region_emoji(region_short)}'
            contents += f' [{region}]({db["metadata"]["base url"]})'
            contents += '\n'

    embed = discord.Embed(
        title='Region List',
        description=contents,
        color=EMBED_COLOR,
    )
    await try_send(context, embed=embed)

@bot.command(name='status',
    aliases=['st'],
    brief='display status for all available databases',
    description='display status for all available databases',
)
async def cmd_status(context):
    guild_id = context.guild.id

    embed = discord.Embed(
        title='All Database Statuses',
        color=EMBED_COLOR,
    )
    for k, db in dbs.items():
        region = db['metadata']['short region']
        if not (guild_id in DISABLED_REGIONS and region in DISABLED_REGIONS[guild_id]):
            contents = ''
            contents += lelnovo.get_status(db)

            footer = lelnovo.get_footer(db)
            # remove divider line
            footer = '\n'.join(footer.split('\n')[1:])
            contents += f'{footer}\n'

            embed.add_field(name=db['metadata']['short region'], value=contents, inline=False)

    await try_send(context, embed=embed)

@bot.event
async def on_command_error(context, error):
    if isinstance(error, discord.ext.commands.CommandNotFound):
        print(f'Ignoring invalid command \'{context.invoked_with}\'')
        return
    raise error

if __name__ == '__main__':
    cfg = configparser.ConfigParser()
    if not os.path.exists(CFG_FILENAME):
        cfg.add_section('discord')
        cfg.set('discord', 'token', '')
        with open(CFG_FILENAME, 'w') as cfg_file: cfg.write(cfg_file)
        print(f'Created template \'{CFG_FILENAME}\'. Add bot token and restart.')
        sys.exit()

    cfg.read(CFG_FILENAME)
    token = cfg['discord']['token']
    if token: bot.run(token)
    else:     print(f'Token not found in \'{CFG_FILENAME}\'')
