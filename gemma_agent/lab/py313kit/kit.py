# Builds python313.tar.gz (relocatable uv python 3.13) and image_wheels/ (the swebench-sandbox image's pip line)
# so GPU lab kernels, which cannot enable internet, can run the docker-like sandbox offline.
import glob, os, subprocess, sys, tarfile
out = "/kaggle/working/py313kit"; os.makedirs(out, exist_ok=True)
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "uv"], check=True)
uv = os.path.join(os.path.dirname(sys.executable), "uv")
if not os.path.exists(uv):
    import shutil; uv = shutil.which("uv")
subprocess.run([uv, "python", "install", "3.13"], check=True)
py = subprocess.run([uv, "python", "find", "3.13"], capture_output=True, text=True, check=True).stdout.strip()
root = os.path.dirname(os.path.dirname(os.path.realpath(py)))
print("python", py, "root", root, flush=True)
with tarfile.open(f"{out}/python313.tar.gz", "w:gz") as tf:
    tf.add(root, arcname=os.path.basename(root))
pkgs = ["pytest", "pytest-timeout==2.1.0", "typer", "pdm-backend", "setuptools", "wheel", "poetry-core",
        "hatchling", "flit-core", "editables"]
subprocess.run([py, "-m", "ensurepip"], check=False)
subprocess.run([py, "-m", "pip", "download", "-q", "-d", f"{out}/image_wheels", "--only-binary=:all:", *pkgs], check=True)
print(sorted(os.path.basename(p) for p in glob.glob(f"{out}/image_wheels/*.whl")))
# self-test: extract and run
subprocess.run(["bash", "-c", f"mkdir -p /tmp/t && tar xzf {out}/python313.tar.gz -C /tmp/t && /tmp/t/*/bin/python3.13 -c 'import sys,ssl,sqlite3;print(sys.version)'"], check=True)
print("kit ok", os.path.getsize(f"{out}/python313.tar.gz"))
