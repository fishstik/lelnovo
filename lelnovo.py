import argparse
import json
import time
import sys
import re
import operator
import math
import textwrap
import os
from datetime import datetime,timezone,timedelta
from pprint import pprint

def pretty_duration(time_diff_secs):
    weeks_per_month = 365.242 / 12 / 7
    intervals = [('minute', 60), ('hour', 60), ('day', 24), ('week', 7),
                 ('month', weeks_per_month), ('year', 12)]

    unit, number = 'second', abs(time_diff_secs)
    for new_unit, ratio in intervals:
        new_number = float(number) / ratio
        # If the new number is too small, don't go to the next unit.
        if new_number < 1:
            break
        unit, number = new_unit, new_number
    shown_num = int(number)
    return '{} {}'.format(shown_num, unit + ('' if shown_num == 1 else 's'))

#results = [
#    ( 'prod_num',
#      part_db,
#      matches = [
#          ('spec', value),
#          ...
#      ]
#    ),
#    ...
#]
def search(query, db):
    error = False
    ops = {
        '<':  operator.lt,
        '<=': operator.le,
        '=':  operator.eq,
        '==': operator.eq,
        '>=': operator.ge,
        '>':  operator.gt,
        '!=': operator.ne,
    }
    # parse query
    #qs = [
    #    ('search', term),
    #    ('spec', spec, term),
    #    ('num_spec', spec, term),
    #    ...
    #]
    qs = []
    for term in query.split(','):
        term = term.strip()
        m = re.match(r'(.*?):(.*)', term) # spec:'string' search
        if m:
            spec   = m.group(1).strip()
            search = m.group(2).strip()

            if str(spec).lower() in [k.lower() for k in db['keys']['info']] + ['product']:
                qs.append(('spec', spec, search))
            elif str(spec).lower() in SPEC_ALIASES:
                qs.append(('spec', SPEC_ALIASES[spec], search))
            else:
                print(f'Ignoring unhandled spec \'{spec}\' in \'{term}\'')
        else:
            m = re.match(r'\s?([\w ]+)([=<>]+)\s?(.*)', term) # num_spec comparison search
            if m:
                spec =   m.group(1).strip()
                op_str = m.group(2).strip()
                num    = m.group(3).strip()
                if op_str in ops:
                    if spec in db['keys']['num_specs']:
                        qs.append(('num_spec', spec, ops[op_str], num))
                    elif spec in NUM_SPEC_ALIASES and NUM_SPEC_ALIASES[spec] in db['keys']['num_specs']:
                        qs.append(('num_spec', NUM_SPEC_ALIASES[spec], ops[op_str], num))
                    else:
                        print(f'Ignoring unhandled num_spec \'{spec}\' in \'{term}\'')
                else:
                    print(f'Ignoring unhandled num_spec operator \'{m.group(2)}\' in \'{term}\'')
            else: # generic value search
                qs.append(('search', term))
    #pprint(qs)
    results = []
    if qs:
        for brand, prods in db['data'].items():
            for prod, parts in prods.items():
                for part in parts:
                    matches = []
                    qs_matched = [False]*len(qs)
                    search_matched = False
                    for i in range(len(qs)):
                        q = qs[i]
                        if q[0] == 'search':
                            term = q[1]
                            # product line search (special case since product line not in part dictionary)
                            if term.lower() in prod.lower():
                                matches.append(('product line', prod))
                                qs_matched[i] = True
                            # generic search
                            for k, v in part.items():
                                # dont search summary
                                if k != 'summary' and type(v) == str and term.lower() in v.lower():
                                    matches.append((k, v))
                                    qs_matched[i] = True
                        elif q[0] == 'spec':
                            spec = q[1]
                            term = q[2]
                            # product line search (special case since product line not in part dictionary)
                            if spec == 'product':
                                if term.lower() in prod.lower():
                                    matches.append(('product line', prod))
                                    qs_matched[i] = True
                            # spec search
                            else:
                                if spec in part and term.lower() in part[spec].lower():
                                    matches.append((spec, part[spec]))
                                    qs_matched[i] = True
                        elif q[0] == 'num_spec':
                            num_spec = q[1]
                            op       = q[2]
                            num      = q[3]
                            if num_spec in part['num_specs'] and (num == '' or op(part['num_specs'][num_spec][0], float(num))):
                                matches.append((num_spec, f'{part["num_specs"][num_spec][0]} {part["num_specs"][num_spec][1]}'))
                                qs_matched[i] = True

                    # if all queries matched, add to result list
                    if qs_matched.count(True) == len(qs):
                        results.append((prod, part, matches))
    else: error = True

    return results, error

