import os
import json
import time
import logging
import requests
from requests.adapters import HTTPAdapter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime

# ── Config ────────────────────────────────────────────────────────────────────
DATA_DIR         = '/home/suno/Downloads/_archives/Data_Sample'
FHIR_URL         = os.getenv('FHIR_URL', 'http://localhost:8081/fhir').rstrip('/')
MAX_WORKERS      = int(os.getenv('MAX_WORKERS', '2'))   # file nhẹ / batch
MAX_WORKERS_HEAVY = int(os.getenv('MAX_WORKERS_HEAVY', '1'))  # transaction nặng
BIG_FILE_MB      = float(os.getenv('BIG_FILE_MB', '1.0'))
HEAVY_ENTRY_COUNT = int(os.getenv('HEAVY_ENTRY_COUNT', '300'))
SERVER_MAX_BUNDLE_SIZE = int(os.getenv('SERVER_MAX_BUNDLE_SIZE', '0'))
MAX_RETRIES      = int(os.getenv('MAX_RETRIES', '2'))
CONNECT_TIMEOUT  = int(os.getenv('CONNECT_TIMEOUT', '10'))
READ_TIMEOUT_BASE = int(os.getenv('READ_TIMEOUT_BASE', '180'))
READ_TIMEOUT_PER_ENTRY = float(os.getenv('READ_TIMEOUT_PER_ENTRY', '0.45'))
READ_TIMEOUT_MAX = int(os.getenv('READ_TIMEOUT_MAX', '1800'))
LOG_FILE         = f'fhir_upload_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'

HEADERS = {'Content-Type': 'application/fhir+json'}

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(),
    ]
)
log = logging.getLogger(__name__)

# ── Result tracking ───────────────────────────────────────────────────────────


@dataclass
class Summary:
    ok:      list = field(default_factory=list)
    failed:  list = field(default_factory=list)
    skipped: list = field(default_factory=list)

summary = Summary()


@dataclass
class BundleInfo:
    file_path: str
    filename: str
    size_mb: float
    bundle_type: str
    entry_count: int
    is_heavy: bool

# ── Core upload ───────────────────────────────────────────────────────────────
def load_bundle_info(file_path: str) -> BundleInfo | None:
    filename = os.path.basename(file_path)
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            bundle = json.load(f)
    except json.JSONDecodeError:
        log.warning(f"[INVALID JSON] {filename}")
        return None

    if bundle.get('resourceType') != 'Bundle':
        log.warning(f"[SKIP] {filename} — resourceType={bundle.get('resourceType')}")
        return None

    size_mb = os.path.getsize(file_path) / (1024 * 1024)
    bundle_type = bundle.get('type', 'unknown')
    entry_count = len(bundle.get('entry', []))
    is_heavy = (
        bundle_type == 'transaction'
        and (size_mb >= BIG_FILE_MB or entry_count >= HEAVY_ENTRY_COUNT)
    )

    return BundleInfo(
        file_path=file_path,
        filename=filename,
        size_mb=size_mb,
        bundle_type=bundle_type,
        entry_count=entry_count,
        is_heavy=is_heavy,
    )


def build_session(pool_size: int) -> requests.Session:
    session = requests.Session()
    adapter = HTTPAdapter(pool_connections=pool_size, pool_maxsize=pool_size)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session


def compute_read_timeout(info: BundleInfo) -> int:
    estimated = int(READ_TIMEOUT_BASE + (info.entry_count * READ_TIMEOUT_PER_ENTRY))
    return min(READ_TIMEOUT_MAX, max(READ_TIMEOUT_BASE, estimated))


