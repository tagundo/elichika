import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.parse import urlsplit

ROOTS = {
    "amd64": ["https://archive.ubuntu.com/ubuntu", "https://mirrors.edge.kernel.org/ubuntu",
              "https://mirrors.mit.edu/ubuntu", "https://mirror.math.princeton.edu/pub/ubuntu",
              "https://mirrors.tuna.tsinghua.edu.cn/ubuntu"],
    "arm64": ["https://ports.ubuntu.com/ubuntu-ports", "https://mirrors.edge.kernel.org/ubuntu-ports",
              "https://mirrors.mit.edu/ubuntu-ports", "https://mirror.math.princeton.edu/pub/ubuntu-ports",
              "https://mirrors.tuna.tsinghua.edu.cn/ubuntu-ports", "https://mirrors.ustc.edu.cn/ubuntu-ports"],
}


def ubuntu_uri(value):
    if value.startswith("mirror+file:"):
        return bool(re.fullmatch(r"mirror\+file:/etc/apt/apt-mirrors(?:[-a-z0-9_]*)\.txt", value))
    parsed = urlsplit(value)
    return ((parsed.hostname or "").endswith(".ubuntu.com") and parsed.path.rstrip("/") in ("/ubuntu", "/ubuntu-ports")
            or value.rstrip("/") in {url for roots in ROOTS.values() for url in roots}
            or value == "mirror://mirrors.ubuntu.com/mirrors.txt")


def rewrite_sources(text, selected):
    result = []
    for paragraph in text.split("\n\n"):
        uri = re.search(r"(?m)^URIs:[ \t]*([^\n]+)$", paragraph)
        suites = re.search(r"(?m)^Suites:[ \t]*([^\n]+)$", paragraph)
        disabled = re.search(r"(?im)^Enabled:\s*no\s*$", paragraph)
        if not uri or not suites or disabled or not all(ubuntu_uri(value) for value in uri.group(1).split()):
            result.append(paragraph)
            continue
        groups = [(False, []), (True, [])]
        for suite in suites.group(1).split():
            groups[int(suite.endswith("-security"))][1].append(suite)
        for security, values in groups:
            if values:
                changed = re.sub(r"(?m)^URIs:[^\n]+$", "URIs: " + selected["security" if security else "main"], paragraph)
                changed = re.sub(r"(?m)^Suites:[^\n]+$", "Suites: " + " ".join(values), changed)
                result.append(changed)
    return "\n\n".join(result)


def rewrite_list(text, selected):
    result = []
    for line in text.splitlines(keepends=True):
        match = re.match(r"^(\s*deb(?:-src)?\s+(?:\[[^]\n]*\]\s+)?)(\S+)(\s+)(\S+)(.*?)(\n?)$", line)
        if match and ubuntu_uri(match.group(2)):
            base = selected["security" if match.group(4).endswith("-security") else "main"]
            line = match.group(1) + base + match.group(3) + match.group(4) + match.group(5) + match.group(6)
        result.append(line)
    return "".join(result)


def verified_mirror(candidates, suites, directory, attempts):
    for base in dict.fromkeys(candidates):
        valid = True
        for suite in suites:
            target = directory / (hashlib.sha256((base + suite).encode()).hexdigest() + ".InRelease")
            url = base + "/dists/" + suite + "/InRelease"
            result = subprocess.run(["curl", "--fail", "--silent", "--show-error", "--location",
                "--connect-timeout", "5", "--max-time", "15", "--output", str(target), url],
                capture_output=True, text=True, timeout=20)
            record = {"url": url, "curl_exit": result.returncode, "curl_error": result.stderr[-1200:]}
            if result.returncode == 0:
                signature = subprocess.run(["gpgv", "--keyring", "/usr/share/keyrings/ubuntu-archive-keyring.gpg", str(target)],
                    capture_output=True, text=True, timeout=15)
                record.update(gpgv_exit=signature.returncode, gpgv=signature.stderr[-2000:])
                valid = signature.returncode == 0
            else:
                valid = False
            attempts.append(record)
            if not valid:
                break
        if valid:
            return base
    raise RuntimeError("No reachable, Ubuntu-signature-verified mirror serves " + ", ".join(suites))


