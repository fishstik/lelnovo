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
from bs4 import BeautifulSoup
from pprint import pprint

import io
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from dateutil.rrule import DAILY

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
                print(f'Ignoring invalid spec \'{spec}\' in \'{term}\'')
        else:
            m = re.match(r'\s?([\w ]+)([=<>]+)\s?(.*)', term) # num_spec comparison search
            if m:
                spec =   m.group(1).strip()
                op_str = m.group(2).strip()
                num    = m.group(3).strip()
                if op_str in ops:
                    try:
                        float(num)
                        if spec in db['keys']['num_specs']:
                            qs.append(('num_spec', spec, ops[op_str], num))
                        elif spec in NUM_SPEC_ALIASES and NUM_SPEC_ALIASES[spec] in db['keys']['num_specs']:
                            qs.append(('num_spec', NUM_SPEC_ALIASES[spec], ops[op_str], num))
                        else:
                            print(f'Ignoring invalid num_spec \'{spec}\' in \'{term}\'')
                    except ValueError: print(f'Ignoring invalid number \'{num}\' in \'{term}\'')
                else:
                    print(f'Ignoring invalid num_spec operator \'{m.group(2)}\' in \'{term}\'')
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

# takes (info, specs) return value from get_specs()
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
                if spec == 'processor': value = cleanup_cpu(value)
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
                contents += num_spec_contents
    else: contents += f'`[no valid specs to list]`\n'

    return contents

def get_specs_psref(s, pn, specs=[]):
    info = {}
    ret_specs = {}

    # replace spec aliases with real spec
    for i in range(len(specs)):
        if specs[i] in SPEC_ALIASES: specs[i] = SPEC_ALIASES[specs[i]]
        elif specs[i] in NUM_SPEC_ALIASES: specs[i] = NUM_SPEC_ALIASES[specs[i]]

    payload = {
        't':             'PreSearchForPerformance',
        'SearchContent': pn,
        'SearchType':    'Model',
    }
    r = s.post(f'https://psref.lenovo.com/ajax/HomeHandler.ashx', data=payload)
    if r:
        d = json.loads(r.text)
        if d:
            info['part number'] = pn
            info['name']        = d[0]['ProductName']
            info['url']         = f"https://psref.lenovo.com{d[0]['ProductPageLink']}"

    if info:
        r = s.get(info['url'])
        if r:
            soup = BeautifulSoup(r.content, 'html.parser')
            for table in soup.select('.SpecValueTable'):
                for row in table.find_all('tr'):
                    if not row.has_attr('class'):
                        tds = row.find_all('td')
                        if len(tds) >= 2:
                            spec_name = tds[0].get_text().lower()
                            spec_val = tds[1].get_text()
                            if not specs:
                                ret_specs[spec_name] = spec_val
                            else:
                                for spec in specs:
                                    if spec in spec_name:
                                        ret_specs[spec_name] = spec_val
    return info, ret_specs

# takes (info, specs) return value from get_specs()
def format_specs_psref(info, specs):
    contents = ''
    contents += f'{info["part number"]} ([PSREF link]({info["url"]}))\n'

    if specs:
        num_specs = {}
        for spec, value in specs.items():
            spacing = max([len(k) for k in specs.keys()])
            if spec == 'processor': value = cleanup_cpu(value)
            line = f'{spec:>{spacing}}  {value}'
            contents += f'{multiline(line, indent=spacing+2)}\n'
    else: contents += f'`[no valid specs to list]`\n'

    return contents

def multiline(line, indent, max_width=73):
    wrapper = textwrap.TextWrapper(
        width             = max_width,
        subsequent_indent = ' '*indent,
    )
    return '\n'.join([f'`{l}`' for l in wrapper.fill(line).split('\n')])

