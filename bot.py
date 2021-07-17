import lelnovo

import re
import configparser
import json, time
import os
import atexit
import sys
from datetime import datetime

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

import discord
from discord.ext import commands
from disputils import BotEmbedPaginator

def exit():
    print('Exiting...')
atexit.register(exit)

CFG_FILENAME = 'config.ini'

CFG = configparser.ConfigParser()
if os.path.exists(CFG_FILENAME):
    CFG.read(CFG_FILENAME)
else:
    CFG.add_section('bot')
    CFG.set('bot', 'discord_token', '')
    CFG.set('bot', 'prefix', '!lenovo, !ln')
    CFG.set('bot', 'embed_color', 'e41c1c')
    CFG.set('bot', 'db_dir', '')
    CFG.set('bot', 'backup_dir', '')
    with open(CFG_FILENAME, 'w') as cfg_file: CFG.write(cfg_file)
    sys.exit(f'Created template \'{CFG_FILENAME}\'. Add bot token and restart.')

DB_DIR = CFG['bot']['db_dir']
BACKUP_DIR = CFG['bot']['backup_dir']
BOT_PREFIXES = []
for prefix in CFG['bot']['prefixes'].split(','):
    BOT_PREFIXES.append(prefix.strip())
EMBED_COLOR = int(CFG['bot']['embed_color'], 16)
# TODO: move to config
DISABLED_REGIONS = {
    #851248442864173057: ['tck'], # lbt2
    361360173530480640: ['tck', 'epp', 'gbepp'], # SAL
}

CMD_ALIASES = {
    'h': 'help',
    'lr': 'listregions',
    'st': 'status',
    'sr': 'setregion',
}
REGCMD_ALIASES = {
    'st': 'status',
    'ls': 'listspecs',
    'ch': 'changes',
    's':  'search',
    'sp': 'specs',
    'hi': 'history',
}

BOT = discord.ext.commands.Bot(
    command_prefix=[f'{p} ' for p in BOT_PREFIXES],
    help_command=None
)

DBS = {} #{ short_region: db, ... }

class FileHandler(FileSystemEventHandler):
    def on_modified(self, event):
        global DBS
        if event.src_path.endswith('.json'):
            print(f'{event.src_path} modified')
            for i in range(5):
                try:
                    DBS = lelnovo.get_dbs(DB_DIR)
                    print('\n'.join([lelnovo.get_footer(db) for db in DBS.values()]))
                    break
                except json.decoder.JSONDecodeError:
                    print(f'JSON load error. Retrying ({i+1}/5)...')
                    time.sleep(1)

### start command for every region ###

@BOT.command()
async def us(context, *args):
    embed, attach = parse_command(context, args, region='us')
    if embed:
        if attach: await try_send(context, embed=embed, file=attach)
        else:      await try_send_paginated(context, embed)

@BOT.command()
async def tck(context, *args):
    embed, attach = parse_command(context, args, region='tck')
    if embed:
        if attach: await try_send(context, embed=embed, file=attach)
        else:      await try_send_paginated(context, embed)

@BOT.command()
async def ca(context, *args):
    embed, attach = parse_command(context, args, region='ca')
    if embed:
        if attach: await try_send(context, embed=embed, file=attach)
        else:      await try_send_paginated(context, embed)

@BOT.command()
async def epp(context, *args):
    embed, attach = parse_command(context, args, region='epp')
    if embed:
        if attach: await try_send(context, embed=embed, file=attach)
        else:      await try_send_paginated(context, embed)

@BOT.command()
async def gb(context, *args):
    embed, attach = parse_command(context, args, region='gb')
    if embed:
        if attach: await try_send(context, embed=embed, file=attach)
        else:      await try_send_paginated(context, embed)

@BOT.command()
async def gbepp(context, *args):
    embed, attach = parse_command(context, args, region='gbepp')
    if embed:
        if attach: await try_send(context, embed=embed, file=attach)
        else:      await try_send_paginated(context, embed)

