"""Build the Companion's offline name index from an OpenNGC checkout."""
import argparse
import csv
import re
from pathlib import Path


def designation(name):
    match = re.fullmatch(r'(NGC|IC|M|B|C)\s*(\d+)(.*)', name)
    if match:
        return f'{match[1]} {int(match[2])}{match[3]}'
    return name


def angle(value):
    first, minutes, seconds = map(float, value.lstrip('+-').split(':'))
    absolute = first + minutes / 60 + seconds / 3600
    return -absolute if value.startswith('-') else absolute


def generate(source, destination):
    rows = []
    for filename in ('NGC.csv', 'addendum.csv'):
        with (source / 'database_files' / filename).open(encoding='utf-8', newline='') as infile:
            rows.extend(csv.DictReader(infile, delimiter=';'))

    duplicates = {}
    for row in rows:
        if row['Type'] == 'Dup':
            for catalog in ('NGC', 'IC'):
                if row[catalog]:
                    duplicates.setdefault(catalog + row[catalog], []).append(designation(row['Name']))

    with destination.open('w', encoding='utf-8', newline='') as outfile:
        writer = csv.writer(outfile, lineterminator='\n')
        writer.writerow(('name', 'ra_deg', 'dec_deg', 'aliases'))
        for row in rows:
            if row['Type'] in ('Dup', 'NonEx') or not row['RA'] or not row['Dec']:
                continue
            name = designation(row['Name'])
            aliases = set(filter(None, (s.strip() for s in row['Common names'].split(','))))
            aliases.update(duplicates.get(row['Name'], ()))
            for catalog in ('M', 'NGC', 'IC'):
                aliases.update(designation(catalog + n.strip()) for n in row[catalog].split(',') if n.strip())
            for ident in map(str.strip, row['Identifiers'].split(',')):
                if re.fullmatch(r'(C|B)\s*\d+|SH\s*2-\d+', ident, re.IGNORECASE):
                    aliases.add(designation(ident))
            aliases.discard(name)
            writer.writerow((name, f"{15 * angle(row['RA']):.6f}", f"{angle(row['Dec']):.6f}",
                             '|'.join(sorted(aliases))))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, help='OpenNGC repository directory')
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    generate(args.source, args.destination)