def format_changes(changes, base_url=None):
    shown_changed_specs = ['price', 'status', 'shipping']

    ret_contents = {
        'added':   {},
        'removed': {},
        'changed': [],
    }

    for k, v in changes.items():
        #print(k)
        #if k == 'timestamp_old':
        #    print(f'  {datetime.utcfromtimestamp(v)}')
        if k in ['added', 'removed']:
            sym = '+' if k == 'added' else '-'
            for brand, prod in v.items():
                #print(f'  {brand}')
                for prodn, prodname_ps in prod.items():
                    if base_url: prodlink = f' [{prodname_ps[0]}]({base_url}/p/{prodn})'
                    else:        prodlink = f' {prodname_ps[0]}'
                    header = f' **{prodlink}**'

                    num = len(prodname_ps[1])
                    if num > 0: header += f' ({num})'
                    else:       header += ''

                    ret_contents[k][header] = []
                    for i in range(len(prodname_ps[1])):
                        p = prodname_ps[1][i]
                        ret_contents[k][header].append(part_listentry(p, base_url=base_url if k == 'added' else None))
        elif k == 'changed':
            avgs = []
            for brand, prod in v.items():
                #print(f'  {brand}')
                for prodn, prodname_ps in prod.items():
                    avg = {
                        'prodnum': '',
                        'prodname': '',
                        'price_before': [],
                        'percent_change': [],
                    }
                    first = True
                    for p, changes in prodname_ps[1]:
                        curr = p['num_specs']['price'][1]
                        changes_filtered = [c for c in changes if c['spec'] in shown_changed_specs]
                        if changes_filtered:
                            if first:
                                #print(f'  {prodname_ps[0]} {prodn} ({len(prodname_ps[1])})')
                                first = False
                            #print(f'    {part_listentry(p)}')
                            for change in changes_filtered:
                                if change['is_num_spec']:
                                    before = f'{change["before"][1]}{change["before"][0]}'
                                    after = f'{change["after"][1]}{change["after"][0]}'
                                    percent_change = (change['after'][0]-change['before'][0])/change['before'][0]
                                    #print(f'      {change["spec"]}: {percent_change:+4.0%} ({before}->{after})')
                                #else:
                                #    print(f'      {change["spec"]}: {change["before"]} -> {change["after"]}')

                                if change['spec'] == 'price':
                                    avg['price_before'].append(change['before'][0])
                                    avg['percent_change'].append((change['after'][0]-change['before'][0])/change['before'][0])
                                    #print(
                                    #    f'    {avg["percent_change"][-1]:+4.0%}'
                                    #    f' ({"{}{:.2f}".format(curr, avg["price_before"][-1]):>8}->{"{}{:.2f}".format(curr, change["after"][0]):8})'
                                    #)

                    if avg['percent_change']:
                        avg['prodnum']        = prodn
                        avg['prodname']       = prodname_ps[0]
                        avg['count']          = len(avg['price_before'])
                        avg['price_before']   = sum(avg['price_before'])/len(avg['price_before'])
                        avg['percent_change'] = sum(avg['percent_change'])/len(avg['percent_change'])
                        avgs.append(avg)

            for avg in sorted(avgs, key=lambda x: x['percent_change']):
                avg_price_after = avg['price_before']*(1+avg['percent_change'])
                if base_url: prodname = f'[{avg["prodname"]}]({base_url}/p/{avg["prodnum"]})'
                else:        prodname = avg['prodname']
                percent = f'{"avg " if avg["count"] > 1 else ""}{avg["percent_change"]:+.0%}'
                before = f'{curr}{round(avg["price_before"])}'
                after =  f'{curr}{round(avg_price_after)}'
                ret_contents[k].append(
                    f'`{percent:>9} {before:>5}->{after:>5}` '
                    f'**{prodname}** '
                    f'({avg["count"]})'
                )

    return ret_contents

def part_listentry(p, show_pn=True, base_url=None, show_price=True, show_name=False, fmt='`'):
    if base_url: pn = f'{p["part number"]} ([link]({base_url}/p/{p["part number"]}))'
    else:
        if show_pn: pn = f'{p["part number"]}'
        else:       pn = ''
    price = f'{p["num_specs"]["price"][1]}{p["num_specs"]["price"][0]:.2f}'
    #res = f'{p["num_specs"]["display res horizontal"][0]}x{p["num_specs"]["display res vertical"][0]}' if "display res vertical" in p["num_specs"] else ""
    res = f' {p["num_specs"]["display res vertical"][0]}p ' if "display res vertical" in p["num_specs"] else ""
    proc = f'{cleanup_cpu(p["processor"], 2)}'
    if 'graphics' in p and 'discrete' in p['graphics'].lower() or 'nvidia' in p['graphics'].lower(): proc += f', {cleanup_gpu(p["graphics"], 2)}'
    ret = (
        f'{pn}'
        f'{" "+fmt+price+" " if show_price else " "+fmt}'
        f'{str(int(p["num_specs"]["memory"][0]))+p["num_specs"]["memory"][1] if "memory" in p["num_specs"] else ""}'
        f'{","+str(int(p["num_specs"]["storage"][0]))+p["num_specs"]["storage"][1] if "storage" in p["num_specs"] else ""}'
        f'{res}'
        f'{proc}{fmt}'
    )
    if show_name: ret += f' {p["name"]}'
    return ret

