# Deployment relay

Image relay menjalankan `findhub-relay daemon` sebagai UID/GID
`10001`. Root filesystem image read-only; hanya `/data` yang writable. Service
tidak membuka atau mempublikasikan port dan mengirim data keluar ke endpoint
OsmAnd Traccar melalui Docker network. Command shell yang tidak diberi label
PowerShell dijalankan dari WSL.

## Prasyarat dan checkout

Gunakan checkout dan direktori state pada filesystem Linux WSL, bukan langsung di
`/mnt/c`. Bind mount dari filesystem Windows tidak selalu mempertahankan owner
dan mode Linux yang diperlukan UID/GID `10001`.

```bash
git clone https://github.com/FoxLost/google-find-hub-traccar.git
cd google-find-hub-traccar
cp .env.example .env
# Edit .env hanya untuk TRACCAR_URL, interval, dan DEVICE_IDS.

docker version
docker compose version
```

Provisioning membutuhkan Python 3.11+, dependency development dari
`requirements.txt`, dan Google Chrome pada host provisioning. Image runtime
memakai dependency terpisah dari `requirements-runtime.txt`.

## Kontrak runtime

Compose menetapkan:

- `DATA_DIRECTORY=/data`;
- `CREDENTIALS_FILE=/data/credentials.json`;
- `TRACCAR_URL=http://traccar:5055` secara default.

CLI juga menerima `DEVICE_IDS`, `POLL_INTERVAL_SECONDS`,
`LOCATION_TIMEOUT_SECONDS`, `DEVICE_REFRESH_INTERVAL_SECONDS`, dan `LOG_LEVEL`.
Pengaturan Compose-only adalah `RELAY_DATA_DIR` (direktori host yang di-mount ke
`/data`), `TRACKING_NETWORK`, dan `TZ`. Jangan menaruh credential atau token di
dokumentasi, `.env`, atau source control.

## Provision credential pada workstation

Provisioning dilakukan di luar image runtime karena autentikasi Google bersifat
interaktif dan membutuhkan browser. WSLg dapat memakai Chrome Linux yang
terpasang di dalam distro WSL; `chromedriver` Linux tidak dapat mengendalikan
Chrome Windows.

```bash
# WSL shell, dari root checkout
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
# Pasang Google Chrome Linux versi saat ini di distro WSL.
mkdir -p provision-data
CREDENTIALS_FILE="$PWD/relay-credentials.json" \
DATA_DIRECTORY="$PWD/provision-data" \
./bin/findhub-relay provision
```

Fallback module jika launcher checkout belum tersedia:

```bash
python -m findhub_relay provision
```

Saat provisioning meminta username, gunakan alamat email yang sama dengan akun
Chrome. File hasil provisioning selalu disebut `relay-credentials.json` pada
host. Stage ke direktori runtime dengan owner dan mode yang ketat:

```bash
sudo install -d -o 10001 -g 10001 -m 0700 relay-data
sudo install -o 10001 -g 10001 -m 0600 \
  "$PWD/relay-credentials.json" relay-data/credentials.json
```

File source dan file staged tetap private. File tersebut tidak pernah disalin ke
image; container hanya membaca `/data/credentials.json` dari bind mount.
`.dockerignore` mengecualikan credential, `.env`, dan `relay-data` dari build
context.

### Fallback native Windows

Jika Chrome Linux tidak tersedia, jalankan provisioning pada checkout Windows,
lalu salin hanya `relay-credentials.json` ke checkout WSL. Jangan memakai path
Windows sebagai bind mount `relay-data`.

```powershell
# PowerShell, di checkout Windows
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
New-Item -ItemType Directory -Force .\provision-data | Out-Null
$env:CREDENTIALS_FILE = Join-Path (Get-Location) "relay-credentials.json"
$env:DATA_DIRECTORY = Join-Path (Get-Location) "provision-data"
python -m findhub_relay provision
```