def upload_bundle(session: requests.Session, info: BundleInfo) -> str:
    timeout = (CONNECT_TIMEOUT, compute_read_timeout(info))

    if info.is_heavy:
        log.info(
            f"[HEAVY {info.size_mb:.1f}MB | {info.entry_count} entries | {info.bundle_type}] "
            f"{info.filename} | timeout={timeout[1]}s"
        )

    if SERVER_MAX_BUNDLE_SIZE > 0 and info.entry_count > SERVER_MAX_BUNDLE_SIZE:
        log.error(
            f"[SKIP TOO LARGE] {info.filename} | entries={info.entry_count} "
            f"> server limit {SERVER_MAX_BUNDLE_SIZE}"
        )
        return 'failed'

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with open(info.file_path, 'r', encoding='utf-8') as f:
                bundle = json.load(f)

            resp = session.post(FHIR_URL, headers=HEADERS, json=bundle, timeout=timeout)

            if resp.status_code in (200, 201):
                log.info(f"[OK] {info.filename} | {info.entry_count} entries")
                return 'ok'

            if 400 <= resp.status_code < 500:
                log.error(
                    f"[FAIL-4xx] {info.filename} | {resp.status_code} | "
                    f"entries={info.entry_count} | {resp.text[:300]}"
                )
                return 'failed'

            log.warning(
                f"[RETRY {attempt}/{MAX_RETRIES}] {info.filename} | "
                f"HTTP {resp.status_code} | entries={info.entry_count}"
            )

        except requests.exceptions.ConnectionError as e:
            if 'Connection reset by peer' in str(e) or 'Connection aborted' in str(e):
                log.warning(
                    f"[RESET {attempt}/{MAX_RETRIES}] {info.filename} — "
                    f"server reset ({info.size_mb:.1f}MB, {info.entry_count} entries)"
                )
            else:
                log.warning(f"[CONN ERROR {attempt}/{MAX_RETRIES}] {info.filename} | {e}")

        except requests.exceptions.Timeout:
            log.warning(
                f"[TIMEOUT {attempt}/{MAX_RETRIES}] {info.filename} — "
                f"read_timeout={timeout[1]}s | entries={info.entry_count}"
            )

        except requests.exceptions.RequestException as e:
            log.warning(f"[REQUEST ERROR {attempt}/{MAX_RETRIES}] {info.filename} | {e}")

        if attempt < MAX_RETRIES:
            wait = (2 ** attempt) * (3 if info.is_heavy else 1)
            time.sleep(wait)

    log.error(f"[GIVE UP] {info.filename} ({info.size_mb:.1f}MB, {info.entry_count} entries)")
    return 'failed'


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    log.info(f"FHIR endpoint: {FHIR_URL}")
    all_files = sorted(
        os.path.join(DATA_DIR, f)
        for f in os.listdir(DATA_DIR)
        if f.endswith('.json')
    )

    if not all_files:
        log.warning(f"Không tìm thấy file .json nào trong {DATA_DIR}")
        return

    bundle_infos: list[BundleInfo] = []
    scan_started = time.time()
    log.info(f"Bắt đầu quét metadata {len(all_files)} file JSON trong {DATA_DIR}")
    for index, file_path in enumerate(all_files, start=1):
        info = load_bundle_info(file_path)
        if info is None:
            summary.skipped.append(os.path.basename(file_path))
            continue
        bundle_infos.append(info)
        if index % 10 == 0 or index == len(all_files):
            elapsed = time.time() - scan_started
            log.info(
                f"  Đã quét: {index}/{len(all_files)} | hợp lệ={len(bundle_infos)} "
                f"| skipped={len(summary.skipped)} | elapsed={elapsed:.1f}s"
            )

    if not bundle_infos:
        log.warning("Không có bundle hợp lệ để upload")
        return

    light_files = [info for info in bundle_infos if not info.is_heavy]
    heavy_files = [info for info in bundle_infos if info.is_heavy]
    oversized_files = [
        info for info in bundle_infos
        if SERVER_MAX_BUNDLE_SIZE > 0 and info.entry_count > SERVER_MAX_BUNDLE_SIZE
    ]

    total = len(bundle_infos)
    log.info(
        f"Tổng hợp lệ: {total} file(s) — nhẹ/batch: {len(light_files)}, "
        f"transaction nặng: {len(heavy_files)}, vượt ngưỡng server: {len(oversized_files)}"
    )
    log.info(
        f"Workers: {MAX_WORKERS} (nhẹ/batch) / {MAX_WORKERS_HEAVY} (transaction nặng) | "
        f"server_max_bundle_size={'disabled' if SERVER_MAX_BUNDLE_SIZE <= 0 else SERVER_MAX_BUNDLE_SIZE}"
    )
    start = time.time()
    done  = 0

    def process_batch(infos: list[BundleInfo], workers: int):
        nonlocal done
        if not infos:
            return
        session = build_session(max(workers, 1))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(upload_bundle, session, info): info for info in infos}
            for future in as_completed(futures):
                result = future.result()
                getattr(summary, result).append(futures[future].filename)
                done += 1
                if done % 10 == 0 or done == total:
                    log.info(f"  Tiến độ: {done}/{total} | OK={len(summary.ok)} FAIL={len(summary.failed)} SKIP={len(summary.skipped)}")
        session.close()

    if light_files:
        log.info("── Upload file nhẹ / batch ──")
        process_batch(light_files, MAX_WORKERS)

    if heavy_files:
        log.info("── Upload transaction nặng ──")
        process_batch(heavy_files, MAX_WORKERS_HEAVY)

    elapsed = time.time() - start
    log.info("=" * 60)
    log.info(f"HOÀN THÀNH trong {elapsed:.1f}s")
    log.info(f"  Thành công : {len(summary.ok)}")
    log.info(f"  Thất bại   : {len(summary.failed)}")
    log.info(f"  Bỏ qua     : {len(summary.skipped)}")

    if summary.failed:
        log.info("  File lỗi:")
        for f in summary.failed:
            log.info(f"    - {f}")

    log.info(f"Log đã lưu: {LOG_FILE}")


if __name__ == '__main__':
    main()