# level 0: Intel Core i5-1135G7, AMD Ryzen 5 4500U
# level 1:       Core i5-1135G7,     Ryzen 5 4500U
# level 2:            i5-1135G7,             4500U
def cleanup_cpu(cpu, level=0):
    m = re.search(r'((?:Intel|AMD|Qualcomm).*) Processor', cpu)
    if m: cpu = m.group(1)
    cpu = re.sub(r'\s+\(.*\)', '', cpu)
    cpu = re.sub(r'\S+\s+\S+\s+Gen(eration)?\s?', '', cpu)
    cpu = re.sub(r'IntelCore', 'Intel Core', cpu)
    cpu = re.sub(r'Core Intel', 'Core', cpu)
    cpu = re.sub(r'(i\d)\s+\1', r'\1', cpu) # i5 i5-XXXX
    if level >= 1:
        cpu = re.sub('(Intel|AMD|Qualcomm)\s+', '' , cpu)
    if level >= 2:
        cpu = re.sub('(Core\s+|Xeon\s+|Ryzen\s+\d+\s+)(Pro\s+)?', '' , cpu)
    return cpu

# level 0: Intel Iris Xe, NVIDIA RTX 2070 Max-Q
# level 1:       Iris Xe,        RTX 2070 Max-Q
# level 2:       Iris Xe,            2070 MQ
def cleanup_gpu(gpu, level=0):
    m = re.search(r'((?:Intel|AMD|Qualcomm).*) Graphics', gpu)
    if m: gpu = m.group(1)
    tmp = []
    for word in [w for w in re.split(r'\s+', gpu) if w.lower() not in [
        'geforce',
        'discrete',
        'integrated',
        'with',
        'other',
        'graphics',
        't',
        'series',
    ]]:
        tmp.append(word)
    gpu = ' '.join(tmp)
    gpu = re.sub(r'\s?\d+GB', '', gpu)
    gpu = re.sub(r'\s?\d+bits', '', gpu)
    gpu = re.sub(r'\s?GDDR\d+', '', gpu)
    if level >= 1:
        gpu = re.sub('(Intel|AMD|NVIDIA|Qualcomm)\s+', '' , gpu)
    if level >= 2:
        gpu = re.sub('\s?Super', 'S' , gpu)
        gpu = re.sub('Max-?Q', 'MQ' , gpu)
        gpu = re.sub('[RG]TX\s?', '' , gpu)
    return gpu

# returns ([(dt:datetime, price:str, unavailable:bool) ...], part:dict)
def get_history(pn, dbs):
    data = []
    part = None

    for db in dbs:
        dt = datetime.utcfromtimestamp(db['metadata']['timestamp'])
        found = False
        for brand, prods in db['data'].items():
            if found: break
            for prod, parts in prods.items():
                if found: break
                for p in parts:
                    if found: break
                    if pn == p['part number']:
                        if p['status'].lower() == 'unavailable':
                            data.append((dt, p['num_specs']['price'][0], True))
                        else:
                            data.append((dt, p['num_specs']['price'][0], False))
                        part = p
                        found = True
        if not found: data.append((dt, -100, False))

    return data, part

# takes (data, part) return value from get_history()
# returns binary stream of plot image
def plot_history(data, part):
    unav_alpha = 0.6

    if part:
        curr = part['num_specs']['price'][1]

        x = np.array([d[0] for d in data])
        y = np.array([d[1] for d in data])
        a = np.array([unav_alpha if d[2] else 1.0 for d in data])
        y_masked = np.ma.masked_where(y <= 0, y)
        y_masked_unav = np.ma.masked_where(a == 1.0, y_masked)
        y_masked_av = np.ma.masked_where(a < 1.0, y_masked)

        plt.rcParams['font.size'] = 12
        fig = plt.figure(figsize=(8,5))
        ax = plt.axes()

        locator = mdates.AutoDateLocator()
        locator.intervald[DAILY] = [round((x[-1]-x[0]).days/15)]
        formatter = mdates.ConciseDateFormatter(locator)
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(formatter)

        ax.set_ylim(bottom=0)
        ylim = round(max(y))+200-(round(max(y))%100)
        ax.set_yticks(np.arange(0, ylim+1, ylim/5))
        ax.yaxis.set_major_formatter(curr+'{x:1.0f}')

        for i in range(len(y)):
            if (y[i] != -100
                and (i == 0
                    or all([abs(y[i-n]-y[i]) > ylim/20 for n in range(1, 10)])
                )
            ):
                plt.text(x=x[i], y=y[i]-ylim/5/3, s=f'{curr}{round(y[i])}', **{'fontweight': 'bold', 'alpha': a[i]})

        plt.title(part['name'])
        plt.scatter(x, y, alpha=a)
        plt.plot(x, y_masked_av)
        plt.plot(x, y_masked_unav, 'C0--', alpha=unav_alpha)
        plt.grid(axis='x')

        bytes = io.BytesIO()
        plt.savefig(bytes, format='png', bbox_inches='tight', dpi=100)
        plt.close()

        return bytes
    else: return None

