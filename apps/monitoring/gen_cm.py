import json, os

dashboard_dir = "/home/frhnardi/Projects/paved-road-platform/platform-gitops/apps/monitoring/dashboards"
dashboards = {}

for f in sorted(os.listdir(dashboard_dir)):
    if f.endswith('.json'):
        name = f.replace('.json', '')
        with open(os.path.join(dashboard_dir, f)) as fh:
            data = json.load(fh)
        dashboards[f"{name}.json"] = json.dumps(data)

print("""apiVersion: v1
kind: ConfigMap
metadata:
  name: grafana-dashboards
  namespace: monitoring
  labels:
    grafana_dashboard: "1"
data:""")

for filename, content in dashboards.items():
    indented = content.replace('\n', '\n    ')
    print(f'  {filename}: |')
    print(f'    {indented}')
