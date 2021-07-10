import argparse
import requests
import sys
import re
import json
import math
import time
import multiprocessing
import os
from bs4 import BeautifulSoup
from itertools import repeat
from collections import namedtuple
from datetime import datetime
from html2text import html2text
from pprint import pprint, pformat

def try_request(s, url, wait_s=1):
    while True:
        r = s.get(url)
        if r.status_code == 200:
            return r
        elif r.status_code == 404:
            return None
        else:
            #print(f'request {url} failed with {r.status_code}. Waiting {wait_s}s ...')
            #time.sleep(wait_s)
            #wait_s *= 2
            print(f'request {url} failed with {r.status_code} Exiting...')
            sys.exit() #FIXME: terminate mp parent if child is exiting

def get_info(prod, button):
    info = {}

    pn = ''
    part = prod.find('div', {'class': 'partNumber'})
    if prod.has_attr('data-code'):
        pn = prod['data-code']
    elif part:
        pn = part.text.split('\xa0')[-1]
    elif button.has_attr('data-productcode'):
        pn = button['data-productcode']
    if not pn:
        print(f'ERROR: No part number found for {prod}. Skipping...')
        return None
    info['part number'] = pn

    bundle = prod.find_all('a', {'class': 'bundleResults-black'})
    if bundle:
        info['bundle'] = [part['href'].split('/p/')[-1] for part in bundle]
        pn = info['bundle'][0]

    name = prod.select('h3.tabbedBrowse-productListing-title, h2.tabbedBrowse-title')
    name = name[0].contents[0].strip()
    name = name.replace('\n', '')
    info['name'] = name

    #price = prod.select_one('dd.saleprice.pricingSummary-details-final-price, span.bundleDetail_youBundlePrice_value')
    #price = price.text.strip()
    #for ch in ['$', ',']:
    #    if ch in price: price = price.replace(ch, '')
    #info['price'] = NumSpec(float(price), '$')

    if button.has_attr('disabled'): info['status'] = 'Unavailable'
    else:                           info['status'] = button.text.strip()

    #coupon = prod.find('span', {'class': 'pricingSummary-couponCode'})
    #if coupon: info['coupon'] = coupon.text.strip()

    shipping = prod.find('div', {'class': 'rci-esm'})
    info['shipping'] = shipping.text.strip() if shipping else ''

    #info['cto'] = button.text.strip() != 'Add to cart'

    #spec_names = []
    #spec_values = []
    #specs = prod.find('div', {'class': 'tabbedBrowse-productListing-featureList'})
    #if specs:
    #    for spec_name in specs.find_all('dt'):
    #        spec_names.append(spec_name.text.strip())
    #    for spec_value in specs.find_all('dd'):
    #        spec_values.append(spec_value.text.strip())
    #else: # single-model view
    #    specs = prod.find('ul', {'class': 'configuratorItem-mtmTable'})
    #    for spec_name in specs.find_all('h4', {'class': 'configuratorItem-mtmTable-title'}):
    #        spec_names.append(spec_name.text.strip())
    #    for spec_value in specs.find_all('p', {'class': 'configuratorItem-mtmTable-description'}):
    #        spec_values.append(spec_value.text.strip())
    #info['specs'] = dict(zip(spec_names, spec_values))

    return pn, info