def get_region_emoji(region_short):
    if region_short in REGION_EMOJIS:
        return REGION_EMOJIS[region_short]
    else:
        return None

def get_status(db, backup_dir=None):
    string = ''

    backup_tss = []
    if backup_dir:
        for f in os.scandir(backup_dir):
            if f.name.startswith(f'db_{db["metadata"]["short region"]}_') and f.name.endswith('.json'):
                # use mtime instead of json timestamp (much faster)
                backup_tss.append(f.stat().st_mtime)
    backup_tss = sorted(backup_tss)

    emoji = get_region_emoji(db['metadata']['short region'])
    if emoji: string += f' {emoji}'
    string += f' **{db["metadata"]["region"]}**\n'

    string += f'**{db["metadata"]["total"]}** products total across **{len(db["data"].keys())}** series\n'

    if backup_tss:
        dt = datetime.utcfromtimestamp(backup_tss[0])
        string += f'**{len(backup_tss)}** historical databases saved since {dt.strftime("%b %d %Y")} ({pretty_duration((datetime.utcnow() - dt).total_seconds())} ago)\n'
    else: string += f'No historical databases saved\n'

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

def get_usage_str(prefixes):
    prefix = prefixes[0]
    return (
        f'usage: {"|".join(prefixes)} [region] [command] [parameters, ...]\n'
        f'\n'
        f'commands without region:\n'
        f'  {"h|help"        :14}    show this help message\n'
        f'  {"h|help command":14}    show help for command\n'
        f'  {"lr|listregions":14}    {COMMAND_BRIEFS["listregions"]}\n'
        f'  {"st|status"     :14}    {COMMAND_BRIEFS["status"]}\n'
        f'  {"sr|setregion"  :14}    {COMMAND_BRIEFS["setregion"]}\n'
        f'  {"ps|psref"      :14}    {COMMAND_BRIEFS["psref"]}\n'
        f'\n'
        f'commands with region:\n'
        f'  {"st|status"     :14}    {COMMAND_BRIEFS["reg_status"]}\n'
        f'  {"ls|listspecs"  :14}    {COMMAND_BRIEFS["reg_listspecs"]}\n'
        f'  {"ch|changes  "  :14}    {COMMAND_BRIEFS["reg_changes"]}\n'
        f'  {"s|search query[, query, ...]"}\n'
        f'  {" "             :14}    {COMMAND_BRIEFS["reg_search"]}\n'
        f'  {"sp|specs prodnum [spec[, spec, ...]]"}\n'
        f'  {" "             :14}    {COMMAND_BRIEFS["reg_specs"]}\n'
        f'  {"hi|history"    :14}    {COMMAND_BRIEFS["reg_history"]}\n'
        f'\n'
        f'examples:\n'
        f'  "{prefix} help search"\n'
        f'  "{prefix} listregions"\n'
        f'  "{prefix} us status"\n'
        f'  "{prefix} us search x1e, price<=1400, display:fhd"\n'
        f'  "{prefix} us specs 20TK001EUS"\n'
        f'  "{prefix} us specs 20TK001EUS price, display, memory"\n'
        f'  "{prefix} us history 20TK001EUS"\n'
        f'  "{prefix} setregion us", then "{prefix} history 20TK001EUS"\n'
        f'  "{prefix} psref 20TK001EUS"\n'
        f'  "{prefix} psref 20TK001EUS processor, display, memory"\n'
    )