# returns (None, None) if part_num not found
#         (info, {})    if part_num found but no specs matched
#         (info, specs) otherwise
def get_specs(part_num, db, specs=[]):
    ret_specs = {}
    info = {}
    for brand, prods in db['data'].items():
        for prod, parts in prods.items():
            for part in parts:
                if part_num.strip().lower() == part['part number'].strip().lower():
                    info['name'] = part['name']
                    info['part number'] = part['part number']
                    info['price'] = part['num_specs']['price']
                    info['status'] = part['status']
                    if not specs:
                        ret_specs = part
                    else:
                        # replace spec aliases with real spec
                        for i in range(len(specs)):
                            if specs[i] in SPEC_ALIASES: specs[i] = SPEC_ALIASES[specs[i]]
                            elif specs[i] in NUM_SPEC_ALIASES: specs[i] = NUM_SPEC_ALIASES[specs[i]]

                        # if spec is both normal spec and num spec, ignore num spec
                        for spec in specs:
                            if spec in part:
                                ret_specs[spec] = part[spec]
                            elif spec in part['num_specs']:
                                ret_specs[spec] = f'{part["num_specs"][spec][0]} {part["num_specs"][spec][1]}'
                    return info, ret_specs
    return None, None

def multiline(line, indent, max_width=73):
    wrapper = textwrap.TextWrapper(
        width             = max_width,
        subsequent_indent = ' '*indent,
    )
    return '\n'.join([f'`{l}`' for l in wrapper.fill(line).split('\n')])

# takes (info, specs) return value from get_specs
def format_specs(db, info, specs):
    contents = ''
    contents += f'{info["part number"]} ([link]({db["metadata"]["base url"]}/p/{info["part number"]}))'

    price_str = f'{info["price"][1]}{info["price"][0]:.2f}'
    if info['status'].lower() == 'unavailable':
        contents += f' **~~{price_str}~~ (unavailable)**\n'
    elif info['status'].lower() == 'customize':
        contents += f' **{price_str} (customize)**\n'
    else:
        contents += f' **{price_str}**\n'

    if specs:
        num_specs = {}
        for spec, value in specs.items():
            spacing = max([len(k) for k in specs.keys()])
            if spec == 'num_specs': # save num_specs sub-dict for later
                num_specs = specs[spec]
            else: # add regular specs
                line = f'{spec:>{spacing}}  {value}'
                contents += f'{multiline(line, indent=spacing+2)}\n'

            # format num_specs sub-dict
            if num_specs:
                num_spec_contents = f'`{"num_specs":>{spacing}}:`\n'
                num_spec_spacing = max([len(k) for k in num_specs.keys()])
                for num_spec, tup in num_specs.items():
                    val, unit = tup
                    line = f'{num_spec:>{num_spec_spacing}}  {val} {unit}'
                    num_spec_contents += f'{multiline(line, indent=num_spec_spacing+2)}\n'
                # only add num_specs if doesnt exceed length limit
                if len(contents+num_spec_contents) < 2048:
                    contents += num_spec_contents
                else:
                    contents += f'`{"num_specs":>{spacing}}  [omitted. use \'specs {info["part number"]} num_specs\' to view.]`\n'
    else: contents += f'`[no valid specs to list]`\n'

    return contents

def get_region_emoji(region_short):
    if region_short in REGION_EMOJIS:
        return REGION_EMOJIS[region_short]
    else:
        return None

def get_status(db):
    string = ''

    emoji = get_region_emoji(db['metadata']['short region'])
    if emoji: string += f' {emoji}'
    string += f' **{db["metadata"]["region"]}**\n'

    string += f'**{db["metadata"]["total"]}** products total across **{len(db["data"].keys())}** series\n'
    return string

def get_footer(db):
    total = 0
    dt = datetime.utcfromtimestamp(db['metadata']['timestamp'])

    string = (
        '_'*30 + '\n'
        f'{db["metadata"]["base url"]}\n'
    )

    if 'passcode' in db['metadata']: string += f'passcode: {db["metadata"]["passcode"]}\n'

    string += f'last update: {dt.strftime("%c")} UTC ({pretty_duration((datetime.utcnow() - dt).total_seconds())} ago)'
    return string

def get_dbs(dir):
    dbs = {}
    for filename in os.listdir(dir):
        if filename.endswith('.json'):
            with open(f'{dir}/{filename}', 'r') as f:
                js = f.read()
                db = json.loads(js)
                print(f'Loaded \'{dir}/{filename}\'')
                dbs[db['metadata']['short region']] = db
    return dbs