def get_api_specs(session, pn):
    spec_merge = {
        'battery':                    'battery',
        'blue tooth':                 'bluetooth',
        'body color':                 'color',
        'depth_met':                  'depth',
        'display type':               'display',
        'feature backlit keyboard':   'keyboard',
        'feature convertible':        'convertible',
        'feature fingerprint reader': 'fp reader',
        'feature for gaming':         'gaming',
        'feature optical drive':      'optical drive',
        'feature numeric keypad':     'keyboard',
        'feature touch screen':       'display',
        'formfactadapter_ag':         'graphics',
        'hard drive':                 'storage',
        'hdtype':                     'storage',
        'height_met':                 'height',
        'integrated graphics':        'graphics',
        'longdesc_bat':               'battery',
        'maxresolution':              'display',
        'near field communication':   'nfc',
        'num_cores':                  'cores',
        'nb_wwan':                    'wwan',
        'operating system language':  'operating system',
        'pixels':                     'camera',
        'processortype':              'processor',
        'ram slots avail':            'ram slots free',
        'selectable sim':             'sim card',
        'series mktg battery':        'battery',
        'series mktg weight':         'weight',
        'screen resolution':          'display',
        'screen size':                'display',
        'vidram':                     'graphics',
        'weight in lbs':              'weight',
        'weight in kg':               'weight',
        'width_met':                  'width',
        'world facing camera':        'second camera',
        'wlan':                       'wireless',
    }
    spec_nums = {
        'ac adapter':        ('system common attributes', r'([\d\.]+) ?W',    int,   'W',  ['ac adapter']),
        'depth_met':         ('report usage',             r'([\d\.]+).*mm',   float, 'mm', ['depth']),
        'height_met':        ('report usage',             r'([\d\.]+) ?mm',   float, 'mm', ['thickness']),
        'hard drive':        ('facet features mtmcto',    r'(\d+) ?GB',       int,   'GB', ['storage']),
        'hard drive':        ('facet features mtmcto',    r'(\d+) ?TB',       int,   'TB', ['storage']),
        'memory':            ('facet features mtmcto',    r'([\d\.]+) ?GB',   float, 'GB', ['memory']),
        'num_cores':         ('report usage',             r'(\d+)',           int,   '',   ['cpu cores']),
        'screen resolution': ('facet features mtmcto',    r'(\d+) ?x ?(\d+)', int,   'px', ['display res horizontal', 'display res vertical']),
        'screen size':       ('facet features mtmcto',    r'([\d\.]+)"',      float, 'in', ['display size']),
        'width_met':         ('report usage',             r'([\d\.]+) ?mm',   float, 'mm', ['width']),
        'weight in lbs':     ('facet features mtmcto',    r'([\d\.]+)',       float, 'lb', ['weight']),
        'weight in kg':      ('facet features mtmcto',    r'([\d\.]+)',       float, 'kg', ['weight']),
    }
    spec_ignore = [
        'feature trackpoint',
        'form factor',
        'freeformfacet1',
        'freeformfacet2',
        'freeformfacet3',
        'freeformfacet4',
        'freeformfacet5',
        'longdesc_sec',
        'optional device',
        'pointing device',
        'product type',
        'touch screens',
        'type_attr1',
        'usage_attr1',
    ]
    r = try_request(session, f'{BASE_URL}/p/{pn}/specs/json')
    d = json.loads(r.text)

    all_specs = []
    for feature_types_d in d['classificationData']:
        feature_type = feature_types_d['name']
        for feature_d in feature_types_d['featureDataDTO']:
            feature_val = feature_d['featureValues'][0]['value'].encode('ascii', 'ignore').decode('ascii') # clean up unicode
            all_specs.append((feature_d['name'], feature_val, feature_type))

    # merge/clean up specs
    specs = {}
    num_specs = {}
    for spec in all_specs:
        spec_name = spec[0].lower()
        spec_value = spec[1]
        spec_type = spec[2].lower()

        # clean up spec value
        spec_value = re.sub(r'<sup>|<\/sup>', '', spec_value)
        # assemble numeric specs
        if spec_name in spec_nums and spec_nums[spec_name][0] == spec_type:
            regex          = spec_nums[spec_name][1]
            type_id        = spec_nums[spec_name][2]
            num_spec_unit  = spec_nums[spec_name][3]
            num_spec_names = spec_nums[spec_name][4]
            m = re.match(regex, spec_value)
            if m:
                for i in range(len(m.groups())):
                    num_specs[num_spec_names[i]] = NumSpec(type_id(m.groups()[i]), num_spec_unit)
        # merge spec names
        if spec_name not in spec_ignore:
            if spec_name in spec_merge:
                spec_name = spec_merge[spec_name]
            if spec_name not in specs:
                specs[spec_name] = spec_value
            else:
                for word in spec_value.split():
                    if word.lower() not in specs[spec_name].lower():
                        specs[spec_name] += f' {word}'

    # calculate numeric specs
    # pixel density
    if (    'display res horizontal' in num_specs
        and 'display res vertical'   in num_specs
        and 'display size'           in num_specs
    ):
        num_specs['pixel density'] = (
            int(round((
                math.sqrt(
                    num_specs['display res horizontal'].value**2
                    + num_specs['display res vertical'].value**2
                ) / num_specs['display size'].value
            ))),
            'ppi'
        )

    #print(pn)
    #pprint([f'{f[2]:30} {f[0]:30} {f[1]}' for f in sorted(all_specs, key = lambda x: x[0])], width=187)
    #pprint([f'{k:20} {v}' for k, v in specs.items()], width=187)
    #pprint([f'{k:20} {v}' for k, v in num_specs.items()], width=187)
    return specs, num_specs

