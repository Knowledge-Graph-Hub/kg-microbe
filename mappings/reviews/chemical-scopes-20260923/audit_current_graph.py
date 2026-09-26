"""Count current graph references to identifiers lost from the frozen candidate."""
import argparse
import csv, hashlib, json
from collections import Counter, defaultdict
from pathlib import Path
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--data-root', type=Path, required=True)
parser.add_argument('--candidate-report', type=Path, required=True)
parser.add_argument('--output-directory', type=Path, required=True)
args = parser.parse_args()
data_root = args.data_root
out = args.output_directory
out.mkdir(parents=True, exist_ok=True)
report_path = args.candidate_report
report = json.loads(report_path.read_text())
lost = set(report['unreconstructed_entities'])
counts = defaultdict(Counter)
inputs = {}
summaries = {}
examples = defaultdict(list)
for path in sorted((data_root / 'transformed').rglob('*edges.tsv')):
    digest = hashlib.sha256()
    before = path.stat()
    total = touched = 0
    with path.open('rb') as stream:
        header = next(stream)
        digest.update(header)
        fields = header.decode().rstrip('\n\r').split('\t')
        si, oi, pi = (fields.index(k) for k in ('subject', 'object', 'predicate'))
        for line in stream:
            digest.update(line)
            row = line.decode().rstrip('\n\r').split('\t')
            total += 1
            hits = lost.intersection((row[si], row[oi]))
            if not hits:
                continue
            touched += 1
            for entity in hits:
                counts[entity][path.parent.name] += 1
                if len(examples[entity]) < 3:
                    examples[entity].append({'producer': path.parent.name, 'subject': row[si], 'predicate': row[pi], 'object': row[oi]})
    after = path.stat()
    assert (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns), f'Input changed: {path}'
    rel = str(Path('data') / path.relative_to(data_root))
    inputs[rel] = digest.hexdigest()
    summaries[rel] = {'rows_scanned': total, 'rows_touching_lost_entity': touched}
    print(rel, total, touched, flush=True)
with (out / 'coverage-current-graph.tsv').open('w') as stream:
    writer = csv.writer(stream, delimiter='\t', lineterminator='\n')
    writer.writerow(['identifier', 'current_producer_edge_rows', 'producer_counts', 'sample_edges'])
    for entity in sorted(lost):
        writer.writerow([entity, sum(counts[entity].values()), json.dumps(counts[entity], sort_keys=True), json.dumps(examples[entity], sort_keys=True)])
summary = {
 'scope': 'Observed references in all existing data/transformed/**/*edges.tsv to identifiers missing from the chemical-scope candidate; includes gitignored files. This is exposure, not predicted deletion or a post-promotion graph validation. Producers have not been rebuilt.',
 'candidate_sha256': report['candidate_sha256'],
 'candidate_report_sha256': hashlib.sha256(report_path.read_bytes()).hexdigest(),
 'lost_entities': len(lost), 'lost_entities_referenced': sum(bool(value) for value in counts.values()),
 'edge_rows_touching_lost_entity': sum(x['rows_touching_lost_entity'] for x in summaries.values()),
 'edge_rows_scanned': sum(x['rows_scanned'] for x in summaries.values()),
 'input_sha256': inputs, 'producer_tables': summaries,
}
(out / 'coverage-current-graph.json').write_text(json.dumps(summary, indent=2)+'\n')
print(json.dumps({k:v for k,v in summary.items() if k not in {'input_sha256','producer_tables'}}, indent=2))