def get_command_descr(cmd, prefixes):
    if cmd == 'setregion':
        ret_str = (
            f'usage: {"|".join(prefixes)} setregion [region / \'cl\'|\'clear\']\n'
            f'       {"|".join(prefixes)} sr        [region / \'cl\'|\'clear\']\n'
            f'\n'
            f'{COMMAND_BRIEFS["setregion"]}\n'
            f'\n'
            f'use \'{prefixes[0]} setregion\' to view currently saved region\n'
            f'use \'{prefixes[0]} setregion clear\' to clear saved region\n'
            f'use \'{prefixes[0]} listregions\' to view valid regions\n'
            f'\n'
            f'examples:\n'
            f'  "{prefixes[0]} setregion"\n'
            f'  "{prefixes[0]} setregion tck"\n'
            f'  "{prefixes[0]} setregion clear"\n'
        )
    elif cmd == 'listregions':
        ret_str = (
            f'usage: {"|".join(prefixes)} listregions\n'
            f'       {"|".join(prefixes)} lr\n'
            f'\n'
            f'{COMMAND_BRIEFS["listregions"]}'
        )
    elif cmd == 'status':
        ret_str = (
            f'usage: {"|".join(prefixes)} status\n'
            f'       {"|".join(prefixes)} st\n'
            f'\n'
            f'{COMMAND_BRIEFS["status"]}'
            # add reg_status help since it's inaccessible
            f'\n'
            f'\n'
            f'usage: {"|".join(prefixes)} [region] status\n'
            f'       {"|".join(prefixes)} [region] st\n'
            f'\n'
            f'{COMMAND_BRIEFS["reg_status"]}'
        )
    elif cmd == 'psref':
        ret_str = (
            f'usage: {"|".join(prefixes)} psref [prodnum] [spec[, spec, ...]]\n'
            f'       {"|".join(prefixes)} ps    [prodnum] [spec[, spec, ...]]\n'
            f'\n'
            f'{COMMAND_BRIEFS["psref"]}\n',
            f'if specs are given, filters result by the given comma-separated specs.\n'
            f'\n'
            f'examples:\n'
            f'  "{prefixes[0]} us psref 20TK001EUS"\n'
            f'  "{prefixes[0]} us psref 20TK001EUS price, display, memory"\n'
        )
    elif cmd == 'reg_status':
        ret_str = COMMAND_BRIEFS['reg_status'] # inaccessible
    elif cmd == 'reg_listspecs':
        ret_str = (
            f'usage: {"|".join(prefixes)} [region] listspecs\n'
            f'       {"|".join(prefixes)} [region] ls\n'
            f'\n'
            f'list valid specs and num_specs for use in \'search\' and \'specs\' commands'
        )
    elif cmd == 'reg_changes':
        ret_str = (
            f'usage: {"|".join(prefixes)} [region] changes\n'
            f'       {"|".join(prefixes)} [region] ch\n'
            f'\n'
            f'show additions, removals, and price changes since previous database update'
        )
    elif cmd == 'reg_search':
        ret_str = (
            f'usage: {"|".join(prefixes)} [region] search [query[, query, ...]]\n'
            f'       {"|".join(prefixes)} [region] s      [query[, query, ...]]\n'
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
            f'  "{prefixes[0]} us search x1e, price<=1400, display:fhd"\n'
        )
    elif cmd == 'reg_specs':
        ret_str = (
            f'usage: {"|".join(prefixes)} [region] specs [prodnum] [spec[, spec, ...]]\n'
            f'       {"|".join(prefixes)} [region] sp    [prodnum] [spec[, spec, ...]]\n'
            f'\n'
            f'{COMMAND_BRIEFS["reg_specs"]}\n',
            f'if specs are given, filters result by the given comma-separated specs.\n'
            f'use \'listspecs\' to view valid specs.\n'
            f'\n'
            f'examples:\n'
            f'  "{prefixes[0]} us specs 20TK001EUS"\n'
            f'  "{prefixes[0]} us specs 20TK001EUS price, display, memory"\n'
        )
    elif cmd == 'reg_history':
        ret_str = (
            f'usage: {"|".join(prefixes)} [region] history [prodnum]\n'
            f'       {"|".join(prefixes)} [region] hi      [prodnum]\n'
            f'\n'
            f'{COMMAND_BRIEFS["reg_history"]}\n',
            f'\n'
            f'example:\n'
            f'  "{prefixes[0]} us history 20TK001EUS"\n'
        )
    else:
        ret_str = ''
    return ret_str

COMMAND_BRIEFS = {
    'psref':         'list PSREF specs for a given product number',
    'setregion':     'set/view/clear user region for region commands',
    'listregions':   'list all available regions',
    'status':        'display status for all available databases',
    'reg_status':    'display region\'s database status',
    'reg_changes':   'show changes compared to previous update',
    'reg_listspecs': 'list valid specs and num_specs',
    'reg_search':    'search for products with queries separated by commas',
    'reg_specs':     'list specs for a given product number',
    'reg_history':   'show price history for a given product number',
}

REGION_EMOJIS = {
    'us':    ':flag_us:',
    'tck':   ':tickets:',
    'gb':    ':flag_gb:',
    'ca':    ':flag_ca:',
    'epp':   ':maple_leaf:',
    'gbepp': ':pound:',
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