### end region commands ###

@BOT.command(name='help',
    aliases = ['h'],
)
async def cmd_help(context, *args):
    arg = ' '.join(args)
    # searching in non-region commands first
    # so conflicting name in region commands are inaccessible
    if arg in ['h', CMD_ALIASES['h']]:
        msg = 'haha nice try'
    elif arg in CMD_ALIASES.values():
        msg = ''.join(lelnovo.get_command_descr(arg, BOT_PREFIXES[0]))
    elif arg in CMD_ALIASES.keys():
        msg = ''.join(lelnovo.get_command_descr(CMD_ALIASES[arg], BOT_PREFIXES[0]))
    elif arg in REGCMD_ALIASES.values():
        msg = ''.join(lelnovo.get_command_descr(f'reg_{arg}', BOT_PREFIXES[0]))
    elif arg in REGCMD_ALIASES.keys():
        msg = ''.join(lelnovo.get_command_descr(f'reg_{REGCMD_ALIASES[arg]}', BOT_PREFIXES[0]))
    else:
        msg = lelnovo.get_usage_str(BOT_PREFIXES)

    await try_send(context, content=f'```\n{msg}```')

@BOT.command(name='listregions',
    aliases     = ['lr'],
    brief       = lelnovo.COMMAND_BRIEFS['listregions'],
    description = lelnovo.get_command_descr('listregions', BOT_PREFIXES[0]),
)
async def cmd_listregions(context):
    embed = discord.Embed(
        title='Region List',
        description=format_regions(context.guild.id),
        color=EMBED_COLOR,
    )
    await try_send(context, embed=embed)

@BOT.command(name='status',
    aliases=['st'],
)
async def cmd_status(context):
    guild_id = context.guild.id

    embed = discord.Embed(
        title='All Database Statuses',
        color=EMBED_COLOR,
    )
    for k, db in DBS.items():
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

@BOT.command(name='setregion',
    aliases=['sr'],
)
async def cmd_setregion(context, *args):
    arg = ' '.join(args).strip().lower()
    id = str(context.author.id)

    if arg == '':
        if 'user regions' in CFG and id in CFG['user regions']:
            reg = CFG['user regions'][id]
            content = f'{context.author.mention} using region `{reg}`{lelnovo.REGION_EMOJIS[reg]}'
        else:
            content = f'No region set for {context.author.mention}'
    elif arg in lelnovo.REGION_EMOJIS:
        if 'user regions' not in CFG: CFG.add_section('user regions')
        CFG.set('user regions', id, arg)
        with open(CFG_FILENAME, 'w') as cfg_file: CFG.write(cfg_file)
        content = f'Saved region `{arg}`{lelnovo.REGION_EMOJIS[arg]} for {context.author.mention}'
    elif arg in ['clear', 'cl']:
        if 'user regions' in CFG and id in CFG['user regions']:
            CFG.remove_option('user regions', id)
            with open(CFG_FILENAME, 'w') as cfg_file: CFG.write(cfg_file)
            content = f'Cleared region for {context.author.mention}'
        else:
            content = f'No region set for {context.author.mention}'
    else:
        content = f'Invalid region `{arg}`. Use `{BOT_PREFIXES[0]} listregions` to view valid regions'

    embed = discord.Embed(
        title='User Region',
        description=content,
        color=EMBED_COLOR,
    )
    await try_send(context, embed=embed)

@BOT.event
async def on_ready():
    global DBS
    print('Logged in as {0}'.format(BOT.user.name))
    await BOT.change_presence(activity=discord.Game(f'{BOT_PREFIXES[0]} help'))

    file_handler = FileHandler()
    observer = Observer()
    observer.schedule(file_handler, path=DB_DIR)
    observer.start()
    print(f'Monitoring \'{DB_DIR}\'')

    DBS = lelnovo.get_dbs(DB_DIR)

    print('\n'.join([lelnovo.get_footer(db) for db in DBS.values()]))