Setelah menyalin file ke filesystem WSL, jalankan perintah `sudo install` di atas
agar owner `10001:10001`, mode direktori `0700`, dan mode file `0600` benar.

## Network Traccar

Compose memakai external network. Buat sekali jika belum ada:

```bash
docker network create tracking
```

Hubungkan container Traccar yang sudah berjalan, atau gunakan network dengan
nama yang sama pada deployment Traccar:

```bash
docker network connect tracking traccar
```

Jika nama network berbeda, set `TRACKING_NETWORK` di `.env`. Untuk Traccar yang
berjalan di network Docker, gunakan endpoint OsmAnd berikut; `5055` bukan port
web UI:

```dotenv
TRACCAR_URL=http://traccar:5055
```

Untuk Traccar native di Windows:

```dotenv
TRACCAR_URL=http://host.docker.internal:5055
```

Traccar native harus listen pada alamat non-loopback dan Windows Firewall harus
mengizinkan inbound TCP `5055`. Compose menyediakan mapping
`host.docker.internal` ke host gateway, termasuk pada Docker Engine Linux
modern.

## Akses keluar Google

Relay membutuhkan outbound TCP `443` untuk endpoint HTTPS Google, termasuk
`android.googleapis.com`, `android.clients.google.com`, dan endpoint
FCM/Firebase. Listener FCM/MCS memakai `mtalk.google.com:5228`; izinkan outbound
TCP `5228` ke host tersebut. Relay tidak membutuhkan inbound port.

## Menjalankan image Docker Hub

Jalur ini memakai image `herlambang333/google-find-hub-traccar`; tag yang
direkomendasikan adalah `latest` dan `1.0.1`. Image saat ini hanya mendukung
`linux/amd64`. Credential tetap harus diprovision di host dan distage sebelum
container dibuat (langkah `install` di atas).

Buat dedicated network jika belum ada, lalu hubungkan container Traccar:

```bash
docker network inspect tracking >/dev/null 2>&1 || docker network create tracking
docker network connect tracking traccar
```

Perintah `docker network connect` hanya perlu dijalankan jika container Traccar
belum terhubung ke network tersebut. Pull dan jalankan daemon dengan hardening
yang sama seperti Compose:

```bash
docker pull herlambang333/google-find-hub-traccar:latest
docker run -d --name google-find-hub-traccar \
  --restart unless-stopped --init --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --cap-drop ALL --security-opt no-new-privileges --stop-timeout 45 \
  -v "$PWD/relay-data:/data" --network tracking \
  -e TRACCAR_URL=http://traccar:5055 \
  -e DATA_DIRECTORY=/data -e CREDENTIALS_FILE=/data/credentials.json \
  herlambang333/google-find-hub-traccar:latest
```

Untuk Traccar native di Windows, gunakan host gateway dan endpoint berikut
(Traccar harus listen pada alamat non-loopback dan firewall mengizinkan TCP
`5055`):

```bash
docker run -d --name google-find-hub-traccar \
  --restart unless-stopped --init --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --cap-drop ALL --security-opt no-new-privileges --stop-timeout 45 \
  --add-host host.docker.internal:host-gateway \
  -v "$PWD/relay-data:/data" --network tracking \
  -e TRACCAR_URL=http://host.docker.internal:5055 \
  -e DATA_DIRECTORY=/data -e CREDENTIALS_FILE=/data/credentials.json \
  herlambang333/google-find-hub-traccar:latest
```

Setelah daemon berjalan detached, buka terminal container dengan:

```bash
docker exec -it google-find-hub-traccar sh
```

Jangan menjalankan `devices` atau `once` dengan `exec` ketika daemon utama
aktif. Untuk one-off yang aman, hentikan container utama, gunakan mount,
network, dan environment yang sama, lalu hidupkan kembali container utama:

```bash
docker stop google-find-hub-traccar
docker run --rm --init --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --cap-drop ALL --security-opt no-new-privileges --stop-timeout 45 \
  -v "$PWD/relay-data:/data" --network tracking \
  -e TRACCAR_URL=http://traccar:5055 \
  -e DATA_DIRECTORY=/data -e CREDENTIALS_FILE=/data/credentials.json \
  herlambang333/google-find-hub-traccar:latest devices
docker run --rm --init --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --cap-drop ALL --security-opt no-new-privileges --stop-timeout 45 \
  -v "$PWD/relay-data:/data" --network tracking \
  -e TRACCAR_URL=http://traccar:5055 \
  -e DATA_DIRECTORY=/data -e CREDENTIALS_FILE=/data/credentials.json \
  herlambang333/google-find-hub-traccar:latest once
docker start google-find-hub-traccar
```

Ganti URL dan tambahkan `--add-host` seperti contoh Windows jika Traccar native.

Terminal, CLI, log, dan lifecycle container:

```bash
docker exec -it google-find-hub-traccar sh
findhub-relay --help
findhub-relay healthcheck
exit
docker logs --tail=100 google-find-hub-traccar
docker inspect google-find-hub-traccar
docker stop google-find-hub-traccar
docker rm google-find-hub-traccar
docker pull herlambang333/google-find-hub-traccar:latest
# Jalankan kembali command daemon di atas setelah update.
```

Mount `/data` mempertahankan database dan credential saat container dibuat ulang.
Image tidak mempublikasikan port; root filesystem read-only, semua capability
dijatuhkan, dan `no-new-privileges` aktif.

## Build dan jalankan daemon

Untuk deployment dari source dengan Compose, setelah credential distage dan
network tersedia:

```bash
docker compose -f compose.yaml build
docker compose -f compose.yaml up -d
```

Compose mengaktifkan `restart: unless-stopped`, stop grace period 45 detik,
init process, root filesystem read-only, `/tmp` tmpfs, semua capability
dijatuhkan, `no-new-privileges`, dan rotasi Docker JSON logs. Service tidak
mempublikasikan port.

Periksa konfigurasi Compose tanpa menampilkan environment lokal:

```bash
docker compose -f compose.yaml config --quiet
```

## Referensi CLI dan verifikasi

Entrypoint image menerima command sebagai argumen:

```text
ENTRYPOINT ["findhub-relay"]
CMD ["daemon"]
```

Di host checkout gunakan `./bin/findhub-relay <perintah>`; fallback module-nya
adalah `python -m findhub_relay <perintah>`. Image memasang executable di
`/usr/local/bin/findhub-relay`; `provision` hanya untuk host: perintah ini
membutuhkan Python 3.11+, dependency `requirements.txt`, dan Chrome serta tidak
dapat dijalankan di image runtime yang sengaja tidak memiliki dependency browser.

| Perintah | Fungsi dan prasyarat | Exit penting |
| --- | --- | --- |
| `provision` | Autentikasi interaktif dan pembuatan credential di host; membutuhkan Chrome. | `0` jika berhasil; non-zero jika gagal. |
| `devices` | Mengambil perangkat dan menyegarkan snapshot SQLite; membutuhkan credential valid dan akses Google/FCM. | `0` jika berhasil; non-zero jika gagal. |
| `once` | Menjalankan satu siklus, mengantrekan lokasi, lalu mengirim antrean; membutuhkan credential valid, `TRACCAR_URL`, dan upstream. | `0` untuk `ok`, `1` untuk `degraded`, `2` untuk error fatal/konfigurasi. |
| `daemon` | Menjalankan siklus berkala dan listener FCM; membutuhkan credential valid, `TRACCAR_URL`, dan upstream. | Berjalan sampai dihentikan; `0` saat berhenti dengan signal, non-zero untuk error fatal. |
| `healthcheck` | Membaca health state SQLite tanpa memulai listener. | `0` sehat, `1` tidak sehat, `2` untuk error konfigurasi/fatal. |
| `--help` | Menampilkan pemakaian. | `0`; tanpa credential atau service aktif. |

