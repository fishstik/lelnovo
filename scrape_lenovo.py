import argparse
import requests
import urllib
import sys
import re
import json
import math
import time
import multiprocessing
import os, shutil
from bs4 import BeautifulSoup
from itertools import repeat
from collections import namedtuple
from datetime import datetime
from html2text import html2text
from pprint import pprint, pformat

def try_request(s, url, wait_s=1, tries=3):
    global FORBIDDEN_COUNT

    while tries > 0:
        r = s.get(url)
        if r.status_code == 200:
            return r
        else:
            print(f'request {url} failed with code {r.status_code}')
            if r.status_code == 404:
                return None
            elif r.status_code == 403:
                FORBIDDEN_COUNT += 1
                return None
            else:
                tries -= 1
                print(f'Waiting {wait_s}s and trying again ({tries} left) ...')
                time.sleep(wait_s)
                wait_s *= 2
                #print(f'request {url} failed with {r.status_code} Exiting...')
                #sys.exit() #FIXME: terminate mp parent if child is exiting
    return None

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
    specs = {}
    num_specs = {}

    spec_merge = {
        'battery':                    'battery',
        'blue tooth':                 'bluetooth',
        'body color':                 'color',
        'depth_met':                  'depth',
        'display type':               'display',
        'feature backlit keyboard':   'keyboard',
        'feature convertible':        'convertible',
        'fingerprint reader':         'fp reader',
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
    try:
        d = json.loads(r.text)
    except BaseException as e:
        print(f'Error parsing \'{BASE_URL}/p/{pn}/specs/json\':\n{e}')
        return specs, num_specs

    all_specs = []
    for feature_types_d in d['classificationData']:
        feature_type = feature_types_d['name']
        if 'featureDataDTO' in feature_types_d:
            for feature_d in feature_types_d['featureDataDTO']:
                feature_val = feature_d['featureValues'][0]['value'].encode('ascii', 'ignore').decode('ascii') # clean up unicode
                all_specs.append((feature_d['name'], feature_val, feature_type))

    # merge/clean up specs
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

def get_brands(s, region):
    # collect brands from seriesListPage api call
    series = [
        'THINKPAD' if region in ['gb/en', 'gb/en/gbepp'] else 'thinkpad',
        'IdeaPad',
        'legion-laptops',
    ]
    brands = []
    for ser in series:
        r = try_request(s, f'{BASE_URL}/c/{ser}/seriesListPage/json')
        if r:
            d = json.loads(r.text)
            for brand_d in d[ser]:
                brands.append(brand_d['code'])
    brands.extend([
        'thinkbook-series',
        'yoga-2-in-1-series',
        'yoga-slim-series',
    ])
    [brands.remove(b) for b in [
        'thinkpadyoga',
        'thinkpadyoga-2',
        'thinkpad11e',
    ] if b in brands]
    #brands = ['IdeaPad-300']

    return brands

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
    r = try_request(s, f'{BASE_URL}/c/products/json?categoryCodes={brand}')
    try:
        d = json.loads(r.text)
        if brand in d: pcodes.extend([p['code'] for p in d[brand]])
    except BaseException as e:
        print(f'Error parsing \'{BASE_URL}/c/products/json?categoryCodes={brand}\':\n{e}')

    if pcodes:
        for pn in set(pcodes):
            prods[pn] = []
    else:
        print(f'No pcodes found for \'{brand}\'')
        return prods, keys

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
                    # get pn, name, shipping info from html scrape
                    res = get_info(prod, button)
                    if res:
                        pn, info = res

                        # get specs from api call
                        api_specs, num_specs = get_api_specs(s, pn)

                        # get price info from api call
                        r = try_request(s, f'{BASE_URL}/p/{pn}/singlev2/price/json')
                        try:
                            d = json.loads(r.text)
                            currency = d['currencySymbol']
                            if d['eCoupon']: info['coupon'] = d['eCoupon']
                            price_str = d['startingAtPrice']
                            for ch in [currency, ',']:
                                if ch in price_str: price_str = price_str.replace(ch, '')
                            num_specs['price'] = NumSpec(float(price_str), currency)
                        except BaseException as e:
                            print(f'Error parsing \'{BASE_URL}/p/{pn}/singlev2/price/json\':\n{e}')

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

def scrape_openapi(s, region, brand_merge):
    data = {}
    # keep track of and return all keys encountered in this brand
    keys = {
        'info': set(),
        'num_specs': set(),
    }
    total = 0

    spec_merge = {
        'fingerprint reader':  'fp reader',
        'nb_wwan':             'wwan',
        'second storage':      'storage',
        'wlan':                'wireless',
        'world facing camera': 'second camera',
    }
    spec_ignore = [
        'pointing device',
    ]

    pages = float('inf')
    page = 1
    while page <= pages:
        payload = json.dumps({
            "classificationGroupIds":"800001",
            "pageFilterId":"6999c7d0-bccf-4160-91d2-90a8288f8365",
            "page":str(page),
            "pageSize":"40",
        })
        r = s.post(f'https://openapi.lenovo.com/{region}/ofp/search/dlp/product/query', data=payload)
        if r:
            d = json.loads(r.text)
            if d and 'data' in d and d['data'] and 'data' in d['data']:
                for p in d['data']['data']:
                    # locate prod by capitalization and length, assume brand always precedes it in categoryPath
                    prod = ''
                    for i in range(0, len(p['categoryPath'])-1):
                        step = p['categoryPath'][i+1]
                        m = re.match(r'[A-Z0-9]+', step)
                        if m and (prod == '' or len(m.group(0)) < len(prod)):
                            prod = m.group(0)
                            break

                    brand = p['categoryPath'][i]
                    name = p['summary']
                    if brand in brand_merge: brand = brand_merge[brand]
                    if brand not in data: data[brand] = {}
                    if prod not in data[brand]: data[brand][prod] = []
                    if p['productCode'] in [p['part number'] for p in data[brand][prod]]:
                        print(f'Skipping duplicate \'{p["productCode"]}\'')
                    elif 'classification' not in p or 'processor' not in [k['a'].lower() for k in p['classification']]:
                        print(f'Skipping \'{p["productCode"]}\' (no processor in specs)')
                    else:
                        info = {
                            'part number': p['productCode'],
                            'name': name,
                            'status': p['marketingStatus'],
                        }
                        if 'leadTime' in p: info['shipping'] = f"Ships in {p['leadTime']} days"
                        if 'couponCode' in p: info['coupon'] = p['couponCode']
                        #info['image url'] = p['media']['heroImage']['imageAddress'][2:]

                        # classification specs
                        for spec in p['classification']:
                            spec_name = spec['a'].lower()
                            spec_value = spec['b'].strip()

                            # clean up spec value
                            spec_value = re.sub(r'<br>|<\/br>', ', ', spec_value)
                            spec_value = re.sub(r'®|™', '', spec_value)
                            spec_value = re.sub(r'\\n', ' ', spec_value)
                            spec_value = html2text(spec_value).strip()

                            # merge specs
                            if spec_name not in spec_ignore:
                                if spec_name in spec_merge: spec_name = spec_merge[spec_name]
                                if spec_name not in info: info[spec_name] = spec_value
                                else:
                                    for word in spec_value.split():
                                        if word.lower() not in info[spec_name].lower():
                                            info[spec_name] += f' {word}'

                        # numeric specs
                        info['num_specs'] = {
                            'price': NumSpec(float(p['finalPrice']), p['currencySymbol']),
                        }

                        #print(f'{brand} | {prod} | {info["part number"]} | {name}')
                        data[brand][prod].append(info)

                        keys['info'].update(info.keys())
                        keys['num_specs'].update(info['num_specs'].keys())

                        total += 1

                pages = int(d['data']['pageCount'])
                print(f"Got {len(d['data']['data'])} parts from page {d['data']['page']}/{pages}")
                if pages > 100:
                    print(f'Error: openapi request returned {pages} pages (>100). Exiting...')
                    sys.exit()
        else:
            print(f'Error: {r.status_code}')
        page += 1

    # merge keys
    keys['info'] = list(keys['info'])
    keys['info'].remove('num_specs')
    keys['num_specs'] = list(keys['num_specs'])

    return data, keys, total

def get_prodnames_openapi(s, region, brand_merge):
    brands = {}
    pages = float('inf')
    page = 1
    while page <= pages:
        params = {
            'params': urllib.parse.quote('{\
                "pageFilterId":"a7b024c8-a164-4c56-b65e-0c20fe323ada",\
                "page":'+str(page)+',\
                "pageSize":40\
            }')
        }
        r = s.get(f'https://openapi.lenovo.com/{region}/ofp/search/dlp/product/query/get/_tsc', params=params)
        if r:
            d = json.loads(r.text)
            if d and 'data' in d and d['data'] and 'data' in d['data']:
                for p in d['data']['data']:
                    brand = p['categoryPath'][-1]
                    if brand in brand_merge: brand = brand_merge[brand]
                    if brand not in brands: brands[brand] = []

                    prodnum = p['productCode']

                    prodname = p['summary'].replace('\u201d', '"')
                    prodname = re.sub(r'(\|.*|laptop|2 in 1|2-in-1|mobile workstation|high performance|gaming|tablet|pc)', '', prodname, flags=re.I)
                    prodname = prodname.strip()

                    brands[brand].append((prodnum, prodname))

                pages = int(d['data']['pageCount'])
                print(f"Got {len(d['data']['data'])} product lines from page {d['data']['page']}/{pages}")
        else:
            print(f'Error: {r.status_code}')
        page += 1

    return brands

#returns changes = {
#    'timestamp_old' = ts,
#    'added':   { 'brand': { 'prodn': ('prodname', [part_d, ... ]), ... }, ... },
#    'removed': { 'brand': { 'prodn': ('prodname', [part_d, ... ]), ... }, ... },
#    'changed': { 'brand': { 'prodn': ('prodname', [(part_d, [ {'spec': str, 'is_num_spec': bool, 'before': str, 'after': str}, ... ], ... ), ... ]) }, ... }
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
                    if prodn not in added[brand]: added[brand][prodn] = ([v[1] for v in db_new["brands"][brand] if v[0] in prodn][0], [])
                    added[brand][prodn][1].extend(new_parts)
            else: # new brand or prodn, count all
                if brand not in added: added[brand] = {}
                if prodn not in added[brand]: added[brand][prodn] = ([v[1] for v in db_new["brands"][brand] if v[0] in prodn][0], [])
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
                        if prodn not in removed[brand]: removed[brand][prodn] = ([v[1] for v in db_old["brands"][brand] if v[0] in prodn][0], [])
                        removed[brand][prodn][1].extend(removed_parts)
                else: # entire prodn removed, count all
                    if brand not in removed: removed[brand] = {}
                    if prodn not in removed[brand]: removed[brand][prodn] = ([v[1] for v in db_old["brands"][brand] if v[0] in prodn][0], [])
                    removed[brand][prodn][1].extend(removed_parts)
        else: # entire brand removed, count all
            if brand not in removed: removed[brand] = {}
            for prodn, parts in prods.items():
                if prodn not in removed[brand]: removed[brand][prodn] = ([v[1] for v in db_old["brands"][brand] if v[0] in prodn][0], [])
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
                            if prodn not in changed[brand]: changed[brand][prodn] = ([v[1] for v in db_new["brands"][brand] if v[0] in prodn][0], [])
                            changed[brand][prodn][1].append((part, changed_specs))

    #pprint(removed, width=125)
    changes = {
        'timestamp_old': db_old['metadata']['timestamp'],
        'added': added,
        'removed': removed,
        'changed': changed,
    }
    return changes

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('region')
    parser.add_argument('region_short')
    parser.add_argument('mp_threads', type=int)
    parser.add_argument('-o', '--openapi', action='store_true')
    parser.add_argument('-pw', '--password')
    parser.add_argument('-p', '--print_progress', action='store_true')
    parser.add_argument('-l', '--print_live_progress', action='store_true')
    args = parser.parse_args()

    BASE_URL = f'https://www.lenovo.com/{args.region}'
    DB_DIR = f'./dbs'
    DB_FILENAME = f'db_{args.region_short}.json'
    FORBIDDEN_COUNT = 0

    NumSpec = namedtuple('NumSpec', ['value', 'unit'])

    s = requests.Session()
    s.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/93.0.4577.82 Safari/537.36',
        'referer': 'https://www.lenovo.com/',
    })

    db = {
        'metadata': {
            'region':       args.region,
            'short region': args.region_short,
            'base url':     BASE_URL,
        },
        # track changes per scrape
        'changes': {},
        # flatten prices for fast history lookup
        'prices': {},
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
        #{
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
        'data': {}
    }

    start = time.time()

    if args.region in ['us/en/ticketsatwork', 'gb/en/gbepp']:
        print(f'Authenticating \'{args.region}\'...')
        if not args.password:
            print(f'\'{args.region}\' requires --password argument. Exiting...')
            sys.exit()

        db['metadata']['passcode'] = args.password
        # authenticate with passcode-protected sites
        payload = {
            'gatekeeperType': 'PasscodeGatekeeper',
            'passcode': args.password
            #'CSRFToken': csrf,
        }
        url = f"{BASE_URL}/gatekeeper/authGatekeeper"
        r = s.post(
            url,
            data=payload,
        )

    # openapi scrape
    brand_merge = {
        'thinkbook-series': 'thinkbook',
    }
    if args.openapi:
        print(f'Scraping \'{args.region}\' (openapi)...')
        data, keys, total = scrape_openapi(s, args.region, brand_merge)
        db['data'] = data
        db['keys'] = keys
        db['metadata']['total'] = total

        # retrieve product line names
        print(f'Getting product line names (openapi)...')
        db['brands'] = get_prodnames_openapi(s, args.region, brand_merge)

        # check against data and correct data
        prodn_corrections = []
        for brand, prods in db['data'].items():
            for prod, parts in prods.items():
                #for part in parts:
                if brand in db['brands']:
                    found = False
                    for brandprod in db['brands'][brand]:
                        if brandprod[0] == prod:
                            found = True
                            break
                        elif brandprod[0] in prod:
                            prodn_corrections.append({
                                'brand': brand,
                                'prodn_old': prod,
                                'prodn_new': brandprod[0],
                            })
                            found = True
                            break
                    if not found: print(f'WARNING: \'{prod}\' from data not in db[\'brands\'][{brand}]')
                else:
                    print(f'WARNING: \'{brand}\' in data not in db[\'brands\']')
        for correction in prodn_corrections:
            ps = db['data'][correction['brand']][correction['prodn_old']]
            db['data'][correction['brand']][correction['prodn_new']] = ps
            del db['data'][correction['brand']][correction['prodn_old']]
            print(f'Corrected data prodnum \'{correction["prodn_old"]}\' to \'{correction["prodn_new"]}\'')

    # regular scrape
    else:
        print(f'Collecting brands...')
        brands = get_brands(s, args.region)
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

        # retrieve product line names
        print(f'Getting product line names...')
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

    # flatten price info
    for brand, prods in db['data'].items():
        for prod, parts in prods.items():
            for part in parts:
                db['prices'][part['part number']] = part['num_specs']['price']

    # retrieve and log changes
    if os.path.exists(f'{DB_DIR}/{DB_FILENAME}'):
        with open(f'{DB_DIR}/{DB_FILENAME}', 'r') as f:
            js = f.read()
            db_old = json.loads(js)
            print(f'Found existing \'{DB_DIR}/{DB_FILENAME}\'')
        db['changes'] = get_changes(db, db_old)

    # print db summary
    for k, v in db.items():
        if k in ['data', 'brands', 'changes', 'prices']:
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

    if FORBIDDEN_COUNT > 0:
        print(f'WARNING: Got {FORBIDDEN_COUNT} 403 Forbidden errors while scraping.')
        filename = f'db_{args.region_short}_{datetime.fromtimestamp(db["metadata"]["timestamp"]).strftime("%m%d")}_{FORBIDDEN_COUNT}FORBIDDENS.json'
        with open(filename, 'w') as f:
            json.dump(db, f)
            print(f'Wrote temp-banned db to \'./{filename}\' on {time.strftime("%c")}')
    else:
        if not os.path.exists(DB_DIR): os.makedirs(DB_DIR)
        # backup old json file
        if db['changes']:
            if not os.path.exists(f'{DB_DIR}/backup'): os.makedirs(f'{DB_DIR}/backup')
            new_filename = f'db_{args.region_short}_{datetime.fromtimestamp(db_old["metadata"]["timestamp"]).strftime("%y%m%d")}.json'
            shutil.copyfile(f'{DB_DIR}/{DB_FILENAME}', f'{DB_DIR}/backup/{new_filename}')
            print(f'Backed up \'{DB_DIR}/{DB_FILENAME}\' to \'{DB_DIR}/backup/{new_filename}\'')

        # write new json file
        with open(f'{DB_DIR}/{DB_FILENAME}', 'w') as f:
            json.dump(db, f)
            print(f'Wrote to \'{DB_DIR}/{DB_FILENAME}\' on {time.strftime("%c")}')