def main():
    evidence = Path(os.environ["ELICHIKA_APT_EVIDENCE"])
    evidence.mkdir(parents=True, exist_ok=True)
    arch = subprocess.check_output(["dpkg", "--print-architecture"], text=True).strip()
    if arch not in ROOTS:
        raise RuntimeError("Unsupported Ubuntu runner architecture: " + arch)
    release = dict(line.split("=", 1) for line in Path("/etc/os-release").read_text().splitlines() if "=" in line)
    suite = release.get("VERSION_CODENAME", "").strip('"')
    if not re.fullmatch(r"[a-z0-9]+", suite):
        raise RuntimeError("The Ubuntu runner codename is invalid")
    report = {"status": "PENDING", "architecture": arch, "codename": suite, "attempts": [], "sources": [],
              "resolver": Path("/etc/resolv.conf").read_text(), "scope": "Disposable CI APT mirror selection only; Ubuntu GPG trust, package assertions and app tests remain mandatory."}
    try:
        report["dns"] = []
        for host in dict.fromkeys([urlsplit(ROOTS[arch][0]).hostname, "mirrors.edge.kernel.org", "github.com"]):
            try:
                probe = subprocess.run(["getent", "ahosts", host], capture_output=True, text=True, timeout=5)
                report["dns"].append({"host": host, "exit": probe.returncode, "answers": probe.stdout[:2000]})
            except subprocess.TimeoutExpired:
                report["dns"].append({"host": host, "status": "TIMEOUT_5_SECONDS"})
        with tempfile.TemporaryDirectory(prefix="verified-ubuntu-mirrors-") as temporary:
            directory = Path(temporary)
            if arch == "arm64":
                chosen = verified_mirror(ROOTS[arch], [suite, suite + "-updates", suite + "-backports", suite + "-security"], directory, report["attempts"])
                selected = {"main": chosen, "security": chosen}
            else:
                selected = {"main": verified_mirror(ROOTS[arch], [suite, suite + "-updates", suite + "-backports"], directory, report["attempts"])}
                selected["security"] = verified_mirror(["https://security.ubuntu.com/ubuntu", selected["main"], *ROOTS[arch]], [suite + "-security"], directory, report["attempts"])
            report["selected"] = selected
            paths = [Path("/etc/apt/sources.list"), *sorted(Path("/etc/apt/sources.list.d").glob("*.list")), *sorted(Path("/etc/apt/sources.list.d").glob("*.sources"))]
            for path in paths:
                if not path.is_file():
                    continue
                before = path.read_text()
                after = rewrite_sources(before, selected) if path.suffix == ".sources" else rewrite_list(before, selected)
                report["sources"].append({"path": str(path), "before": before, "after": after,
                    "before_sha256": hashlib.sha256(before.encode()).hexdigest(), "after_sha256": hashlib.sha256(after.encode()).hexdigest()})
                if after != before:
                    path.write_text(after)
            mirror_files = sorted(Path("/etc/apt").glob("apt-mirrors*.txt"))
            report["original_mirror_lists"] = {str(path): path.read_text() for path in mirror_files if path.is_file()}
            # Bound broken DNS/mirror retries instead of consuming the native
            # test budget; APT still fails closed on an unavailable repository.
            Path("/etc/apt/apt.conf.d/99-elichika-ci-mirrors").write_text('Acquire::Retries "1";\nAcquire::http::Timeout "20";\nAcquire::https::Timeout "20";\nAPT::Update::Error-Mode "any";\n')
            report["status"] = "PASS_REACHABLE_UBUNTU_SIGNED_MIRRORS"
    except Exception as error:
        report["status"], report["error"] = "FAIL", str(error)
        raise
    finally:
        (evidence / "apt-mirror-preflight.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({key: report[key] for key in ("status", "architecture", "codename", "selected", "error") if key in report}))


if __name__ == "__main__":
    main()
