#!/usr/bin/env python3
"""Read-only link/default-route snapshot; no connections, passwords or writes."""
import datetime
import json
import os
import subprocess


def fields(line):
    """Parse nmcli terse escaping, including literal colon and backslash."""
    result, current, escaped = [], '', False
    for char in line:
        if escaped:
            current += char
            escaped = False
        elif char == '\\':
            escaped = True
        elif char == ':':
            result.append(current)
            current = ''
        else:
            current += char
    if escaped:
        raise ValueError('Incomplete nmcli escape')
    return result + [current]


def devices(raw):
    rows = []
    for line in raw.splitlines():
        if not line:
            continue
        values = fields(line)
        if len(values) != 3:
            raise ValueError('Unexpected nmcli device status format')
        interface, kind, state = values
        if kind in ('ethernet', 'wifi'):
            rows.append({'interface': interface, 'type': kind, 'state': state})
    return rows


def routes(raw, family):
    items = json.loads(raw)
    if not isinstance(items, list):
        raise ValueError('Unexpected ip route format')
    rows = []
    for item in items:
        if item.get('dst') not in ('default', '0.0.0.0/0', '::/0'):
            continue
        for hop in item.get('nexthops', [item]):
            rows.append({'family': family, 'interface': hop.get('dev', item.get('dev', '—')),
                         'gateway': hop.get('gateway', item.get('gateway', 'on-link')),
                         'metric': item.get('metric'), 'table': item.get('table', 'main'),
                         'flags': hop.get('flags', item.get('flags', []))})
    return rows


def read(argv):
    result = subprocess.run(argv, capture_output=True, text=True, timeout=3,
                            env=dict(os.environ, LC_ALL='C'), check=True)
    if len(result.stdout) > 1024 * 1024:
        raise ValueError('Unexpectedly large network response')
    return result.stdout


def snapshot():
    out = {'devices': [], 'routes': [], 'errors': [],
           'at': datetime.datetime.now().astimezone().isoformat(timespec='seconds')}
    jobs = [('NetworkManager', ['nmcli', '--terse', '--escape', 'yes', '--fields', 'DEVICE,TYPE,STATE', 'device', 'status'], devices, 'devices')]
    jobs += [(family, ['ip', '-j', flag, 'route', 'show', 'table', 'all', 'default'],
              lambda raw, family=family: routes(raw, family), 'routes') for family, flag in [('IPv4', '-4'), ('IPv6', '-6')]]
    for label, argv, parse, target in jobs:
        try:
            out[target].extend(parse(read(argv)))
        except (OSError, subprocess.SubprocessError, ValueError, TypeError, AttributeError) as error:
            detail = getattr(error, 'stderr', None) or str(error)
            out['errors'].append(label + ': ' + ' '.join(detail.split())[:240])
    return out


if __name__ == '__main__':
    print(json.dumps(snapshot(), ensure_ascii=False))
