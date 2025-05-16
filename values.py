import os
import re


apps = "charts/apps/values"

envs = [
    "dev",
    "eng",
    "prd",
]

for env in envs:
    data_centers = os.listdir(f"{apps}/{env}")
    for data_center in data_centers:
        if data_center == "all.yaml":
            continue
        for cluster in os.listdir(f"{apps}/{env}/{data_center}"):
            cluster_file = f"{apps}/{env}/{data_center}/{cluster}"

            print(f"\n---\nProcessing {cluster_file}")

            with open(cluster_file, "r") as f:
                content = f.read()

            if "openPlatformAgent" not in content:
                print(
                    f"Open Platform Agent not found in {env}/{data_center}/{cluster}")
                after_apps = False
                previous_app = ""
                for line in content.split("\n"):
                    if line.strip() == "apps:":
                        after_apps = True
                    if not after_apps:
                        continue  # only check after "apps:" line
                    if not re.match(r"^  [a-z]", line):
                        continue  # "  prometheusStack:"
                    current_app = line.strip()  # "prometheusStack:"
                    if current_app > "openPlatformAgent" and previous_app < "openPlatformAgent":
                        print(f"add between {previous_app} and {current_app}")
                        content = content.replace(line, "  openPlatformAgent:\n    enabled: true\n\n" + line)
                    previous_app = current_app

                with open(cluster_file, "w") as f:
                    f.write(content)