Saat daemon berjalan, `exec` hanya dipakai untuk pemeriksaan operasional:

```bash
docker compose exec relay findhub-relay healthcheck
docker compose exec relay findhub-relay --help
```

Untuk `devices` dan `once`, hentikan daemon sebelum menjalankan container
sekali-pakai, lalu restart sesudahnya. Ini mencegah listener FCM/siklus ganda
dan race pada state bersama:

```bash
docker compose stop relay
docker compose run --rm relay devices
docker compose run --rm relay once
docker compose start relay
```

Terminal interaktif:

```bash
docker compose exec -it relay sh
findhub-relay --help
findhub-relay healthcheck
exit
```

Untuk daemon foreground, gunakan `docker compose up relay`.

Periksa service dan log:

```bash
docker compose -f compose.yaml ps
docker compose -f compose.yaml logs --tail=100 relay
```

Docker healthcheck menjalankan command yang sama dengan start period dua menit.
Status stale/unhealthy berarti daemon belum mencatat siklus yang cukup baru,
atau state, credential, dan konektivitas upstream perlu diperiksa.

### Log, health, dan privasi

Gunakan log container bersama hasil `healthcheck`; koneksi ulang FCM hanya
menjelaskan lifecycle koneksi Google dan **bukan** bukti bahwa Traccar menerima
posisi. Perintah ringkas untuk Compose:

```bash
docker compose -f compose.yaml logs --tail=100 relay
docker compose -f compose.yaml exec relay findhub-relay healthcheck
```

Untuk container yang dijalankan langsung dengan `docker run`:

```bash
docker logs --tail=100 google-find-hub-traccar
docker exec google-find-hub-traccar findhub-relay healthcheck
```

Pesan operasional berikut stabil pada prefix dan nama field:

| Level | Prefix/template persis | Field dan arti |
| --- | --- | --- |
| INFO | `Relay daemon started poll_interval_seconds=<seconds> device_filter=all` | Daemon mulai untuk semua perangkat; interval polling dicatat tanpa daftar ID. |
| INFO | `Relay daemon started poll_interval_seconds=<seconds> device_filter_count=<count>` | Daemon mulai dengan filter; hanya jumlah ID yang dicatat. |
| INFO | `Relay cycle started` | Siklus baru dimulai. |
| INFO | `Find Hub query succeeded device_id=<id> reports=<count>` | Query satu perangkat berhasil; hanya jumlah laporan yang dicatat. |
| ERROR | `Find Hub query failed device_id=<id> error_type=<class>` | Query perangkat gagal; tipe exception dicatat tanpa teks exception. |
| INFO | `OsmAnd delivery accepted device_id=<id> position_timestamp=<timestamp> http_status=<2xx>` | Traccar menerima satu posisi antrean dengan respons 2xx. |
| WARNING | `OsmAnd delivery HTTP failure device_id=<id> position_timestamp=<timestamp> http_status=<status>` | Traccar mengembalikan status non-2xx. |
| WARNING | `OsmAnd delivery transport failure device_id=<id> position_timestamp=<timestamp> error_type=<class>` | Request gagal sebelum memperoleh status HTTP. |
| ERROR | `Relay cycle failed error_type=<class>` | Siklus gagal secara keseluruhan; daemon akan mencoba siklus berikutnya. |
| INFO | `Relay cycle completed status=<status> devices_selected=<count> devices_queried=<count> positions_queued=<count> positions_sent=<count> delivery_failures=<count> pending_positions=<count> duration_seconds=<seconds>` | Ringkasan tunggal hasil siklus dan sisa antrean. |
| INFO | `Relay daemon waiting next_cycle_seconds=<seconds>` | Daemon menunggu jadwal siklus berikutnya; ini bukan heartbeat. |
| INFO | `Relay daemon stopped gracefully` | Daemon berhenti dengan normal. |
| WARNING | `Relay cycle pending count failed error_type=<class>` | Penghitungan diagnostik antrean gagal; ringkasan memakai `pending_positions=-1` tanpa mengubah hasil siklus. |

