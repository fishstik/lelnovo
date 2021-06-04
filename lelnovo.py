import argparse
import json
import time
import sys
import re
import operator
import math
from datetime import datetime,timezone,timedelta
from pprint import pprint

def pretty_duration(time_diff_secs):
    # Each tuple in the sequence gives the name of a unit, and the number of
    # previous units which go into it.
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
    qs = []
    for term in query.split(','):
        term = term.strip()
        m = re.match(r'(.*):(.*)', term) # spec:'string' search
        if m:
            spec   = m.group(1).strip()
            search = m.group(2).strip()
            if str(spec).lower() in [k.lower() for k in db['keys']['info']] + ['product']:
                qs.append(('spec', spec, search))
            else:
                print(f'Ignoring unhandled spec \'{spec}\' in \'{term}\'')
        else:
            m = re.match(r'\s?([\w ]+)([=<>]+)\s?(.*)', term) # num_spec comparison search
            if m:
                spec =   m.group(1).strip()
                op_str = m.group(2).strip()
                num    = m.group(3).strip()
                if spec in db['keys']['num_specs'] and op_str in ops:
                    qs.append(('num_spec', spec, ops[op_str], num))
                else:
                    print(f'Ignoring unhandled num_spec \'{spec}\' or num_spec operator \'{m.group(2)}\' in \'{term}\'')
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
                            # product line search
                            if term.lower() in prod.lower():
                                matches.append(('product line', prod))
                                qs_matched[i] = True
                            # generic search
                            for k, v in part.items():
                                if type(v) == str and term.lower() in v.lower():
                                    matches.append((k, v))
                                    qs_matched[i] = True
                        elif q[0] == 'spec':
                            spec = q[1]
                            term = q[2]
                            # product line search
                            if spec == 'product':
                                if term.lower() in prod.lower():
                                    matches.append(('product line', prod))
                                    qs_matched[i] = True
                            # spec search
                            else:
                                if term.lower() in part[spec].lower():
                                    matches.append((spec, part[spec]))
                                    qs_matched[i] = True
                        elif q[0] == 'num_spec':
                            num_spec = q[1]
                            op       = q[2]
                            num      = q[3]
                            if num_spec in part['num_specs'] and op(part['num_specs'][num_spec][0], float(num)):
                                matches.append((num_spec, f'{part["num_specs"][num_spec][0]} {part["num_specs"][num_spec][1]}'))
                                qs_matched[i] = True
                    if qs_matched.count(True) == len(qs):
                        results.append((prod, part, matches))
    else: error = True

    return results, error

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
                    if not specs:
                        ret_specs = part
                    else:
                        for spec in specs:
                            if spec in part:
                                ret_specs[spec] = part[spec]
                            elif spec in part['num_specs']:
                                ret_specs[spec] = f'{part["num_specs"][spec][0]} {part["num_specs"][spec][1]}'
                    return info, ret_specs

def format_specs(db, info, specs):
    contents = ''
    contents += (
        f'[{info["part number"]}]({db["metadata"]["base url"]}/p/{info["part number"]})'
        f' --- **{info["price"][1]}{info["price"][0]}**\n'
    )
    for spec, value in specs.items():
        spacing = max([len(k) for k in specs.keys()])
        if spec == 'num_specs':
            contents += f'`{spec:>{spacing}}:`\n'
            spacing = max([len(k) for k in specs['num_specs'].keys()])
            for num_spec, tup in specs['num_specs'].items():
                val, unit = tup
                contents += f'`{num_spec:>{spacing}}  {val} {unit}`\n'
        else:
            contents += f'`{spec:>{spacing}}  {value}`\n'

    return contents

def get_status(db):
    string = ''
    string += f'**{db["metadata"]["total"]}** products total across **{len(db["data"].keys())}** product lines\n'
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

def get_db(filename):
    with open('db.json', 'r') as f:
        js = f.read()
        return json.loads(js)

