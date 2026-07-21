import csv, json, sys
sys.stdout.reconfigure(encoding="utf-8")

rows = list(csv.DictReader(open('eval/results/retrieval_metrics.csv', encoding='utf-8')))

# Questions that scored > 0 recall at k=4
hits = [r for r in rows if r.get('recall@4') and float(r['recall@4']) > 0]
misses = [r for r in rows if r.get('recall@4') and float(r['recall@4']) == 0]

print(f"=== Questions with recall@4 > 0: {len(hits)} ===")
for r in hits:
    print(f"  {r['id']:5s} | cat={r['category']:20s} | recall@4={float(r['recall@4']):.2f} | gold={r['gold_sources'][:60]}")

print(f"\n=== Questions with recall@4 = 0: {len(misses)} ===")
for r in misses:
    print(f"  {r['id']:5s} | cat={r['category']:20s} | gold={r['gold_sources'][:60]}")

print(f"\n=== Questions with NO metrics (out_of_scope_negative): {len(rows) - len(hits) - len(misses)} ===")
