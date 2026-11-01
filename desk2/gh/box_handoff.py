"""One-time cutover: the box desk acts as predecessor 'box' for the first Actions run.
Waits for refs/heads/handoff-desk2 {pred:'box'}, stops the box supervisors + desk + ngrok, snapshots desk.db + logs
(encrypted) to `state-desk2` with released_for=<run>. If the push fails, the box desk is restarted (stays the live desk)."""
import json, os, signal, subprocess, sys, time
sys.path.insert(0, os.path.dirname(__file__))
import runner as R

BOX = "/workspace/desk2"

def pid(f):
    try: return int(open(f"{BOX}/logs/{f}").read().strip())
    except Exception: return None

def stop_box():
    for f in ("ngrok_supervisor.pid", "desk_supervisor.pid"):
        p = pid(f)
        if p:
            try: os.kill(p, signal.SIGTERM)
            except ProcessLookupError: pass
    subprocess.run(["pkill", "-f", "ngrok http 8787"]); subprocess.run(["pkill", "-f", "python -m desk.main"])
    t = time.time()
    while time.time() - t < 6 and subprocess.run(["pgrep", "-f", "desk.main|ngrok http 8787"], capture_output=True).returncode == 0:
        time.sleep(0.3)
    subprocess.run(["pkill", "-9", "-f", "desk.main|ngrok http 8787"])

def start_box():
    for s in ("desk_supervisor.sh", "ngrok_supervisor.sh"):
        subprocess.Popen(["setsid", "nohup", "bash", f"bin/{s}"], cwd=BOX, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def main():
    last = R.remote_sha(R.REQ_REF)
    R.log("box waiting for a handoff request (pred=box)")
    t0 = time.time()
    while time.time() - t0 < 40 * 60:
        sha = R.remote_sha(R.REQ_REF)
        if sha and sha != last:
            last = sha
            req = json.loads(R.fetch_file(R.REQ_REF, "req.json") or b"{}")
            if req.get("pred") == "box" and req.get("succ"):
                R.log("handoff requested by run", req["succ"])
                stop_box(); t = time.time()
                try:
                    R.save_state("box", released_for=req["succ"], stopped_at=t, note="box cutover")
                except Exception as e:
                    R.log("state push FAILED -> restarting box desk:", e); start_box(); sys.exit(1)
                R.log(f"released to {req['succ']} (stop->pushed {time.time() - t:.1f} s)")
                return
        time.sleep(2)
    R.log("no request within 40 min; box desk untouched"); sys.exit(2)

if __name__ == "__main__":
    main()