# also handles region-less commands with saved user region
@BOT.event
async def on_command_error(context, error):
    if isinstance(error, discord.ext.commands.CommandNotFound):
        cmd = context.invoked_with

        if cmd in REGCMD_ALIASES: cmd = REGCMD_ALIASES[cmd]
        if cmd in REGCMD_ALIASES.values():
            attach = None
            # parse region-less region command with saved user region
            if 'user regions' in CFG and str(context.author.id) in CFG['user regions']:
                args = [] if len(context.message.content.split(' ')) <= 2 else context.message.content.split(' ')[2:]
                embed, attach = parse_command(context, [cmd]+args, CFG['user regions'][str(context.author.id)])
            else:
                embed = discord.Embed(
                    title=f'No region specified for command `{cmd}`',
                    description = (
                        f'`usage: {BOT_PREFIXES[0]} [region] [command] [parameters, ...]`\n'
                        f'`       {BOT_PREFIXES[0]} setregion [region]`\n'
                    ),
                    color=EMBED_COLOR,
                )
                embed.add_field(
                    name='Available regions',
                    value=format_regions(context.guild.id),
                    inline=False,
                )
            if attach: await try_send(context, embed=embed, file=attach)
            else:      await try_send_paginated(context, embed)
        else:
            print(f'Ignoring invalid command \'{cmd}\'')
    else: raise error

async def try_send(context, content=None, embed=None, file=None):
    try:
        await context.send(content=content, embed=embed, file=file)
    except discord.errors.Forbidden:
        print(f'No permission to send to server \'{context.guild}\': \'#{context.channel}\'')

async def try_send_paginated(context, embed, attach=None, limit=2048):
    msg = context.message.content

    embeds_splitdescr = []
    descr = ''
    if len(embed.description) > limit:
        for line in embed.description.split('\n'):
            if len(descr+f'{line}\n') <= limit:
                descr += f'{line}\n'
            else:
                embed_page = discord.Embed(
                    title=embed.title,
                    description=descr,
                    color=embed.colour,
                )
                embed_page.set_footer(text=embed.footer.text)
                embeds_splitdescr.append(embed_page)
                descr = f'{line}\n'
        if descr:
            embed_page = discord.Embed(
                title=embed.title,
                description=descr,
                color=embed.colour,
            )
            embed_page.set_footer(text=embed.footer.text)
            embeds_splitdescr.append(embed_page)
    else:
        embeds_splitdescr.append(embed)

    # display search results summary on every page
    is_search = False
    if embed.fields and (msg.split()[1] in ['s', REGCMD_ALIASES['s']] or (len(msg.split()) >= 3 and msg.split()[2] in ['s', REGCMD_ALIASES['s']])):
        is_search = True
        summary_field = embed.fields[-1]
        embed.remove_field(-1)

    embeds = []
    for embed in embeds_splitdescr:
        if embed.fields and len(embed) > 3000:
            embed_page = discord.Embed(
                title=embed.title,
                description=embed.description,
                color=embed.colour,
            )
            embed_page.set_footer(text=embed.footer.text)
            for i in range(len(embed.fields)):
                field = embed.fields[i]
                #if len(embed_page)+len(field.name+field.value) < 3000:
                if i == 0 or i % 10 != 0:
                    embed_page.add_field(name=field.name, value=field.value, inline=field.inline)
                else:
                    if is_search: embed_page.add_field(
                        name = summary_field.name,
                        value = f'{summary_field.value} (showing **{i+1-len(embed_page.fields)}**-**{i}**)',
                        inline = summary_field.inline,
                    )
                    embeds.append(embed_page)
                    embed_page = discord.Embed(
                        title=embed.title,
                        description=embed.description,
                        color=embed.colour,
                    )
                    embed_page.set_footer(text=embed.footer.text)
                    embed_page.add_field(name=field.name, value=field.value, inline=field.inline)
            if embed_page.fields:
                i += 1
                if is_search: embed_page.add_field(
                    name = summary_field.name,
                    value = f'{summary_field.value} (showing **{i+1-len(embed_page.fields)}**-**{i}**)',
                    inline = summary_field.inline,
                )
                embeds.append(embed_page)
        else:
            if is_search: embed.add_field(name=summary_field.name, value=summary_field.value, inline=summary_field.inline)
            embeds.append(embed)

    paginator = BotEmbedPaginator(context, embeds, control_emojis=['⏮', '◀', '▶', '⏭', None])
    try:
        await paginator.run()
    except discord.errors.Forbidden:
        print(f'No permission to send to server \'{context.guild}\': \'#{context.channel}\'')

