# Panduan Training & Uji Coba YOLOv8n-cls

Cara melatih model klasifikasi sampah (plastik / kaleng / lainnya) dengan
**YOLOv8n-cls** dan menjalankannya di Raspberry Pi untuk sortir otomatis.

Pipeline lengkap:

```
Kumpulkan foto (Pi, test2.py) → susun folder dataset → training di Google Colab
→ export TFLite → copy ke Pi → uji classifier (classifier.py) → uji sortir (test3.py)
```

---

## Step 1 — Kumpulkan Dataset (di Raspberry Pi)

Foto **harus** diambil pakai kamera Pi di dalam chamber dengan pencahayaan
asli — jangan pakai foto dari internet/HP, karena kondisi gambarnya beda dan
akurasi model akan jeblok saat dipakai sungguhan.

1. Jalankan `python3 test2.py`
2. Masukkan botol plastik ke chamber → IR terdeteksi → foto otomatis
   tersimpan ke `captures/`
3. Keluarkan, masukkan lagi dengan **posisi/orientasi berbeda** — ulangi
4. Lakukan untuk semua variasi:

| Kelas | Target foto | Variasi yang penting |
|---|---|---|
| `plastik` | 150–300 | merek beda, penyok, dengan/tanpa label & tutup, posisi miring/tegak/terbalik |
| `kaleng` | 150–300 | merek beda, penyok, posisi berdiri/rebah |
| `lainnya` | 100–200 | chamber kosong, tangan, kertas, sampah lain — apapun yang harus DITOLAK |

5. Copy semua foto ke laptop:

```powershell
scp -r pi@<IP_RASPI>:/home/pi/captures ./dataset-mentah
```

---

## Step 2 — Susun Folder Dataset

Pilah foto ke struktur ini (≈80% train, ≈20% val):

```
dataset/
  train/
    kaleng/    foto1.jpg, foto2.jpg, ...
    lainnya/   ...
    plastik/   ...
  val/
    kaleng/    ...
    lainnya/   ...
    plastik/   ...
```

> ⚠️ Nama folder = nama kelas. Ultralytics mengurutkan kelas **secara
> alfabetis** (`kaleng`, `lainnya`, `plastik`) — urutan ini harus sama persis
> dengan isi `labels.txt` di Step 4.

Zip foldernya: klik kanan `dataset/` → Compress jadi `dataset.zip`.

---

## Step 3 — Training di Google Colab (gratis, pakai GPU)

1. Buka https://colab.research.google.com → New Notebook
2. Runtime → Change runtime type → **T4 GPU**
3. Upload `dataset.zip` (ikon folder di kiri → upload), lalu jalankan sel-sel ini:

```python
!pip install ultralytics
!unzip -q dataset.zip
```

```python
from ultralytics import YOLO

model = YOLO("yolov8n-cls.pt")          # model klasifikasi terkecil (cocok untuk Pi)
results = model.train(
    data="dataset",
    epochs=50,
    imgsz=224,
    patience=10,                        # stop otomatis kalau tidak membaik
)
```

```python
# cek akurasi di data validasi — usahakan top-1 accuracy > 0.95
metrics = model.val()
print(metrics.top1)
```

```python
# export ke TFLite untuk dijalankan di Raspberry Pi
model.export(format="tflite", imgsz=224)
```

4. Download hasilnya dari panel file Colab:
   `runs/classify/train/weights/best_saved_model/best_float32.tflite`

> Kalau akurasinya rendah (< 0.9): tambah foto (terutama di kelas yang sering
> salah), pastikan tidak ada foto salah folder, lalu training ulang.

---

## Step 4 — Pasang Model di Raspberry Pi

1. Rename `best_float32.tflite` → `model.tflite`
2. Buat file `labels.txt` (urutan **alfabetis**, satu kelas per baris):

```
kaleng
lainnya
plastik
```

3. Kirim keduanya ke Pi, ke folder yang sama dengan script:

```powershell
scp model.tflite labels.txt pi@<IP_RASPI>:/home/pi/
```

4. Install dependensi inferensi di Pi:

```bash
pip3 install tflite-runtime numpy pillow
```

> Kalau `tflite-runtime` tidak tersedia untuk OS-mu, alternatif:
> `pip3 install tensorflow` (lebih berat tapi sama fungsinya).

