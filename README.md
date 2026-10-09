# Google Find Hub Traccar Relay

[Repositori ini](https://github.com/FoxLost/google-find-hub-traccar) menjalankan relay yang mengambil daftar perangkat dan lokasi dari Google Find Hub, lalu mengirimkannya ke endpoint OsmAnd milik Traccar. API Google yang dipakai bersifat tidak resmi dan dapat berubah atau berhenti bekerja tanpa pemberitahuan. Relay tidak membuka port masuk; data yang belum terkirim disimpan di SQLite dan dicoba lagi pada siklus berikutnya.

## Arsitektur

1. `findhub-relay provision` dijalankan di host provisioning yang memiliki Chrome. Proses autentikasi interaktif menghasilkan `relay-credentials.json`.
2. File credential dipasang ke container sebagai `/data/credentials.json`. Container berjalan sebagai UID/GID `10001`, menggunakan root filesystem read-only, dan hanya menulis ke `/data`.
3. `findhub_relay` menjaga listener FCM/MCS, meminta daftar perangkat dan lokasi ke Google Find Hub, lalu memasukkan lokasi ke `/data/relay.db`.
4. Pengirim OsmAnd mengirim antrean secara berurutan ke `TRACCAR_URL`. Respons HTTP 2xx menandai baris sebagai terkirim; kegagalan mempertahankan baris untuk percobaan berikutnya.
5. Status siklus, error terakhir, dan jumlah antrean dibaca oleh perintah `healthcheck` dan Docker `HEALTHCHECK`.

`device_id` Google adalah unique identifier Traccar. Isi kolom identifier perangkat di Traccar dengan nilai `device_id`, bukan nama tampilan perangkat.

## Yang berubah

- Relay operasional berada di package `findhub_relay` dengan subperintah `provision`, `devices`, `once`, `daemon`, dan `healthcheck`.
- Daemon menggunakan antrean SQLite yang tahan restart, pencatatan health, retry pengiriman OsmAnd, dan refresh perangkat berkala.
- Provisioning browser dipisahkan dari image runtime. Image runtime hanya memasang dependency yang diperlukan relay.
- `Dockerfile` dan `compose.yaml` menjalankan service tanpa port masuk, sebagai UID `10001`, dengan network eksternal Traccar dan hardening container.
- `requirements-runtime.txt` memisahkan dependency runtime dari dependency provisioning/development.

## Yang dihapus

Target relay ini tidak lagi menyediakan atau mendokumentasikan:

- Flask microservice;
- alur interaktif legacy `main.py`;
- firmware ESP32 dan Zephyr;
- DULT owner lookup;
- PlaySound dan custom tracker registration;
- firmware CI serta dokumentasi iOS upstream.

Komponen dan instruksi tersebut bukan bagian dari deployment relay Traccar. Kredit untuk komponen awal tetap diberikan kepada Leon Böttger dan proyek upstream [GoogleFindMyTools](https://github.com/leonboe1/GoogleFindMyTools).

## Requirements

- Linux/WSL2 dengan checkout dan direktori state di filesystem Linux, bukan di `/mnt/c`;
- Python 3.11+ dan Google Chrome hanya pada host provisioning;
- Docker Engine atau Docker Desktop dengan Docker Compose v2;
- Traccar yang menerima protokol OsmAnd pada TCP `5055`;
- akses keluar TCP `443` ke endpoint HTTPS Google dan TCP `5228` ke `mtalk.google.com`;
- akun Google yang dapat menyelesaikan autentikasi provisioning.

Docker Desktop harus mengaktifkan WSL Integration untuk distro yang dipakai. Verifikasi dari WSL:

```bash
docker version
docker compose version
```

## Clone dan provisioning di WSLg

Simpan checkout dan state di filesystem Linux WSL. WSLg dapat menjalankan Chrome Linux untuk autentikasi; Chrome Windows tidak dapat dikendalikan langsung oleh `chromedriver` Linux.

```bash
git clone https://github.com/FoxLost/google-find-hub-traccar.git
cd google-find-hub-traccar
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
# Edit .env hanya untuk TRACCAR_URL, interval, dan DEVICE_IDS.
# Pasang Google Chrome versi Linux saat ini di distro WSL.
mkdir -p provision-data
CREDENTIALS_FILE="$PWD/relay-credentials.json" \
DATA_DIRECTORY="$PWD/provision-data" \
./bin/findhub-relay provision
```

Fallback module jika launcher checkout belum tersedia:

```bash
python -m findhub_relay provision
```

Stage credential untuk UID runtime. Nama source selalu `relay-credentials.json`; file yang dibaca container bernama `credentials.json` di dalam mount `/data`.

```bash
sudo install -d -o 10001 -g 10001 -m 0700 relay-data
sudo install -o 10001 -g 10001 -m 0600 \
  "$PWD/relay-credentials.json" relay-data/credentials.json
```

Jangan commit, menampilkan, atau memasukkan credential ke image. Direktori `relay-data` dan file credential harus berada di luar source control.

### Fallback provisioning native Windows

Jika Chrome Linux tidak tersedia, jalankan provisioning native di Windows dengan dependency development dan Chrome Windows, lalu salin hanya `relay-credentials.json` ke checkout WSL dan ulangi staging UID `10001` di atas. Jangan gunakan direktori Windows sebagai bind mount `relay-data`.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
New-Item -ItemType Directory -Force .\provision-data | Out-Null
$env:CREDENTIALS_FILE = Join-Path (Get-Location) "relay-credentials.json"
$env:DATA_DIRECTORY = Join-Path (Get-Location) "provision-data"
python -m findhub_relay provision
```

## Traccar dan Docker network

Compose memakai external network agar container Traccar dapat ditemukan sebagai `traccar`:

```bash
docker network create tracking
docker network connect tracking traccar
```

Jika network atau nama container berbeda, sesuaikan `.env`. Untuk Traccar di network Docker:

```dotenv
TRACCAR_URL=http://traccar:5055
```

Untuk Traccar native di Windows:

```dotenv
TRACCAR_URL=http://host.docker.internal:5055
```

Traccar native harus listen pada alamat non-loopback dan firewall harus mengizinkan TCP `5055`. Compose menyediakan mapping `host.docker.internal` ke host gateway.

## Menjalankan relay

Bangun dan jalankan daemon:

```bash
docker compose -f compose.yaml build
docker compose -f compose.yaml up -d
```

Referensi CLI singkat:

| Perintah | Fungsi dan prasyarat | Exit penting |
| --- | --- | --- |
| `provision` | Hanya di host; autentikasi interaktif membutuhkan Python 3.11+, dependency `requirements.txt`, dan Chrome. Image runtime sengaja tidak memiliki dependency browser. | `0` jika credential berhasil; non-zero jika provisioning gagal. |
| `devices` | Mengambil perangkat Google dan menyegarkan snapshot SQLite; membutuhkan credential valid serta akses Google/FCM. | `0` jika berhasil; non-zero jika gagal. |
| `once` | Menjalankan satu siklus, mengantrekan lokasi, lalu mengirim antrean; membutuhkan credential valid, `TRACCAR_URL`, dan akses upstream. | `0` untuk siklus `ok`, `1` untuk `degraded`, `2` untuk error konfigurasi/fatal. |
| `daemon` | Menjalankan siklus berkala dan listener FCM; membutuhkan credential valid, `TRACCAR_URL`, dan akses upstream. | Berjalan sampai dihentikan; `0` saat berhenti dengan signal, non-zero untuk error fatal. |
| `healthcheck` | Membaca health state dari SQLite; tidak menjalankan listener baru. | `0` sehat, `1` tidak sehat, `2` untuk error konfigurasi/fatal. |
| `--help` | Menampilkan pemakaian dan opsi. | `0`; tidak membutuhkan runtime atau credential. |

Di host checkout gunakan `./bin/findhub-relay <perintah>`; fallback module-nya
adalah `python -m findhub_relay <perintah>`. Di image, executable terpasang di
`/usr/local/bin/findhub-relay` dan dapat dipanggil sebagai `findhub-relay`.

Saat daemon berjalan, gunakan hanya operasi baca/operasional melalui `exec`:

```bash
docker compose exec relay findhub-relay healthcheck
docker compose exec relay findhub-relay --help
```

Untuk `devices` atau `once`, hentikan daemon lebih dulu dan hidupkan kembali
setelah command selesai agar tidak ada listener FCM/siklus ganda atau race pada
state bersama:

```bash
docker compose stop relay
docker compose run --rm relay devices
docker compose run --rm relay once
docker compose start relay
```

Untuk terminal interaktif:

```bash
docker compose exec -it relay sh
findhub-relay --help
findhub-relay healthcheck
exit
```

Daemon foreground dapat dijalankan dengan `docker compose up relay`.

Compose `up -d` memakai `daemon` sebagai command default dan restart policy `unless-stopped`. Pemeriksaan tambahan:

```bash
docker compose -f compose.yaml ps
docker compose -f compose.yaml logs --tail=100 relay
```

## Konfigurasi environment

Simpan pengaturan lokal di `.env`; jangan menyimpan credential atau token di sana.

Edit `.env` hanya untuk endpoint (`TRACCAR_URL`), interval, dan `DEVICE_IDS`.

| Variabel | Default | Fungsi |
| --- | --- | --- |
| `RELAY_DATA_DIR` | `./relay-data` | Direktori host yang di-mount ke `/data` oleh Compose |
| `TRACKING_NETWORK` | `tracking` | Nama external Docker network |
| `TZ` | `UTC` | Zona waktu container |
| `DATA_DIRECTORY` | `/data` | Direktori state di dalam container |
| `CREDENTIALS_FILE` | `/data/credentials.json` | File credential di dalam container |
| `TRACCAR_URL` | `http://traccar:5055` | Endpoint Traccar OsmAnd |
| `DEVICE_IDS` | semua perangkat | Daftar `device_id` dipisahkan koma |
| `POLL_INTERVAL_SECONDS` | `900` | Jeda antar siklus daemon |
| `LOCATION_TIMEOUT_SECONDS` | `30` | Batas waktu request lokasi |
| `DEVICE_REFRESH_INTERVAL_SECONDS` | `3600` | Interval refresh daftar perangkat |
| `LOG_LEVEL` | `INFO` | `CRITICAL`, `ERROR`, `WARNING`, `INFO`, atau `DEBUG` |

`TRACCAR_URL` wajib tersedia untuk `once` dan `daemon`. `devices`, `once`, dan `daemon` memerlukan credential yang valid.

## SQLite, backup, dan update

`/data/relay.db` menyimpan snapshot perangkat, state health, credential FCM yang dipakai runtime, dan `outbound_positions`. Lokasi baru memakai pasangan unik `(device_id, timestamp)` agar tidak digandakan. Baris dengan `sent_at` kosong tetap berada di antrean. Hanya respons HTTP 2xx yang menandai baris terkirim; koneksi gagal, HTTP 429, dan HTTP 5xx membiarkan antrean untuk retry. SQLite memakai WAL dan file database dibuat mode `0600`.

Untuk backup konsisten, hentikan daemon sebentar. Arsip berisi credential dan harus diperlakukan sebagai secret:

```bash
docker compose -f compose.yaml stop relay
archive="relay-backup-$(date +%Y%m%d-%H%M%S).tgz"
sudo install -m 0600 /dev/null "$archive"
sudo tar -C relay-data -czf "$archive" relay.db credentials.json
sudo chmod 0600 "$archive"
sudo chown "$USER":"$(id -gn)" "$archive"
docker compose -f compose.yaml start relay
```

Simpan arsip di luar checkout dengan akses terbatas. Setelah memperbarui source:

```bash
docker compose -f compose.yaml build --pull
docker compose -f compose.yaml up -d --force-recreate
docker compose -f compose.yaml ps
```

Bind mount `/data` mempertahankan `relay.db` dan credential saat image diganti.

## Troubleshooting dan keamanan

- Credential tidak ditemukan atau ditolak: pastikan `relay-data/credentials.json` ada, mode file `0600`, dimiliki `10001:10001`, dan direktori `relay-data` mode `0700`.
- Traccar tidak terhubung: periksa `docker network inspect tracking`, resolusi nama `traccar`, dan port OsmAnd `5055`; jangan gunakan port web UI Traccar.
- Health stale/unhealthy: lihat log, pastikan daemon sudah menyelesaikan siklus, `/data` writable oleh UID `10001`, serta akses keluar ke Google dan Traccar tersedia.
- `devices` atau `once` gagal: periksa credential, `DEVICE_IDS`, endpoint, dan network reachability; command mengembalikan exit status non-zero saat gagal.
- Jangan bind-mount state dari `/mnt/c`; permission Linux dan mode file dapat berubah.

Image tidak memiliki listener inbound atau published port, root filesystem read-only, semua capability dijatuhkan, dan `no-new-privileges` aktif. Detail network, provisioning, backup, update, dan diagnosis ada di [docs/deployment.md](docs/deployment.md).

## Lisensi dan atribusi

Kode ini tetap menggunakan [GPL-3.0](LICENSE). Atribusi legal upstream kepada Leon Böttger dan komponen [GoogleFindMyTools](https://github.com/leonboe1/GoogleFindMyTools) dipertahankan; metadata citation repo ini menunjuk ke [FoxLost/google-find-hub-traccar](https://github.com/FoxLost/google-find-hub-traccar).