def process_brand(s, brand, print_part_progress=False, print_live_progress=False):
    # returns dict with part numbers as key
    prods = {}
    # keep track of and return all keys encountered in this brand
    keys = {
        'info': [],
        #'api_specs': [], # merged into 'info'
        'num_specs': [],
    }

    start = time.time()
    if print_live_progress: print(brand, end='\r')

    pcodes = []
    if brand == 'yoga':
        r = try_request(s, f'{BASE_URL}/yoga/products')
        soup = BeautifulSoup(r.content, 'html.parser')
        for yoga in soup.select('section.yoga-list-convertibles'):
            pcodes.extend([p['data-article-test'] for p in yoga.select('*[data-article-test]')])
    elif brand == 'ideapad-s-series':
        r = try_request(s, f'{BASE_URL}/d/ideapad-ultra-thin')
        soup = BeautifulSoup(r.content, 'html.parser')
        pcodes.extend(soup.select_one('#partNumbers')['data-partnumbers'].strip(',').split(','))
    else:
        r = try_request(s, f'{BASE_URL}/c/{brand}')
        soup = BeautifulSoup(r.content, 'html.parser')
        pcodes = soup.select_one('meta[name="subseriesPHimpressions"], meta[name="bundleIDimpressions"]')['content'].split(',')

    for pn in set(pcodes):
        prods[pn] = []

    if print_part_progress: print(f'{brand} ({len(prods)}) {time.time()-start:.1f}s')

    prod_count = 0
    cur_str = ''
    for prod, parts in prods.items():
        cur_str = f'{brand:22} ({prod_count+1:<2}/{len(prods):2}) {prod}'
        if print_live_progress: print(cur_str, end='\r')
        start = time.time()

        r = try_request(s, f'{BASE_URL}/p/{prod}')
        if r:
            soup = BeautifulSoup(r.content, 'html.parser')

            cur_str += f' {time.time()-start:.1f}s'
            if print_live_progress: print(cur_str, end='\r')
            start = time.time()

            part_count = 0
            for prod in soup.select('li.tabbedBrowse-productListing-container, div.tabbedBrowse-module.singleModelView'):
                button = prod.select_one('form[id^="addToCartFormTop"] button[class*="tabbedBrowse-productListing-footer"]')
                if button:
                    res = get_info(prod, button)
                    if res:
                        pn, info = res

                        #info['api_specs'], info['num_specs'] = get_api_specs(s, pn)
                        api_specs, num_specs = get_api_specs(s, pn)

                        # get price info from api call
                        r = try_request(s, f'{BASE_URL}/p/{pn}/singlev2/price/json')
                        if r:
                            d = json.loads(r.text)
                            currency = d['currencySymbol']
                            if d['eCoupon']: info['coupon'] = d['eCoupon']
                            price_str = d['startingAtPrice']
                            for ch in [currency, ',']:
                                if ch in price_str: price_str = price_str.replace(ch, '')
                            num_specs['price'] = NumSpec(float(price_str), currency)

                        # merge api specs with info
                        info.update(api_specs)
                        # store num_specs as own entry
                        info['num_specs'] = num_specs

                        # add weight unit to info-weight from num_spec-weight
                        if 'weight' in info and 'weight' in info['num_specs']:
                            info['weight'] += f' {info["num_specs"]["weight"].unit}'

                        # collect and merge keys
                        keys['info'] = list(set(keys['info'] + list(info.keys()))) 
                        #keys['api_specs'] = list(set(keys['api_specs'] + list(info['api_specs'].keys())))
                        keys['num_specs'] = list(set(keys['num_specs'] + list(info['num_specs'].keys())))

                        parts.append(info)

                        part_count += 1
                    if print_live_progress: print(f'{cur_str} {"#"*part_count}{part_count}\r', end='\r')
            if print_part_progress: print(f'{cur_str:46} {"#"*part_count}{part_count} {time.time()-start:.1f}s')
            prod_count += 1
        else:
            cur_str += f' {prod} 404!'
            print(f'{cur_str:46} {time.time()-start:.1f}s')

    return prods, keys