---

## Step 4b — (Opsional) Model INT8 yang Lebih Cepat

INT8 = bobot model disimpan sebagai angka 8-bit, bukan float32. File jadi
~3,7× lebih kecil (5,8 MB → 1,6 MB) dan biasanya inferensi di CPU ARM
seperti Pi 3B+ lebih cepat. Ulangi tiap kali habis training ulang.

1. Di laptop (Python 3.10+, venv terpisah):

```bash
pip install "ai-edge-quantizer>=0.6.0" "ai-edge-litert>=2.1.4" pillow numpy
python3 quantize_int8.py --dataset ~/Documents/dataset
```

   Script ini mengkalibrasi pakai foto `train/`, lalu membandingkan float vs
   INT8 di foto `val/`. Pakai INT8 hanya kalau akurasinya tidak turun.

2. Kirim `model_int8.tflite` ke Pi, lalu bandingkan kecepatannya di Pi:

```bash
python3 cls2.py captures/*.jpg
TRASHPOINT_MODEL=/home/pi/model_int8.tflite python3 cls2.py captures/*.jpg
```

3. Kalau INT8 lebih cepat dan hasilnya sama, aktifkan di
   `trashpoint-bin.service` (tambahkan baris di bawah `[Service]`):

```
Environment=TRASHPOINT_MODEL=/home/pi/model_int8.tflite
```

   Balik ke model float cukup dengan menghapus baris itu.

---

## Step 5 — Uji Classifier Saja (tanpa hardware)

Tes model dengan salah satu foto yang sudah ada:

```bash
python3 classifier.py captures/test-20260612-101500.jpg
# Result: plastik (97.3%)
```

Coba beberapa foto botol, kaleng, dan chamber kosong — pastikan hasilnya
benar dan confidence-nya tinggi (> 90%) sebelum lanjut ke hardware.

---

## Step 6 — Uji Sortir Lengkap (`test3.py`)

```bash
python3 test3.py
```

Flow yang terjadi:

1. IR (GPIO 17) mendeteksi barang di chamber
2. Kamera memotret → `captures/sort-{timestamp}.jpg`
3. Model mengklasifikasi foto (±1–3 detik di Pi 3B+)
4. Hasil:
   - **plastik** → 1 beep, servo miring KIRI (30°), tahan 1,2 detik, balik tengah
   - **kaleng** → 2 beep, servo miring KANAN (150°), tahan, balik tengah
   - **lainnya** atau confidence < 60% → 3 beep error, chamber tidak miring (ditolak)
5. Tunggu chamber kosong → siap barang berikutnya

### Yang bisa kamu setel di atas file `test3.py`

| Konstanta | Default | Fungsi |
|---|---|---|
| `CENTER_ANGLE` / `LEFT_ANGLE` / `RIGHT_ANGLE` | 90 / 30 / 150 | Sudut servo — sesuaikan dengan mekanik chamber-mu |
| `TILT_HOLD_S` | 1.2 | Lama chamber miring (biar barang sempat meluncur keluar) |
| `CONFIDENCE_THRESHOLD` | 0.60 | Di bawah ini barang ditolak — naikkan kalau sering salah sortir, turunkan kalau terlalu sering menolak |

---

## Troubleshooting

- **`ModuleNotFoundError: tflite_runtime`** → ulangi Step 4 no. 4, atau pakai `pip3 install tensorflow`
- **Hasil klasifikasi selalu kelas yang sama** → cek urutan `labels.txt` (harus alfabetis, sama dengan folder training); cek foto test memang dari kamera chamber
- **Confidence selalu rendah** → dataset kurang variasi atau pencahayaan saat inferensi beda dengan saat pengambilan dataset — tambahkan foto dengan kondisi sekarang dan training ulang
- **Servo bergetar/lemah saat miring** → beri power supply terpisah 5V untuk servo (jangan ambil dari pin 5V Pi kalau servonya besar), ground tetap disatukan
- **Inferensi > 5 detik** → pastikan export pakai `imgsz=224` (bukan 640) dan yang dipakai `best_float32.tflite`
- **Barang sudah keluar tapi IR masih LOW** → posisi sensor IR mungkin menghadap dinding chamber yang memantul — atur ulang sudut sensor atau putar potensiometer sensitivitas di modul IR
