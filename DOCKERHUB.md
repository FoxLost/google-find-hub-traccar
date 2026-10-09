# Google Find Hub Traccar Relay

<!-- Maintainers metadata: Docker Hub short description (<=100 chars)
Relay Docker Google Find Hub ke Traccar melalui protokol OsmAnd.
-->

Relay ini mengambil perangkat dan lokasi dari Google Find Hub lalu mengirimkannya
ke endpoint OsmAnd Traccar. API Google yang digunakan **tidak resmi** dan dapat
berubah atau berhenti tanpa pemberitahuan.

## Image dan prasyarat

- Image: `herlambang333/google-find-hub-traccar`
- Tag yang direkomendasikan: `latest` dan `1.1.0`.
- Arsitektur yang didukung: `linux/amd64` dan `linux/arm64`.
- Tag legacy `1.0.1` tetap amd64-only.
- Provision credential di host terlebih dahulu; image runtime tidak menyediakan
  browser atau alur provisioning.
- Traccar harus menerima protokol OsmAnd pada TCP `5055`.
- Docker Engine/Desktop dengan network Docker dan akses keluar ke layanan Google.

Provision credential pada host sesuai [panduan deployment](https://github.com/FoxLost/google-find-hub-traccar/blob/main/docs/deployment.md#provision-credential-pada-workstation),
lalu stage ke `/data`:

```bash
sudo install -d -o 10001 -g 10001 -m 0700 relay-data
sudo install -o 10001 -g 10001 -m 0600 \
  "$PWD/relay-credentials.json" relay-data/credentials.json
docker network create tracking
```

Jika Traccar berjalan sebagai container, hubungkan container tersebut ke network
`tracking` (contoh nama DNS `traccar`):

```bash
docker network connect tracking traccar
```

## Menjalankan daemon

Pull image dan jalankan container tanpa port masuk:

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

Pada host ARM64, Docker memilih varian native secara otomatis. Validasi versi:

```bash
docker run --rm --platform linux/arm64 \
  herlambang333/google-find-hub-traccar:1.1.0 --version
```

Untuk Traccar native di Windows, pastikan Traccar listen pada alamat non-loopback
dan firewall mengizinkan TCP `5055`, lalu gunakan endpoint host gateway:

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

## CLI dan operasi

Volume `/data` menyimpan `relay.db` dan credential runtime. Environment utama:

| Variabel | Nilai umum | Keterangan |
| --- | --- | --- |
| `TRACCAR_URL` | `http://traccar:5055` | Endpoint OsmAnd Traccar |
| `DATA_DIRECTORY` | `/data` | Direktori state |
| `CREDENTIALS_FILE` | `/data/credentials.json` | Credential staged |
| `DEVICE_IDS` | kosong | ID perangkat, dipisahkan koma; kosong berarti semua |
| `POLL_INTERVAL_SECONDS` | `900` | Jeda siklus daemon |
| `LOCATION_TIMEOUT_SECONDS` | `30` | Timeout request lokasi |
| `DEVICE_REFRESH_INTERVAL_SECONDS` | `3600` | Interval refresh perangkat |
| `LOG_LEVEL` | `INFO` | Level log |
| `TZ` | `UTC` | Zona waktu |

Saat daemon berjalan, gunakan `exec` hanya untuk terminal atau operasi baca:

```bash
docker exec -it google-find-hub-traccar sh
findhub-relay --help
findhub-relay healthcheck
exit
docker logs --tail=100 google-find-hub-traccar
docker inspect google-find-hub-traccar
```

Signal normal utama adalah `Relay cycle completed status=ok`; koneksi ulang FCM
bukan bukti pengiriman Traccar. Lihat tabel field, retry antrean, health, dan
batas privasi di
[Log, health, dan privasi](https://github.com/FoxLost/google-find-hub-traccar/blob/main/docs/deployment.md#log-health-dan-privasi).

Jangan menjalankan `once` atau `devices` melalui `exec` sementara daemon aktif.
Untuk one-off, hentikan daemon, jalankan container sementara dengan mount,
network, dan environment yang sama, kemudian hidupkan daemon kembali:

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

Perintah lifecycle dan update:

```bash
docker stop google-find-hub-traccar
docker rm google-find-hub-traccar
docker pull herlambang333/google-find-hub-traccar:latest
# Jalankan kembali command daemon di atas.
```

## Keamanan

Container berjalan sebagai UID/GID `10001`, root filesystem read-only, tanpa
capability Linux, dengan `no-new-privileges`, dan tidak mempublikasikan port.
Simpan `relay-data` di filesystem Linux yang mendukung owner/mode (bukan bind
mount Windows yang tidak konsisten), jangan commit atau menampilkan credential,
dan pertahankan direktori mode `0700` serta file mode `0600`.

## Tautan

- [Repositori GitHub](https://github.com/FoxLost/google-find-hub-traccar)
- [Deployment lengkap](https://github.com/FoxLost/google-find-hub-traccar/blob/main/docs/deployment.md)
- [Lisensi GPL-3.0](https://github.com/FoxLost/google-find-hub-traccar/blob/main/LICENSE)