#returns changes = {
#    'timestamp_old' = ts,
#    'added':   { 'brand': { 'prodn': ('prod', [part_d, ... ]), ... }, ... },
#    'removed': { 'brand': { 'prodn': ('prod', [part_d, ... ]), ... }, ... },
#    'changed': { 'brand': { 'prodn': ('prod', [(part_d, [ {'spec': str, 'is_num_spec': bool, 'before': str, 'after': str}, ... ], ... ), ... ]) }, ... }
#}
def get_changes(db_new, db_old):
    added = {}
    removed = {}
    changed = {}
    # check for additions
    for brand, prods in db_new['data'].items():
        for prodn, parts in prods.items():
            # keep copy of parts, remove if found in old db_new
            new_parts = list(parts)
            if brand in db_old['data'] and prodn in [p[0] for p in db_old['brands'][brand]]:
                for part in parts:
                    for part_old in db_old['data'][brand][prodn]:
                        if part_old['part number'] == part['part number']:
                            new_parts.remove(part)
                # add new_parts list to added dict
                if new_parts:
                    if brand not in added: added[brand] = {}
                    if prodn not in added[brand]: added[brand][prodn] = ([v[1] for v in db_new["brands"][brand] if v[0] == prodn][0], [])
                    added[brand][prodn][1].extend(new_parts)
            else: # new brand or prodn, count all
                if brand not in added: added[brand] = {}
                if prodn not in added[brand]: added[brand][prodn] = ([v[1] for v in db_new["brands"][brand] if v[0] == prodn][0], [])
                added[brand][prodn][1].extend(new_parts)
    # check for removals
    for brand, prods in db_old['data'].items():
        if brand in db_new['data']:
            for prodn, parts in prods.items():
                # keep copy of parts, remove if found in old db
                removed_parts = list(parts)
                if prodn in [p[0] for p in db_new['brands'][brand]]:
                    for part in parts:
                        for part_new in db_new['data'][brand][prodn]:
                            if part_new['part number'] == part['part number']:
                                removed_parts.remove(part)
                    # add removed_parts list to added dict
                    if removed_parts:
                        if brand not in removed: removed[brand] = {}
                        if prodn not in removed[brand]: removed[brand][prodn] = ([v[1] for v in db_old["brands"][brand] if v[0] == prodn][0], [])
                        removed[brand][prodn][1].extend(removed_parts)
                else: # entire prodn removed, count all
                    if brand not in removed: removed[brand] = {}
                    if prodn not in removed[brand]: removed[brand][prodn] = ([v[1] for v in db_old["brands"][brand] if v[0] == prodn][0], [])
                    removed[brand][prodn][1].extend(removed_parts)
        else: # entire brand removed, count all
            if brand not in removed: removed[brand] = {}
            for prodn, parts in prods.items():
                if prodn not in removed[brand]: removed[brand][prodn] = ([v[1] for v in db_old["brands"][brand] if v[0] == prodn][0], [])
                removed[brand][prodn][1].extend(parts)
    # check for changes
    for brand, prods in db_new['data'].items():
        for prodn, parts in prods.items():
            if brand in db_old['data'] and prodn in [p[0] for p in db_old['brands'][brand]]:
                for part in parts:
                    if part['part number'] in [p['part number'] for p in db_old['data'][brand][prodn]]:
                        changed_specs = []
                        part_old = [p for p in db_old['data'][brand][prodn] if p['part number'] == part['part number']][0]
                        for spec, v in part.items():
                            if spec == 'num_specs':
                                for num_spec, new_v in v.items():
                                    if num_spec in part_old['num_specs']:
                                        old_v = part_old['num_specs'][num_spec]
                                        if tuple(new_v) != tuple(old_v): changed_specs.append({
                                            'spec': num_spec,
                                            'is_num_spec': True,
                                            'before': old_v,
                                            'after': new_v,
                                        })
                            else:
                                old_v = part_old[spec] if spec in part_old else ''
                                if v != old_v: changed_specs.append({
                                    'spec': spec,
                                    'is_num_spec': False,
                                    'before': old_v,
                                    'after': v,
                                })
                        if changed_specs:
                            if brand not in changed: changed[brand] = {}
                            if prodn not in changed[brand]: changed[brand][prodn] = ([v[1] for v in db_new["brands"][brand] if v[0] == prodn][0], [])
                            changed[brand][prodn][1].append((part, changed_specs))

    #pprint(removed, width=125)
    changes = {
        'timestamp_old': db_old['metadata']['timestamp'],
        'added': added,
        'removed': removed,
        'changed': changed,
    }
    return changes

