# TrashPoint October 2026

Dokumentasi flow trashpoint

---

## 1. Komponen & Wiring

| Komponen | Koneksi | Keterangan |
|---|---|---|
| Raspberry Pi 3B+ | — | Otak smart bin, terhubung WiFi ke Firebase |
| RFID Reader EM4100 125kHz | USB (HID keyboard-emulation) | Membaca kartu siswa; "mengetik" UID + Enter seperti keyboard |
| Sensor IR (chamber) | GPIO 17 (BCM) | Active LOW — mendeteksi ada barang masuk ke chamber |
| Kamera OV5647 (Pi Camera v1) | CSI ribbon | Memotret barang di chamber untuk klasifikasi AI + bukti/log |
| Servo (pemiring chamber) | GPIO 18 (BCM) | SG90-style, PWM 50Hz — miringkan chamber ke kiri (plastik) / kanan (kaleng) |
| Buzzer | GPIO 23 (BCM) | Active buzzer — bunyi saat HIGH |
---

## 2. Flow Robot (Fisik)

Desain: **satu chamber sortir otomatis**. Barang masuk ke chamber, AI
menentukan jenisnya dari foto, lalu servo memiringkan chamber ke sisi yang
sesuai (kiri = plastik, kanan = kaleng).

```
   Siswa datang membawa sampah
              │
              ▼
   Tap kartu RFID di reader
              │
              ▼
   Pi membaca UID kartu → cari siswa di Firebase (field rfidUid)
              │
       ┌──────┴──────┐
       │ tidak ada   │ ketemu
       ▼             ▼
   Buzzer error   Siswa memasukkan sampah ke chamber
   (kartu tak             │
    dikenal)              ▼
                 Sensor IR (GPIO 17) mendeteksi ada barang
                    di dalam chamber
                          │
                          ▼
                 Kamera OV5647 memotret barang
                    → disimpan ke captures/{timestamp}.jpg
                          │
                          ▼
                 Model AI (klasifikasi gambar, TFLite/YOLOv8n-cls)
                    menganalisis foto → PLASTIK / KALENG / LAINNYA
                          │
              ┌───────────┼───────────┐
              │ plastik   │ kaleng    │ lainnya/ragu
              ▼           ▼           ▼
        Servo miring  Servo miring  Buzzer error,
          ke KIRI 🧴     ke KANAN 🥤   barang ditolak
          + buzzer ok    + buzzer ok   (tanpa poin)
              │           │
              └─────┬─────┘
                    ▼
                  Servo kembali ke posisi tengah,
                    Pi menulis ke Firebase:
                    • /transactions  → catatan setoran baru
                    • /users/{uid}   → totalPoints +10/+15,
                      plasticCount/canCount +1, ecoStatus dihitung ulang
                    • /leaderboard/{uid} → mirror totalPoints
                          │
                          ▼
   📱 Aplikasi Android menerima update real-time (< 2 detik):
      counter poin beranimasi + toast "🎉 +X TP earned!"
      (kalau melewati ambang tier → animasi Bumi rank-up)
```

Poin per item: 🧴 botol plastik = **+75 TP**, 🥤 kaleng = **+200 TP**.
Tier: 🌱 0 · ⚔️ 200 · 🦸 500 · 👑 1000 TP (dihitung ulang otomatis tiap setoran).

### Klasifikasi AI — cara kerjanya & cara melatihnya

Model — YOLO/model bawaan tidak mengenal kondisi chamber
kita, jadi wajib dilatih dengan foto dari kamera bin sendiri. Karena di
chamber hanya ada satu barang dengan posisi & kamera tetap, yang dibutuhkan
adalah *image classification* (bukan object detection ala YOLOv8 penuh, yang
terlalu berat untuk Pi 3B+ — bisa 5–15 detik/frame).

Jalur yang disarankan — **Teachable Machine → TensorFlow Lite**:

1. Kumpulkan dataset **pakai kamera Pi langsung di dalam chamber** dengan
   pencahayaan asli: 600 foto per kelas
   (`plastik`, `kaleng`, `kosong/lainnya` — kelas ketiga penting supaya
   barang aneh ditolak, bukan ditebak paksa)
2. teachablemachine.withgoogle.com → Image Project → Standard →
   upload per kelas → Train
3. Export Model → TensorFlow Lite → Floating point →
   dapat `model.tflite` + `labels.txt` → copy ke `raspi/`
4. Di Pi: `pip3 install tflite-runtime` → inferensi 1 foto ±0,5–1 detik

Alternatif kalau ingin tetap memakai ekosistem YOLO: **YOLOv8n-cls**
(varian klasifikasi) dilatih di Google Colab dari folder per kelas, lalu
export ke TFLite/NCNN — hasil sama, setup lebih teknis.

---

## 3. Flow Kode (`main.py`)


`main.py` adalah loop utama yang merangkai semua modul:

```
setup_logging()                  → log ke logs/events.log (rotating 1MB × 3)
FirebaseClient(...)              → koneksi Firebase Admin SDK
RfidReader()                     → grab device USB RFID via evdev
BinSensors()                     → setup GPIO sensor IR + LED
DepositCamera()                  → start kamera OV5647, warm-up 1 detik

while running:
    1. rfid_uid = reader.wait_for_card()
       └─ blocking: tunggu reader "mengetik" digit UID + Enter
    2. uid, user = firebase.find_user_by_rfid(rfid_uid)
       └─ query /users orderByChild("rfidUid") — kalau tidak ketemu:
          LED merah, kembali ke langkah 1
    3. item_type = sensors.wait_for_item()
       └─ polling IR plastik (GPIO 17) & aluminium (GPIO 27),
          timeout 15 detik — kalau timeout: LED merah, ulang
    4. photo = camera.capture()
       └─ simpan JPEG ke captures/{timestamp}.jpg
    5. firebase.record_deposit(uid, item_type)
       ├─ push /transactions {studentId, itemType, points, timestamp, binId}
       ├─ transaction atomik di /users/{uid}: totalPoints, count, ecoStatus
       └─ update /leaderboard/{uid}/totalPoints
    6. sensors.flash_success()  → LED hijau kedip

Ctrl+C / SIGTERM → cleanup semua (reader, kamera, GPIO)
```

### Peran tiap file

| File | Tanggung jawab |
|---|---|
| `main.py` | Loop utama + signal handler + logging |
| `firebase_client.py` | Wrapper Firebase Admin: lookup siswa by RFID, tulis transaksi, update poin atomik, hitung eco tier, mirror leaderboard |
| `rfid_reader.py` | Baca reader USB HID via `evdev`: grab device (biar ketikan tidak bocor ke console), kumpulkan digit sampai Enter → return UID. Auto-detect device, bisa override via env `TRASHPOINT_RFID_DEVICE` |
| `sensor.py` | Sensor IR dua slot (deteksi + bedakan plastik/aluminium) + LED feedback |
| `camera.py` | Capture foto OV5647 via `picamera2` ke `captures/` |
| `requirements.txt` | `firebase-admin`, `evdev`, `RPi.GPIO`, `picamera2` |
| `trashpoint-bin.service` | Unit systemd untuk auto-start saat boot |

### Script test (tanpa Firebase)

| File | Flow |
|---|---|
| `test.py` | IR deteksi → servo buka (90°) + buzzer bunyi; IR clear → servo balik (0°) + buzzer diam |
| `test2.py` | IR deteksi → **kamera foto dulu** (`captures/test-*.jpg`) → lalu servo buka + buzzer bunyi bersamaan; IR clear → servo balik + buzzer diam |

---

## 4. Cara Menjalankan

### Setup awal (sekali saja)

```bash
pip3 install -r requirements.txt

# Service account: Firebase Console → Project Settings →
# Service accounts → Generate new private key
# simpan sebagai raspi/serviceAccountKey.json

export TRASHPOINT_DATABASE_URL=https://trashpoint-8dc2e-default-rtdb.firebaseio.com
```

### Test hardware dulu

```bash
python3 test.py    # servo + buzzer + IR
python3 test2.py   # + kamera
```

### Jalankan bin sungguhan

```bash
python3 main.py
```

### Auto-start saat boot (systemd)

```bash
# edit path & URL di trashpoint-bin.service dulu, lalu:
sudo cp trashpoint-bin.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now trashpoint-bin

# cek status / log:
systemctl status trashpoint-bin
tail -f logs/events.log
```

### Env vars

| Variabel | Default | Fungsi |
|---|---|---|
| `TRASHPOINT_DATABASE_URL` | — (wajib) | URL Realtime Database |
| `TRASHPOINT_SERVICE_ACCOUNT` | `./serviceAccountKey.json` | Path key service account |
| `TRASHPOINT_BIN_ID` | `bin-001` | ID bin yang dicatat di transaksi |
| `TRASHPOINT_RFID_DEVICE` | auto-detect | Override `/dev/input/eventX` reader |

---

## 5. Troubleshooting

- **Kartu tap tapi tidak terbaca** → cek `TRASHPOINT_RFID_DEVICE`; lihat daftar device: `python3 -c "from evdev import list_devices, InputDevice; [print(p, InputDevice(p).name) for p in list_devices()]"`
- **Servo gerak padahal tidak ada objek** → modul IR-mu active HIGH; balik logika `== GPIO.LOW` jadi `== GPIO.HIGH`
- **Kamera error "Camera not found"** → cek ribbon CSI terpasang benar, lalu `libcamera-hello` untuk tes; pastikan `python3-picamera2` terinstal
- **"Unknown card" terus** → field `rfidUid` di `/users/{uid}` harus sama persis dengan digit yang diketik reader (cek di log `Card tapped: ...`)
- **Poin tidak masuk ke app** → cek `logs/events.log`; pastikan URL database benar dan Pi terhubung internet