COMMAND_BRIEFS = {
    'listregions':   'list all available regions',
    'status':        'display status for all available databases',
    'reg_status':    'display region\'s database status',
    'reg_listspecs': 'list valid specs and num_specs',
    'reg_search':    'search for products with queries separated by commas',
    'reg_specs':     'list specs for a given product number',
}
COMMAND_DESCRS = {
    'listregions': (
        f'usage: !lelnovo listregions\n'
        f'       !lelnovo lr\n'
        f'\n'
        f'{COMMAND_BRIEFS["listregions"]}'
    ),
    'status': (
        f'usage: !lelnovo status\n'
        f'       !lelnovo st\n'
        f'\n'
        f'{COMMAND_BRIEFS["status"]}'
        # add reg_status help since it's inaccessible
        f'\n'
        f'\n'
        f'usage: !lelnovo [region] status\n'
        f'       !lelnovo [region] st\n'
        f'\n'
        f'{COMMAND_BRIEFS["reg_status"]}'
    ),
    'reg_status':  COMMAND_BRIEFS['reg_status'], # inaccessible
    'reg_listspecs': (
        f'usage: !lelnovo [region] listspecs\n'
        f'       !lelnovo [region] ls\n'
        f'\n'
        f'list valid specs and num_specs for use in \'search\' and \'specs\' commands'
    ),
    'reg_search': (
        f'usage: !lelnovo [region] search query[, query, ...]\n'
        f'       !lelnovo [region] s      query[, query, ...]\n'
        f'\n'
        f'{COMMAND_BRIEFS["reg_search"]}\n'
        f'\n'
        f'valid queries:\n'
        f'  term            searches for term in any field\n'
        f'  spec:[term]     searches for term in spec\n'
        f'                  leave term blank to always list spec in results\n'
        f'                  use \'listspecs\' region command to view valid specs\n'
        f'  num_spec<[num]  searches for num_spec that satisfies the condition \'< num\'\n'
        f'                  leave num blank to always list num_spec in results\n'
        f'                  valid operators are <,<=,==,!=,=>,>\n'
        f'                  use \'listspecs\' region command to view valid num_specs.\n'
        f'\n'
        f'example:\n'
        f'  "!lelnovo us search x1e, price<=1400, display:fhd"\n'
    ),
    'reg_specs': (
        f'usage: !lelnovo [region] specs prodnum [spec[, spec, ...]]\n'
        f'       !lelnovo [region] sp    prodnum [spec[, spec, ...]]\n'
        f'\n'
        f'{COMMAND_BRIEFS["reg_specs"]}\n',
        f'if specs are given, filters result by the given comma-separated specs.\n'
        f'use \'listspecs\' to view valid specs.\n'
        f'\n'
        f'examples:\n'
        f'  "!lelnovo us specs 20TK001EUS"\n'
        f'  "!lelnovo us specs 20TK001EUS display, price, memory"\n'
    ),
}
USAGE_STR = (
    f'usage: !lelnovo [region] command [parameters, ...]\n'
    f'\n'
    f'commands without region:\n'
    f'  {"h|help"        :14}    show this help message\n'
    f'  {"h|help command":14}    show help for command\n'
    f'  {"lr|listregions":14}    {COMMAND_BRIEFS["listregions"]}\n'
    f'  {"st|status"     :14}    {COMMAND_BRIEFS["status"]}\n'
    f'\n'
    f'commands with region:\n'
    f'  {"st|status"     :14}    {COMMAND_BRIEFS["reg_status"]}\n'
    f'  {"ls|listspecs"  :14}    {COMMAND_BRIEFS["reg_listspecs"]}\n'
    f'  {"s|search query[, query, ...]"}\n'
    f'  {" "             :14}    {COMMAND_BRIEFS["reg_search"]}\n'
    f'  {"sp|specs prodnum [spec[, spec, ...]]"}\n'
    f'  {" "             :14}    {COMMAND_BRIEFS["reg_specs"]}\n'
    f'\n'
    f'examples:\n'
    f'  "!lelnovo listregions"\n'
    f'  "!lelnovo us status"\n'
    f'  "!lelnovo us search x1e, price<=1400, display:fhd"\n'
    f'  "!lelnovo us specs 20TK001EUS"\n'
    f'  "!lelnovo us specs 20TK001EUS display, price, memory"\n'
)
REGION_EMOJIS = {
    'us':  ':flag_us:',
    'tck': ':tickets:',
    'gb':  ':flag_gb:',
    'ca':  ':flag_ca:',
    'epp': ':maple_leaf:',
}
SPEC_ALIASES = {
    'cores':     'cpu cores',
    'charger':   'ac adapter',
    'cpu':       'processor',
    'disc':      'optical drive',
    'fp':        'fp reader',
    'gpu':       'graphics',
    'pn':        'part number',
    'os':        'operating system',
    'ram':       'memory',
    'screen':    'display',
    'sim':       'sim card',
    'tpm':       'security chip',
    'touch':     'touch screen',
    'wifi':      'wireless',
}
NUM_SPEC_ALIASES = {
    'cores':       'cpu cores',
    'charger':     'ac adapter',
    'hres':        'display res horizontal',
    'ppi':         'pixel density',
    'screen size': 'display size',
    'ram':         'memory',
    'vres':        'display res vertical',
}