parser = argparse.ArgumentParser()
parser.add_argument('region')
parser.add_argument('region_short')
parser.add_argument('mp_threads', type=int)
parser.add_argument('-pw', '--password')
parser.add_argument('-p', '--print_progress', action='store_true')
parser.add_argument('-l', '--print_live_progress', action='store_true')
args = parser.parse_args()

BASE_URL = f'https://www.lenovo.com/{args.region}'
DB_DIR = f'./dbs'
DB_FILENAME = f'db_{args.region_short}.json'

NumSpec = namedtuple('NumSpec', ['value', 'unit'])

s = requests.Session()
s.headers.update({'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/86.0.4240.111 Safari/537.36'})

#db['data'] = {
#    'thinkpadx1': {
#        '22TP2X1X1C9': [
#            {
#                'spec': val,
#                'num_specs': {
#                    'num_spec': (num, 'unit'),
#                }, ...
#            }, ...
#        ], ...
#    }, ...
#}
db = {
    'metadata': {
        'region':       args.region,
        'short region': args.region_short,
        'base url':     BASE_URL,
    },
    # track changes per scrape
    'changes': {},
    # keep track of all keys encountered across all brands
    'keys': {
        'info': [],
        #'api_specs': [], # merged into 'info'
        'num_specs': [],
    },
    #{
    #    'brand': [
    #        ('product line num', 'product line name'), ...
    #    ], ...
    #}
    'brands': {},
    'data': {}
}

start = time.time()

if args.region in ['us/en/ticketsatwork', 'gb/en/gbepp']:
    print(f'Authenticating ticketsatwork...')
    if not args.password:
        print('\'args.region\' requires --password argument. Exiting...')
        sys.exit()
    #if args.region == 'us/en/ticketsatwork':
    #    passcode = 'TICKETSatWK'
    #elif args.region == 'gb/en/gbepp':
    #    passcode = 'lenovo2021epp'

    db['metadata']['passcode'] = args.password
    # authenticate with ticketsatwork
    payload = {
        'gatekeeperType': 'PasscodeGatekeeper',
        'passcode': passcode
        #'CSRFToken': csrf,
    }
    url = f"{BASE_URL}/gatekeeper/authGatekeeper"
    r = s.post(
        url,
        data=payload,
    )

# collect brands from seriesListPage api call
print(f'Collecting brands...')
series = [
    'THINKPAD' if args.region in ['gb/en', 'gb/en/gbepp'] else 'thinkpad',
    'IdeaPad',
    'legion-laptops',
]
brands = []
for ser in series:
    r = try_request(s, f'{BASE_URL}/c/{ser}/seriesListPage/json')
    d = json.loads(r.text)
    for brand_d in d[ser]:
        brands.append(brand_d['code'])
brands.extend([
    'thinkbook-series',
    'yoga',
])
[brands.remove(b) for b in [
    'thinkpadyoga',
    'thinkpadyoga-2',
    'thinkpad11e',
] if b in brands]
#brands = ['ideapad-s-series', 'IdeaPad-300', 'legion-7-series', 'ideapad-gaming-laptops']
print(f'Got {len(brands)} brands')