Signal normal utama adalah `Relay cycle completed status=ok`. Nilai
`status=degraded` berarti siklus selesai tetapi satu atau lebih query/pengiriman
gagal; `status=failed` berarti siklus tidak dapat diselesaikan. Periksa
`delivery_failures` dan `pending_positions` untuk membedakan kegagalan kirim
dari backlog. Hanya HTTP 2xx yang menandai posisi sebagai terkirim. Request
error, HTTP 429, atau HTTP 5xx menghentikan batch saat itu; HTTP 4xx biasa
tidak menghentikan posisi berikutnya. Semua baris yang masih pending tetap
durable di SQLite dan dicoba lagi pada siklus berikutnya.

`healthcheck` mencetak JSON state yang mencakup `daemon_status`,
`cycle_status`, `pending_positions`, `stale`, `healthy`, waktu lifecycle, dan
`last_error`. Exit `0` berarti daemon `running`, siklus terakhir `ok`, schema
sesuai, dan state belum stale. Exit `1` berarti state tidak sehat, termasuk
`degraded`, `failed`, daemon berhenti, atau siklus stale; exit `2` berarti
error konfigurasi/fatal saat command dijalankan. Docker menjalankan command
yang sama setiap 30 detik, dengan start period dua menit, timeout 10 detik, dan
3 percobaan.

Pesan operasional relay pada tabel ini dapat memuat `device_id` yang
dikonfigurasi, jumlah, timing, status, dan kelas error, tetapi tidak pernah
memuat koordinat atau payload lokasi, body respons, URL endpoint, credential,
token, atau payload FCM. Field health `last_error` menyimpan konteks aman berupa
perangkat/kelas error atau jumlah kegagalan delivery, bukan teks exception
mentah.


## Backup

Hentikan daemon sebentar agar backup SQLite konsisten. Arsip di bawah memuat
credential dan harus diperlakukan sebagai secret:

```bash
docker compose -f compose.yaml stop relay
archive="relay-backup-$(date +%Y%m%d-%H%M%S).tgz"
sudo install -m 0600 /dev/null "$archive"
sudo tar -C relay-data -czf "$archive" relay.db credentials.json
sudo chmod 0600 "$archive"
sudo chown "$USER":"$(id -gn)" "$archive"
docker compose -f compose.yaml start relay
```

Simpan arsip di luar checkout dengan akses terbatas. Jangan menampilkan isi
arsip atau file credential.

## Update dan restart

Setelah memperbarui checkout dan meninjau perubahan dependency runtime:

```bash
docker compose -f compose.yaml build --pull
docker compose -f compose.yaml up -d --force-recreate
docker compose -f compose.yaml ps
docker compose -f compose.yaml exec relay findhub-relay healthcheck
```

Bind mount `/data` mempertahankan `relay.db` dan `credentials.json` ketika image
diganti.

## Troubleshooting

- `credentials file not found` atau credential tidak valid: pastikan
  `relay-data/credentials.json` ada, mode file `0600`, owner `10001:10001`, dan
  direktori `relay-data` mode `0700`.
- Connection error Traccar: jalankan `docker network inspect tracking`, pastikan
  container Traccar terhubung dengan DNS name `traccar`, dan gunakan port
  OsmAnd `5055`.
- Health stale: lihat `docker compose logs relay`, pastikan `/data` writable
  oleh UID `10001`, lalu periksa akses ke Google dan Traccar.
- `devices` atau `once` gagal: periksa credential, `DEVICE_IDS`, endpoint, dan
  network reachability sebelum mencoba lagi.
- Error akibat bind mount: pindahkan checkout dan `relay-data` dari `/mnt/c` ke
  filesystem ext4 WSL dan ulangi staging dengan owner/mode di atas.
