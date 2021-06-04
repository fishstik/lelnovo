from datetime import datetime,timezone,timedelta
import re

import lelnovo
import configparser
from discord.ext import commands
import discord

BOT_PREFIX = ('!lelnovo ')
CFG_FILENAME = 'config.ini'
CFG = configparser.ConfigParser()
CFG.read(CFG_FILENAME)
TOKEN = CFG['discord']['token']
bot = discord.ext.commands.Bot(command_prefix=BOT_PREFIX)

db = lelnovo.get_db('db.json')
base_url = db['metadata']['base url']

@bot.event
async def on_ready():
    print('Logged in as {0}'.format(bot.user.name))

@bot.command(
    name='status',
    brief=lelnovo.command_briefs['status'],
    description=lelnovo.command_helps['status'],
)
async def cmd_status(context):
    embed = discord.Embed(
        title='Database Status',
        description=lelnovo.get_status(db),
    )
    await context.send(embed=embed)

@bot.command(
    name='listspecs',
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

@bot.command(
    name='specs',
    brief=lelnovo.command_briefs['specs'],
    description=lelnovo.command_helps['specs'],
)
async def cmd_specs(context, *args):
    args = ' '.join(args)
    specs = []
    words = re.split('\s+', args, 1)
    part_num = words[0]
    # user-provided specs
    if len(words) > 1: specs = [s.strip() for s in words[1].split(',')]
    name, pn, ret_specs = lelnovo.get_specs(part_num, db, specs)

    if name and pn and ret_specs:
        contents = ''
        contents += (
            f'[{pn}]({base_url}/p/{pn})\n'
        )
        for spec, value in ret_specs.items():
            spacing = max([len(k) for k in ret_specs.keys()])
            if spec == 'num_specs':
                contents += f'`{spec:>{spacing}}:`\n'
                spacing = max([len(k) for k in ret_specs['num_specs'].keys()])
                for num_spec, tup in ret_specs['num_specs'].items():
                    val, unit = tup
                    contents += f'`{num_spec:>{spacing}}  {val} {unit}`\n'
            else:
                contents += f'`{spec:>{spacing}}  {value}`\n'

        embed = discord.Embed(
            title=f'Specs for {name}',
            description=contents,
        )
        embed.set_footer(text = lelnovo.get_status(db))
        await context.send(embed=embed)

@bot.command(
    name='search',
    brief=lelnovo.command_briefs['search'],
    description=lelnovo.command_helps['search'],
)
async def cmd_search(context, *args):
    args = ' '.join(args)
    embed = discord.Embed(
        title = f'Search Results for \'{args}\''
    )
    count = 0
    results = lelnovo.search(args, db)
    for result in results:
        contents = ''
        prod = result[0]
        pn   = result[1]['part number']
        contents += (
            #f'[{prod}]({base_url}/p/{prod}) **->** [{pn}]({base_url}/p/{pn})\n'
            f'[{pn}]({base_url}/p/{pn})\n'
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
