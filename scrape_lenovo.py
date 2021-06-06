import requests
import sys
import re
import json
import math
import datetime
import time
import multiprocessing
from bs4 import BeautifulSoup
from itertools import repeat
from collections import namedtuple
from html2text import html2text
from pprint import pprint

def try_request(s, url, wait_s=1):
    while True:
        r = s.get(url)
        if r.status_code == 200:
            return r
        else:
            #print(f'request {url} failed with {r.status_code}. Waiting {wait_s}s ...')
            #time.sleep(wait_s)
            #wait_s *= 2
            print(f'request {url} failed with {r.status_code} Exiting...')
            sys.exit()

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
        print(f'ERROR: No part number found for {prod}. Exiting...')
        sys.exit()
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
        'feature fingerprint reader': 'fingerprint reader',
        'feature for gaming':         'gaming',
        'feature optical drive':      'optical drive',
        'feature numeric keypad':     'keyboard',
        'feature touch screen':       'display',
        'formfactadapter_ag':         'graphics',
        'hard drive':                 'storage',
        'hdtype':                     'storage',
        'height_met':                 'height',
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
        'width_met':                  'width',
        'world facing camera':        'second camera',
        'wlan':                       'wireless',
    }
    spec_nums = {
        'ac adapter':        ('system common attributes', r'([\d\.]+) ?W',    int,   'W',  ['ac adapter']),
        'depth_met':         ('report usage',             r'([\d\.]+).*mm',   float, 'mm', ['depth']),
        'height_met':        ('report usage',             r'([\d\.]+) ?mm',   float, 'mm', ['thickness']),
        'hard drive':        ('facet features mtmcto',    r'(\d+) ?GB',       int,   'GB', ['storage']),
        'memory':            ('facet features mtmcto',    r'([\d\.]+) ?GB',   float, 'GB', ['memory']),
        'num_cores':         ('report usage',             r'(\d+)',           int,   '',   ['cpu cores']),
        'screen resolution': ('facet features mtmcto',    r'(\d+) ?x ?(\d+)', int,   'px', ['display res horizontal', 'display res vertical']),
        'screen size':       ('facet features mtmcto',    r'([\d\.]+)"',      float, 'in', ['display size']),
        'width_met':         ('report usage',             r'([\d\.]+) ?mm',   float, 'mm', ['width']),
        'weight in lbs':     ('facet features mtmcto',    r'([\d\.]+)',       float, 'lb', ['weight']),
    }
    spec_ignore = [
        'feature trackpoint',
        'form factor',
        'freeformfacet1',
        'freeformfacet2',
        'freeformfacet5',
        'longdesc_sec',
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

def process_brand(s, brand, print_progress=False):
    # returns dict with part numbers as key
    prods = {}
    # keep track of and return all keys encountered in this brand
    keys = {
        'info': [],
        #'api_specs': [], # merged into 'info'
        'num_specs': [],
    }

    start = time.time()
    if print_progress: print(brand, end='\r')

    if brand == 'yoga':
        r = try_request(s, f'{BASE_URL}/yoga/products')
        pcodes = []
        soup = BeautifulSoup(r.content, 'html.parser')
        for yoga in soup.select('section.yoga-list-convertibles'):
            pcodes.extend([p['data-article-test'] for p in yoga.select('*[data-article-test]')])
    else:
        r = try_request(s, f'{BASE_URL}/c/{brand}')
        soup = BeautifulSoup(r.content, 'html.parser')
        pcodes = soup.select_one('meta[name="subseriesPHimpressions"], meta[name="bundleIDimpressions"]')['content'].split(',')

    for pn in set(pcodes):
        prods[pn] = []

    print(f'{brand} ({len(prods)}) {time.time()-start:.1f}s')

    prod_count = 0
    cur_str = ''
    for prod, parts in prods.items():
        cur_str = f'{brand:22} ({prod_count+1:<2}/{len(prods):2}) {prod}'
        if print_progress: print(cur_str, end='\r')
        start = time.time()

        r = try_request(s, f'{BASE_URL}/p/{prod}')
        soup = BeautifulSoup(r.content, 'html.parser')

        cur_str += f' {time.time()-start:.1f}s'
        if print_progress: print(cur_str, end='\r')
        start = time.time()

        part_count = 0
        for prod in soup.select('li.tabbedBrowse-productListing-container, div.tabbedBrowse-module.singleModelView'):
            button = prod.select_one('form[id^="addToCartFormTop"] button[class*="tabbedBrowse-productListing-footer"]')
            if button:
                pn, info = get_info(prod, button)

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

                # collect and merge keys
                keys['info'] = list(set(keys['info'] + list(info.keys()))) 
                #keys['api_specs'] = list(set(keys['api_specs'] + list(info['api_specs'].keys())))
                keys['num_specs'] = list(set(keys['num_specs'] + list(info['num_specs'].keys())))

                parts.append(info)

                part_count += 1
                if print_progress: print(f'{cur_str} {"#"*part_count}{part_count}\r', end='\r')
        print(f'{cur_str:46} {"#"*part_count}{part_count} {time.time()-start:.1f}s')
        prod_count += 1

    # clean up any empty prods e.g. from url redirect
    #new_prods = {}
    #for prod, parts in prods.items():
    #    print(parts)
    #    if parts: new_prods[prod] = parts

    return prods, keys

NumSpec = namedtuple('NumSpec', ['value', 'unit'])

BASE_URL = 'https://www.lenovo.com/us/en/ticketsatwork'
DB_FILENAME = 'db.json'

s = requests.Session()
s.headers.update({'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/86.0.4240.111 Safari/537.36'})
# https://www.lenovo.com/us/en/ticketsatwork/p/20XW003EUS/specs/json
# https://www.lenovo.com/us/en/ticketsatwork/p/20XW003EUS/singlev2/price/json

#db = {
#    'metadata': {},
#    'keys': {},
#    'data': {
#        'thinkpadx1': {
#            '22TP2X1X1C9': [
#                {
#                    'spec':     val,
#                    'num_specs': {
#                        'num_spec': (num, 'unit'),
#                    },
#                },
#            ],
#        },
#    }
#}
db = {
    'metadata': {
        'base url': BASE_URL,
    },
    'keys': {},
    'data': {}
}

if 'ticketsatwork' in BASE_URL:
    passcode = 'TICKETSatWK'
    db['metadata']['passcode'] = passcode
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

brands = [
    'thinkpadx1',
    'thinkpadp',
    'thinkpadt',
    'thinkpadx',
    'thinkpade',
    'thinkpadl',
    'thinkpadc',
    'thinkbook-series',
    'yoga',
    'IdeaPad-100',
    'IdeaPad-Flex-Series',
    'IdeaPad-300',
    'IdeaPad-500',
    'Ideapad-700',
    'ideapad-900-series',
    'ideapad-gaming-laptops',
    'legion-laptops-series',
    'legion-5-series',
    'legion-7-series',
]
#brands = ['thinkpadc', 'IdeaPad-100', 'ideapad-gaming-laptops']

# keep track of all keys encountered across all brands
db['keys'] = {
    'info': [],
    #'api_specs': [], # merged into 'info'
    'num_specs': [],
}

# return a list of tuple(brand dicts, keys)
results = []
#for brand in brands:
#    result, keys = process_brand(s, brand, True)
#    results.append((result, keys))
with multiprocessing.Pool(4) as p:
    results = p.starmap(process_brand, zip(repeat(s), brands))
    p.terminate()
    p.join()

# merge keys
for r in results:
    db['keys']['info'] = list(set(db['keys']['info'] + r[1]['info']))
    #db['keys']['api_specs'] = list(set(db['keys']['api_specs'] + r[1]['api_specs']))
    db['keys']['num_specs'] = list(set(db['keys']['num_specs'] + r[1]['num_specs']))
# remove num_specs key from info
db['keys']['info'].remove('num_specs')

db['data'] = dict(zip(brands, [r[0] for r in results]))
db['metadata']['timestamp'] = time.time()

# count and store total
total = 0
for r in results:
    brand = r[0]
    for prod, parts in brand.items():
        total += len(parts)
db['metadata']['total'] = total

print()
for brand, prods in db['data'].items():
    print(f'{brand} ({len(prods)})')
    #for prod, parts in prods.items():
    #    print(f'  {prod} ({len(parts)})')
        #for part in parts:
        #    first = True
        #    for name, val in part.items():
        #        if name in ['specs', 'api_specs', 'num_specs']:
        #            print(f'      {name+":":9}')
        #            for spec, val in val.items():
        #                print(f'        {spec+":":28} {val}')
        #        else:
        #            if first: print('    [ ', end='')
        #            else:     print('      ', end='')
        #            first = False
        #            print(f'{name+":":9} {val}')
        #    print('    ],')
print('keys')
for k, v in db['keys'].items():
    print(f'  {k:10} {v}')
print('metadata')
for k, v in db['metadata'].items():
    print(f'  {k:10} {v}')

with open(DB_FILENAME, 'w') as f:
    json.dump(db, f)