def format_regions(guild_id):
    contents = ''
    for _, db in DBS.items():
        region = db['metadata']['region']
        region_short = db['metadata']['short region']

        if not (guild_id in DISABLED_REGIONS and region_short in DISABLED_REGIONS[guild_id]):
            contents += f'`{region_short:3}` {lelnovo.get_region_emoji(region_short)}'
            contents += f' [{region}]({db["metadata"]["base url"]})'
            contents += '\n'
    return contents

def parse_command(context, args, region):
    guild_id = context.guild.id
    embed = None
    attach = None

    if guild_id in DISABLED_REGIONS and region in DISABLED_REGIONS[guild_id]:
        print(f'Guild \'{context.guild}\' got disabled region command \'{region}\'. Ignoring...')
    else:
        command = args[0]
        params = args[1:]

        db = DBS[region]
        region_emoji = lelnovo.get_region_emoji(db['metadata']['short region'])

        if command in ['st', REGCMD_ALIASES['st']]:
            embed = discord.Embed(
                title='Database Status',
                description=lelnovo.get_status(db),
                color=EMBED_COLOR,
            )
            embed.set_footer(text = lelnovo.get_footer(db))
        elif command in ['ls', REGCMD_ALIASES['ls']]:
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
        elif command in ['ch', REGCMD_ALIASES['ch']]:
            if db['changes']:
                change_contents = lelnovo.format_changes(db['changes'], db['metadata']['base url'])
                contents = ''
                for k, v in change_contents.items():
                    cutoff_msg = f'*...and xx more. use* `changes {k}` *to view all*'
                    if k in ['added', 'removed'] and v:
                        #contents = ''
                        contents += f'\n**{k.capitalize()}**\n'
                        count = 0
                        for prod, parts in v.items():
                            new_contents = f'{prod}\n'
                            #if len(contents+new_contents)+len('\n'.join(parts)) < 1024-len(cutoff_msg):
                            contents += new_contents
                            contents += '\n'.join(parts)
                            if parts: contents += '\n'
                            count += 1
                            #else:
                            #    contents += cutoff_msg.replace('xx', f'{len(v)-count:2}')
                            #    break
                        #embed.add_field(name=k.capitalize(), value=contents, inline=False)
                    if k == 'changed' and v:
                        #contents = ''
                        contents += f'\n**Price Changed**\n'
                        for i in range(len(v)):
                            new_contents = f'{v[i]}\n'
                            #if len(contents+new_contents) < 1024-len(cutoff_msg):
                            contents += new_contents
                            #else:
                            #    contents += cutoff_msg.replace('xx', f'{len(v)-i:2}')
                            #    break
                        #embed.add_field(name=k.capitalize(), value=contents, inline=False)

                old_dt = datetime.utcfromtimestamp(db['changes']['timestamp_old'])
                embed = discord.Embed(
                    title=f'{region_emoji} Changes since {old_dt.strftime("%a %b %d")} ({lelnovo.pretty_duration((datetime.utcnow() - old_dt).total_seconds())} ago)',
                    description=contents,
                    color=EMBED_COLOR,
                )
            else:
                embed = discord.Embed(
                    title=f'{region_emoji} No changes to show',
                    color=EMBED_COLOR,
                )
            embed.set_footer(text = lelnovo.get_footer(db))
        elif command in ['s', REGCMD_ALIASES['s']]:
            params = ' '.join(params).strip(',')
            if params:
                summary = ''

                results, error = lelnovo.search(params, db)
                if error:
                    embed = discord.Embed(
                        title = f'{region_emoji} Search Failed',
                        description = f'Invalid query `{params}` (check commas!)',
                        color=EMBED_COLOR,
                    )
                elif not results:
                    embed = discord.Embed(
                        title = f'{region_emoji} No search results for `{params}`',
                        color=EMBED_COLOR,
                    )
                else:
                    embed = discord.Embed(
                        title = f'{region_emoji} Search Results for `{params}`',
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
                            contents += f' **~~{price_str}~~ (unavailable)**'
                        elif status.lower() == 'customize':
                            contents += f' **{price_str} (customize)**'
                        else:
                            contents += f' **{price_str}**'

                        contents += f'\n {lelnovo.part_listentry(result[1], show_pn=False, show_price=False, fmt="*")}\n'

                        added = [] # keep track of added spec matches to avoid duplicates
                        spacing = max([len(k[0]) for k in spec_matches])
                        for match in result[2]:
                            if match[0] not in added:
                                spec, value = match
                                if spec == 'processor': value = lelnovo.cleanup_cpu(value)
                                contents += lelnovo.multiline(f'{spec:{spacing}}  {value}', indent=spacing+2) + '\n'
                                added.append(spec)
                        embed.add_field(
                            name = result[1]['name'],
                            value = contents,
                            inline = False,
                        )

                    summary = f'Found **{len(results)}** result{"s" if len(results)!=1 else ""} for `{params}`'
                    embed.add_field(
                        name = '\u200b',
                        value = summary,
                    )
                embed.set_footer(text = lelnovo.get_footer(db))
        elif command in ['sp', REGCMD_ALIASES['sp']]:
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
                        description=lelnovo.format_specs(db, info, ret_specs),
                        color=EMBED_COLOR,
                    )
                else:
                    embed = discord.Embed(
                        title=f'{region_emoji} Specs for `{part_num}` not found',
                        description=f'Check that the part number is valid. Discontinued or upcoming products are not in database.',
                        color=EMBED_COLOR,
                    )

                embed.set_footer(text = lelnovo.get_footer(db))
        elif command in ['hi', REGCMD_ALIASES['hi']]:
            if params:
                pn = ''.join(params)
                # collect backup dbs for region
                dbs = [db]
                for f in os.scandir(BACKUP_DIR):
                    if f.name.startswith(f'db_{region}_') and f.name.endswith('.json'):
                        with open(f.path, 'r') as f:
                            js = f.read()
                            dbs.append(json.loads(js))
                dbs = sorted(dbs, key=lambda db: db['metadata']['timestamp'])

                data, part = lelnovo.get_history(pn, dbs)
                if part:
                    bytes = lelnovo.plot_history(data, part)
                    bytes.seek(0)
                    attach = discord.File(bytes, filename='plot.png')

                    embed = discord.Embed(
                        title=f'{region_emoji} Price history for {part["name"]}',
                        description=lelnovo.part_listentry(part, db['metadata']['base url']),
                        color=EMBED_COLOR,
                    )
                    embed.set_image(url='attachment://plot.png')
                else:
                    embed = discord.Embed(
                        title=f'{region_emoji} Price history for `{pn}` not found',
                        description=f'Check that the part number is valid. Discontinued or upcoming products are not in database.',
                        color=EMBED_COLOR,
                    )
                embed.set_footer(text = lelnovo.get_footer(db))

    return embed, attach

if __name__ == '__main__':
    token = CFG['bot']['discord_token']
    if token: BOT.run(token)
    else:     sys.exit(f'Token not found in \'{CFG_FILENAME}\'')