print(f'Scraping \'{args.region}\'...')
# return a list of tuple(data dicts, keys)
results = []
if args.mp_threads <= 1:
    for brand in brands:
        result, keys = process_brand(s, brand, args.print_progress, args.print_live_progress)
        results.append((result, keys))
else:
    with multiprocessing.Pool(args.mp_threads) as p:
        results = p.starmap(process_brand,
            zip(
                repeat(s),
                brands,
                repeat(args.print_progress),
                repeat(False),
            )
        )
        p.terminate()
        print('Pool terminated')
        p.join()

db['data'] = dict(zip(brands, [r[0] for r in results]))

# cleanup any empty brands/prodlines
empty_brands = []
empty_prodnums = {}
for brand, prods in db['data'].items():
    if prods == {'': []}:
        empty_brands.append(brand)
    # check for empty product lines
    for prodnum, parts in prods.items():
        if parts == []:
            if brand not in empty_prodnums: empty_prodnums[brand] = []
            empty_prodnums[brand].append(prodnum)
for empty_brand in empty_brands:
    print(f'\'{empty_brand}\' is empty. Deleting...')
    del db['data'][empty_brand]
for brand, prodnums in empty_prodnums.items():
    for prodnum in prodnums:
        print(f'\'{brand} - {prodnum}\' is empty. Deleting...')
        del db['data'][brand][prodnum]

# add product lines to brands
print(f'Getting product line titles...')
for brand, prods in db['data'].items():
    db['brands'][brand] = []
    for prod in prods.keys():
        # retrieve product line name via api
        r = try_request(s, f'{BASE_URL}/p/{prod}/specs/json')
        if r:
            d = json.loads(r.text)
            db['brands'][brand].append((prod, d['name'].replace('\u201d', '"')))
    if args.print_progress: print(brand)

# merge keys
for r in results:
    db['keys']['info'] = list(set(db['keys']['info'] + r[1]['info']))
    #db['keys']['api_specs'] = list(set(db['keys']['api_specs'] + r[1]['api_specs']))
    db['keys']['num_specs'] = list(set(db['keys']['num_specs'] + r[1]['num_specs']))
# remove num_specs key from info
db['keys']['info'].remove('num_specs')

# count and store total
total = 0
for r in results:
    brand = r[0]
    for prod, parts in brand.items():
        total += len(parts)
db['metadata']['total'] = total

db['metadata']['timestamp'] = time.time()

# retrieve and log changes
if os.path.exists(f'{DB_DIR}/{DB_FILENAME}'):
    with open(f'{DB_DIR}/{DB_FILENAME}', 'r') as f:
        js = f.read()
        db_old = json.loads(js)
        print(f'Found existing \'{DB_DIR}/{DB_FILENAME}\'')
    db['changes'] = get_changes(db, db_old)
    # backup old json file
    if not os.path.exists(f'{DB_DIR}/backup'): os.makedirs(f'{DB_DIR}/backup')
    new_filename = f'db_{args.region_short}_{datetime.fromtimestamp(db_old["metadata"]["timestamp"]).strftime("%m%d")}.json'
    os.rename(f'{DB_DIR}/{DB_FILENAME}', f'{DB_DIR}/backup/{new_filename}')
    print(f'Backed up \'{DB_DIR}/{DB_FILENAME}\' to \'{DB_DIR}/{new_filename}\'')

for k, v in db.items():
    if k in ['data', 'brands', 'changes']:
        print(f'{k} [{len(v)}]')
    else:
        print(k)
        for k1, v1 in v.items():
            print(f'  {k1:13} {v1}')
    #if k in ['data']:
    #    print(k)
    #    for k1, v1 in v.items():
    #        print(f'  {k1:13} {pformat(v1)}')
print()

# print scrape duration
duration_s = time.time()-start
duration_str = f'{int(duration_s/60)}m {int(duration_s%60)}s'
print(f'Scraped in {duration_str}')

if not os.path.exists(DB_DIR): os.makedirs(DB_DIR)
with open(f'{DB_DIR}/{DB_FILENAME}', 'w') as f:
    json.dump(db, f)
    print(f'Wrote to \'{DB_DIR}/{DB_FILENAME}\' on {time.strftime("%c")}')