command_helps = {
    'listspecs': 'list valid specs and num_specs used in \'search\' and \'specs\' commands',
    'search': (
        'search for products with search terms separated by commas. '
        'use \'listspecs\' to view valid specs.\n'
        '\n'
        'possible search terms:\n'
        '  term          searches for \'term\' in any field\n'
        '  spec:term     searches for \'term\' in \'spec\'.\n'
        '  num_spec<num  searches for \'num_spec\' that satisfies the condition \'< num\'.\n'
        '                valid operators are < <= == != => >\n'
        '\n'
        'example:\n'
        '  "search x1e, price<1400, display:fhd"\n'
    ),
    'specs': (
        'list all specs for a given product number. '
        'if arguments are given, lists the given comma-separated specs. '
        'use \'listspecs\' to view valid specs.\n'
        '\n'
        'examples:\n'
        '  "specs 20TK001EUS"\n'
        '  "specs 20TK001EUS display, price, memory"\n'
    ),
    'status':    'display product database status',
}
command_briefs= {
    'listspecs': 'list valid specs and num_specs',
    'search':    'search for products',
    'specs':     'list specs for a given product number',
    'status':    'display product database status',
}
usage_str = (
    f'usage: !lelnovo command [arguments]\n'
    f'\n'
    f'commands:\n'
    f'  {"listspecs":10} {command_helps["listspecs"]}\n'
    f'  {"search   ":10} search for product with search terms separated by commas.\n'
    f'  {"         ":10} valid searches:\n'
    f'  {"         ":10}   term          searches for \'term\' in any field\n'
    f'  {"         ":10}   spec:term     searches for \'term\' in \'spec\'. Use \'listspecs\' command to view valid specs.\n'
    f'  {"         ":10}   num_spec<num  searches for \'num_spec\' that satisfies the condition \'< num\'.\n'
    f'  {"         ":10}                 valid operators are <,<=,==,!=,=>,>. Use \'listspecs\' command to view valid num_specs.\n'
    f'  {"specs    ":10} list all specs for a given product number. if arguments are given, lists the given comma-separated specs\n'
    f'  {"         ":10} use \'listspecs\' command to view valid specs.\n'
    f'  {"help     ":10} show this help message\n'
    f'\n'
    f'examples:\n'
    f'  "search x1e, price<1400, display:1080"\n'
    f'  "specs 20TK001EUS"\n'
    f'  "specs 20TK001EUS display, price"\n'
)
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command')
    args = parser.parse_args()

    db = get_db('db.json')

    words = re.split('\s+', args.command.strip())
    if len(words) == 1:
        command = words[0]
        if command == 'listspecs':
            print(f'valid specs:')
            specs = sorted(db['keys']['info'])
            for i in range(0, len(specs), 5):
                print('  '+' '.join([f'{spec:20}' for spec in specs[i:i+5]]))

            print(f'valid num_specs:')
            specs = sorted(db['keys']['num_specs'])
            for i in range(0, len(specs), 3):
                print('  '+' '.join([f'{spec:30}' for spec in specs[i:i+3]]))
        elif command == 'status':
            print(get_status(db))
            print(get_footer(db))
        elif command == 'help':
            print(usage_str)
        else:
            print(f'Unrecognized command \'{command}\'')
    else:
        command, rest = words[0], ' '.join(words[1:])
        if command == 'search':
            res, error = search(rest, db)
            if error:
                print(f'Invalid query \'{rest}\'')
            else:
                for re in res:
                    print(f'{res[0]} -> {res[1]["part number"]} | {res[1]["name"]}')
                    for match in res[2]:
                        print(f'  {match[0]:12} {match[1]}')
        elif command == 'specs':
            specs = []
            words = re.split('\s+', rest, 1)
            part_num = words[0]
            # user-provided specs
            if len(words) > 1: specs = [s.strip() for s in words[1].split(',')]
            res = get_specs(part_num, db, specs)

            if res:
                info, ret_specs = res
                if info and ret_specs: print(format_specs(db, info, ret_specs))
            else:
                print(f'Specs for \'{part_num}\' not found')
        else:
            print(f'Unrecognized command \'{command}\'')
